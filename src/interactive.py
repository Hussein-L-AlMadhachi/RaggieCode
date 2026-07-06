"""
Agent run loops for Raggie (interactive and non-interactive modes).
"""

import json
import sys
from importlib.metadata import version
from prompt_toolkit import prompt
from rich.console import Console
from rich.markdown import Markdown

console = Console()
GREEN = "\033[32m"
DIM = "\033[2m"
RESET = "\033[0m"


def _print_event(event, stream_reasoning_started, stream_response_started):
    """Process a single agent event and update stream state.

    Returns (stream_reasoning_started, stream_response_started).
    """
    kind = event[0]

    if kind == "tool_call":
        if stream_response_started:
            print()
            stream_response_started = False
        if stream_reasoning_started:
            print(f"{RESET}")
            stream_reasoning_started = False
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
        content = event[1]
        print(f"{DIM}")
        console.print(Markdown(content))
        print(f"{RESET}")

    elif kind == "reasoning_chunk":
        if not stream_reasoning_started:
            print(f"{DIM}", end="", flush=True)
            stream_reasoning_started = True
        print(event[1], end="", flush=True)

    elif kind == "response":
        content = event[1]
        if stream_reasoning_started:
            print(f"{RESET}")
            stream_reasoning_started = False
        print(f"{GREEN}\n\nAgent:{RESET}")
        console.print(Markdown(content))

    elif kind == "response_chunk":
        if not stream_response_started:
            if stream_reasoning_started:
                print(f"{RESET}")
                stream_reasoning_started = False
            print(f"{GREEN}\n\nAgent:{RESET}")
            stream_response_started = True
        print(event[1], end="", flush=True)

    elif kind == "response_end":
        if stream_response_started:
            print()
            stream_response_started = False

    elif kind == "error":
        if stream_response_started:
            print()
            stream_response_started = False
        if stream_reasoning_started:
            print(f"{RESET}")
            stream_reasoning_started = False
        print(f"Error: {event[1]}")

    return stream_reasoning_started, stream_response_started


def run_interactive(agent, role):
    """Run the interactive agent loop.

    Args:
        agent: An Agent instance with tools and commands already set up.
        role: The role name string.
    """
    model_name = agent.roles[role].get("model", "unknown")
    print(f"Raggie Agent ({role}) v{version('raggiecode')} - Interactive Mode")
    print("Press Esc followed by Enter to send message, or type 'exit' to quit")
    print("-" * 50)
    print("\nuse /help to see all available commands")

    try:
        stream_reasoning_started = False
        stream_response_started = False
        for event in agent.resume_dangling_tool_work():
            stream_reasoning_started, stream_response_started = _print_event(
                event, stream_reasoning_started, stream_response_started
            )
    except KeyboardInterrupt:
        print("\n[interrupted]")
    except EOFError:
        print("\n\nAgent: Goodbye!")
        return

    while True:
        try:
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
            stream_reasoning_started = False
            stream_response_started = False
            for event in agent.start(user_input):
                stream_reasoning_started, stream_response_started = _print_event(
                    event, stream_reasoning_started, stream_response_started
                )
        except KeyboardInterrupt:
            print("\n[interrupted]")
            continue
        except EOFError:
            print("\n\nAgent: Goodbye!")
            break

        print()


def run_non_interactive(agent, prompt_text):
    """Run the agent with a single prompt and exit.

    Args:
        agent: An Agent instance with tools and commands already set up.
        prompt_text: The user prompt string.
    """
    try:
        stream_reasoning_started = False
        stream_response_started = False
        for event in agent.start(prompt_text):
            if event[0] == "error":
                if stream_response_started:
                    print()
                if stream_reasoning_started:
                    print()
                print(f"Error: {event[1]}", file=sys.stderr)
                sys.exit(1)
            stream_reasoning_started, stream_response_started = _print_event(
                event, stream_reasoning_started, stream_response_started
            )
    except KeyboardInterrupt:
        print("\n[interrupted]")
    except EOFError:
        print("\nAgent: Goodbye!")
