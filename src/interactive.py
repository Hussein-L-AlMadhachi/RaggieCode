"""
Agent run loops for Raggie (interactive and non-interactive modes).
"""

import json
import re
import sys
from importlib.metadata import version
from pathlib import Path
from prompt_toolkit import prompt
from rich.console import Console
from rich.markdown import Markdown

from Agent.thinking_modes import THINKING_MODES, DEFAULT_THINKING_MODE, thinking_mode_name
from Agent import chat_lock
from Agent.chat_history_db import set_session_thinking_mode, get_session_thinking_mode, get_session_depth
import io_backend

console = Console()
GREEN = "\033[32m"
DIM = "\033[2m"
RESET = "\033[0m"

# Sentinel returned by run_interactive when the user presses Ctrl+C on the
# master prompt: the caller should go back to the chat selection screen.
BACK_TO_CHAT_SELECT = "chat_select"

# Matches @path/to/file.x:23 and @path/to/file.x:23-43. The lookbehind rejects
# @-mentions embedded in emails/handles, and the mandatory :N suffix ensures
# only explicit line references are expanded.
_FILE_REF_RE = re.compile(r'(?<![\w.@-])@([\w./\\-]+\.[A-Za-z0-9]+):(\d+)(?:-(\d+))?')


def expand_file_references(text):
    """Append referenced code snippets for @path/file.x:N[-M] mentions in user input.

    References pointing to non-existent files are left untouched so emails,
    handles, and plain text pass through unchanged.
    """
    snippets = []
    seen = set()
    for m in _FILE_REF_RE.finditer(text):
        ref = m.group(0)
        if ref in seen:
            continue
        seen.add(ref)

        path_str, start, end = m.group(1), int(m.group(2)), m.group(3)
        end = int(end) if end else start
        if end < start:
            start, end = end, start

        path = Path(path_str)
        if not path.is_file():
            continue

        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        if start > len(lines):
            continue

        end = min(end, len(lines))
        chunk = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
        snippets.append(f"--- {path_str}:{start}-{end} ---\n{chunk}")

    if not snippets:
        return text
    return text + "\n\n<referenced_code>\n" + "\n\n".join(snippets) + "\n</referenced_code>"


def _name_to_thinking_mode():
    """Map lowercase thinking mode name -> level number."""
    return {info["name"].lower(): num for num, info in THINKING_MODES.items()}


def _prompt_thinking_mode(session_id, value=None):
    """Ask the user to pick a thinking mode and store it on the session."""
    current = get_session_thinking_mode(session_id)
    default_num = current if current is not None else DEFAULT_THINKING_MODE
    default_name = thinking_mode_name(default_num).lower()

    for num, info in THINKING_MODES.items():
        marker = " (selected)" if num == default_num else ""
        print(f"  {info['name'].lower()}{marker}")

    # Predefined options so web clients show clickable choices instead of a
    # bare text input (io_backend.ask routes them to the ask handler).
    options = [
        {"label": info["name"].lower(),
         **({"description": "current mode"} if num == default_num else {})}
        for num, info in THINKING_MODES.items()
    ]

    while True:

        if value is None:
            print(f"\nThinking mode:")
            # Route through io_backend.ask: in ACP/headless mode the question
            # goes to the client (ask handler) or falls back to the default
            # when nobody can answer. Reading stdin directly here froze the
            # worker thread forever in web mode (no stdin to read from).
            choice = io_backend.ask(
                f"Select thinking mode [{default_name}]: ", options=options
            ).strip()
        else:
            choice = value

        if not choice:
            mode = default_num
            break
        if choice.lower() in _name_to_thinking_mode():
            mode = _name_to_thinking_mode()[choice.lower()]
            break
        try:
            mode = int(choice)
        except ValueError:
            print(f"Unknown mode. Available: {', '.join(info['name'].lower() for info in THINKING_MODES.values())}")
            continue
        if mode not in THINKING_MODES:
            print(f"Available modes: {', '.join(info['name'].lower() for info in THINKING_MODES.values())}")
            continue
        break

    set_session_thinking_mode(session_id, mode)
    return mode


class StreamState:
    """Holds display state across event calls."""
    __slots__ = ("reasoning_started", "response_started")

    def __init__(self):
        self.reasoning_started = False
        self.response_started = False

    def _stop_live(self):
        self.response_started = False


def _print_event(event, state, depth=0, model="", debug=False):
    """Process a single agent event and update stream state.

    Returns the StreamState (mutated in place).
    """
    kind = event[0]

    if kind == "tool_call":
        state._stop_live()
        if state.reasoning_started:
            print(f"{RESET}")
            state.reasoning_started = False
        tool_name = event[1]
        tool_args = event[2]
        tool_name = tool_name.replace("Ugly", "")
        try:
            args_dict = json.loads(tool_args)
            desc = ", ".join(f"{k}={str(v)[:40]}" for k, v in args_dict.items())
            console.print(f"[dim][tool] {tool_name}({desc})[/dim]")
        except Exception:
            console.print(f"[dim][tool] {tool_name}[/dim]")

    elif kind == "tool_result":
        if debug:
            state._stop_live()
            if state.reasoning_started:
                print(f"{RESET}")
                state.reasoning_started = False
            tool_name, content, is_error = event[1], event[2], event[3]
            label = f"[tool output] {tool_name}" if not is_error else f"[tool error] {tool_name}"
            style = "dim" if not is_error else "red"
            console.print(label, style=style, markup=False)
            if content:
                console.print(str(content), style=style, markup=False)

    elif kind == "reasoning":
        state._stop_live()
        if state.reasoning_started:
            print(f"{RESET}")
            state.reasoning_started = False
        content = event[1]
        print(f"{GREEN}\n\nAgent Reasoning:{RESET}")
        console.print(Markdown(content))

    elif kind == "response":
        state._stop_live()
        if state.reasoning_started:
            print(f"{RESET}")
            state.reasoning_started = False
        content = event[1]
        print(f"{GREEN}\n\nAgent ({model}:{depth}):{RESET}")
        console.print(Markdown(content))

    elif kind == "error":
        state._stop_live()
        if state.reasoning_started:
            print(f"{RESET}")
            state.reasoning_started = False
        print(f"Error: {event[1]}")

    elif kind == "notice":
        state._stop_live()
        if state.reasoning_started:
            print(f"{RESET}")
            state.reasoning_started = False
        # Command handler output (captured verbatim, ANSI codes intact);
        # markup=False so rich doesn't treat [] as markup.
        console.print(event[1], markup=False, highlight=False)

    elif kind == "handover_doc":
        state._stop_live()
        if state.reasoning_started:
            print(f"{RESET}")
            state.reasoning_started = False
        print(f"{GREEN}\n\nAgent handover document:{RESET}")
        console.print(Markdown(event[1]))

    elif kind == "health_stats":
        state._stop_live()
        print(f"\n{event[1]}")

    return state


def run_interactive(agent, role):
    """Run the interactive agent loop.

    Args:
        agent: An Agent instance with tools and commands already set up.
        role: The role name string.
    """
    model_name = agent.roles[role].get("model", "unknown")
    print(f"{GREEN}Raggie Agent ({role}) v{version('raggiecode')} - Interactive Mode{RESET}")
    print("-" * 50)
    print("\nuse /help to see all available commands")

    try:
        state = StreamState()
        depth = get_session_depth(agent.session_id)
        model_name = agent.roles[role].get("model", "unknown")
        for event in agent.resume_dangling_tool_work():
            state = _print_event(event, state, depth, model_name, debug=agent.debug)
    except KeyboardInterrupt:
        print("\n[interrupted]")
    except EOFError:
        print("\n\nAgent: Goodbye!")
        return

    while True:
        try:
            current = get_session_thinking_mode(agent.session_id)
            if current is None:
                set_session_thinking_mode(agent.session_id, DEFAULT_THINKING_MODE)
                current = DEFAULT_THINKING_MODE
            print(f"\n{DIM}Thinking mode: {thinking_mode_name(current)} - to change it use /thinkingMode{RESET}")
            print(f"{DIM}Press Esc followed by Enter to send message, or type 'exit' to quit{RESET}")
            print(f"{GREEN}\n\nYou:{RESET}")
            io_backend._flush_stdin()
            user_input = prompt("❯ ", multiline=True)
        except KeyboardInterrupt:
            # Ctrl+C on the master prompt: go back to the chat selection screen.
            print()
            return BACK_TO_CHAT_SELECT
        except EOFError:
            print("\n\nAgent: Goodbye!")
            return None

        if user_input.lower().strip() in ['exit', 'quit']:
            return None

        if not user_input.strip():
            continue

        # Per-turn lock: hold it only while this single turn runs, so a
        # second raggie instance can grab the chat between prompts.
        if not chat_lock.acquire(agent.chat_id):
            print("This chat is in use by another raggie instance.")
            continue
        try:
            state = StreamState()
            depth = get_session_depth(agent.session_id)
            model_name = agent.roles[role].get("model", "unknown")
            for event in agent.start(expand_file_references(user_input)):
                state = _print_event(event, state, depth, model_name, debug=agent.debug)
        except KeyboardInterrupt:
            print("\n[interrupted]")
        except EOFError:
            print("\n\nAgent: Goodbye!")
            return None
        finally:
            # Runs after the generator is fully consumed, raises, or on the
            # return/continue paths above.
            chat_lock.release(agent.chat_id)

        print()


def run_non_interactive(agent, prompt_text, thinking_mode=None):
    """Run the agent with a single prompt and exit.

    Args:
        agent: An Agent instance with tools and commands already set up.
        prompt_text: The user prompt string.
        thinking_mode: Optional thinking mode number (1-5). Defaults to session's current or DEFAULT_THINKING_MODE.
    """
    if thinking_mode is not None:
        set_session_thinking_mode(agent.session_id, thinking_mode)
    elif get_session_thinking_mode(agent.session_id) is None:
        set_session_thinking_mode(agent.session_id, DEFAULT_THINKING_MODE)

    # Per-turn lock: hold it for the duration of this single turn.
    if not chat_lock.acquire(agent.chat_id):
        print("This chat is in use by another raggie instance.", file=sys.stderr)
        sys.exit(1)

    try:
        state = StreamState()
        for event in agent.start(expand_file_references(prompt_text)):
            if event[0] == "error":
                state._stop_live()
                if state.reasoning_started:
                    print()
                    state.reasoning_started = False
                print(f"Error: {event[1]}", file=sys.stderr)
                sys.exit(1)
            state = _print_event(event, state, get_session_depth(agent.session_id), agent.roles[agent.agent_role].get("model", "unknown"), debug=agent.debug)
    except KeyboardInterrupt:
        print("\n[interrupted]")
    except EOFError:
        print("\nAgent: Goodbye!")
    finally:
        # Covers the error-event sys.exit(1) path above as well.
        chat_lock.release(agent.chat_id)
