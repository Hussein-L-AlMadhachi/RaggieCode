"""
Agent run loops for Raggie (interactive and non-interactive modes).
"""

import json
import sys
from importlib.metadata import version
from prompt_toolkit import prompt
from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live

from Agent.effort_levels import EFFORT_LEVELS, DEFAULT_EFFORT, effort_name
from Agent.chat_history_db import set_session_effort, get_session_effort, get_session_depth

console = Console()
GREEN = "\033[32m"
DIM = "\033[2m"
RESET = "\033[0m"


def _prompt_effort(session_id, value=None):
    """Ask the user to pick an effort level and store it on the session."""
    current = get_session_effort(session_id)
    default_num = current if current is not None else DEFAULT_EFFORT

    for num, info in EFFORT_LEVELS.items():
        marker = " (selected)" if num == default_num else ""
        print(f"  {num}. {info['name']}{marker}")

    while True:

        if value is None:
            try:
                print(f"\nEffort level:")
                choice = prompt(f"Select effort (1-{len(EFFORT_LEVELS)}) [{default_num}]: ").strip()
            except (EOFError, KeyboardInterrupt):
                effort = default_num
                set_session_effort(session_id, effort)
                return effort
        else:
            choice = value

        if not choice:
            effort = default_num
            break
        try:
            effort = int(choice)
        except ValueError:
            print("Invalid number. Try again.")
            continue
        if effort not in EFFORT_LEVELS:
            print(f"Pick a number between 1 and {len(EFFORT_LEVELS)}.")
            continue
        break

    set_session_effort(session_id, effort)
    return effort


class StreamState:
    """Holds streaming display state across event calls."""
    __slots__ = ("reasoning_started", "response_started", "live", "accumulated")

    def __init__(self):
        self.reasoning_started = False
        self.response_started = False
        self.live = None
        self.accumulated = ""

    def _stop_live(self):
        if self.live is not None:
            self.live.stop()
            self.live = None
        self.response_started = False


def _print_event(event, state, depth=0, model=""):
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

    elif kind == "reasoning":
        state._stop_live()
        if state.reasoning_started:
            print(f"{RESET}")
            state.reasoning_started = False
        content = event[1]
        print(f"{DIM}")
        console.print(Markdown(content))
        print(f"{RESET}")

    elif kind == "reasoning_chunk":
        state._stop_live()
        if not state.reasoning_started:
            print(f"{DIM}", end="", flush=True)
            state.reasoning_started = True
        print(event[1], end="", flush=True)

    elif kind == "response":
        state._stop_live()
        if state.reasoning_started:
            print(f"{RESET}")
            state.reasoning_started = False
        content = event[1]
        print(f"{GREEN}\n\nAgent ({model}:{depth}):{RESET}")
        console.print(Markdown(content))

    elif kind == "response_chunk":
        if not state.response_started:
            if state.reasoning_started:
                print(f"{RESET}")
                state.reasoning_started = False
            print(f"{GREEN}\n\nAgent ({model}:{depth}):{RESET}")
            state.response_started = True
            state.live = Live(
                Markdown(event[1]),
                console=console,
                refresh_per_second=12,
                transient=True,
            )
            state.live.start()
            state.accumulated = event[1]
        else:
            state.accumulated += event[1]
            state.live.update(Markdown(state.accumulated))

    elif kind == "response_end":
        final_content = state.accumulated
        state._stop_live()
        if final_content:
            console.print(Markdown(final_content))

    elif kind == "error":
        state._stop_live()
        if state.reasoning_started:
            print(f"{RESET}")
            state.reasoning_started = False
        print(f"Error: {event[1]}")

    return state


def run_interactive(agent, role):
    """Run the interactive agent loop.

    Args:
        agent: An Agent instance with tools and commands already set up.
        role: The role name string.
    """
    model_name = agent.roles[role].get("model", "unknown")
    print(f"{GREEN}Raggie Agent ({role}) v{version('raggiecode')} - Interactive Mode{RESET}")
    print(f"{GREEN}Press Esc followed by Enter to send message, or type 'exit' to quit{RESET}")
    print("-" * 50)
    print("\nuse /help to see all available commands")

    try:
        state = StreamState()
        depth = get_session_depth(agent.session_id)
        model_name = agent.roles[role].get("model", "unknown")
        for event in agent.resume_dangling_tool_work():
            state = _print_event(event, state, depth, model_name)
    except KeyboardInterrupt:
        print("\n[interrupted]")
    except EOFError:
        print("\n\nAgent: Goodbye!")
        return

    while True:
        try:
            current = get_session_effort(agent.session_id)
            if current is None:
                set_session_effort(agent.session_id, DEFAULT_EFFORT)
                current = DEFAULT_EFFORT
            print(f"\n{DIM}Effort: {effort_name(current)} - to change it use /effort{RESET}")
            print(f"{GREEN}\n\nYou:{RESET}")
            user_input = prompt("> ", multiline=True)
        except (EOFError, KeyboardInterrupt):
            print("\n\nAgent: Goodbye!")
            break

        if user_input.lower().strip() in ['exit', 'quit']:
            break

        if not user_input.strip():
            continue

        try:
            state = StreamState()
            depth = get_session_depth(agent.session_id)
            model_name = agent.roles[role].get("model", "unknown")
            for event in agent.start(user_input):
                state = _print_event(event, state, depth, model_name)
        except KeyboardInterrupt:
            print("\n[interrupted]")
            continue
        except EOFError:
            print("\n\nAgent: Goodbye!")
            break

        print()


def run_non_interactive(agent, prompt_text, effort=None):
    """Run the agent with a single prompt and exit.

    Args:
        agent: An Agent instance with tools and commands already set up.
        prompt_text: The user prompt string.
        effort: Optional effort level number (1-5). Defaults to session's current or DEFAULT_EFFORT.
    """
    if effort is not None:
        set_session_effort(agent.session_id, effort)
    elif get_session_effort(agent.session_id) is None:
        set_session_effort(agent.session_id, DEFAULT_EFFORT)

    try:
        state = StreamState()
        for event in agent.start(prompt_text):
            if event[0] == "error":
                state._stop_live()
                if state.reasoning_started:
                    print()
                    state.reasoning_started = False
                print(f"Error: {event[1]}", file=sys.stderr)
                sys.exit(1)
            state = _print_event(event, state, get_session_depth(agent.session_id), agent.roles[agent.agent_role].get("model", "unknown"))
    except KeyboardInterrupt:
        print("\n[interrupted]")
    except EOFError:
        print("\nAgent: Goodbye!")
