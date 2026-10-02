"""Configurable I/O backend for Raggie.

All interactive terminal I/O on the agent path (status output, confirmations,
free-form questions) goes through this module so the process can switch
between modes:

- ``terminal``: normal interactive CLI. Output to stdout via rich, questions
  via ``input()``.
- ``acp``: headless ACP agent mode. Output goes to stderr (stdout is the
  JSON-RPC channel in stdio mode); confirmations are bridged to the ACP
  client through a per-thread permission handler, or answered by the
  auto-approve policy when no interactive client can be asked (HTTP
  transport without ``--acp-auto-approve``).
"""

import os
import re
import sys
import termios
import threading

from rich.console import Console

from Tools.utils import BLUE, RESET

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

MODE_TERMINAL = "terminal"
MODE_ACP = "acp"

_mode = MODE_TERMINAL
_console = None
_auto_approve = False
_debug = False
_local = threading.local()


def _flush_stdin():
    """Flush the kernel's terminal input buffer before showing a prompt.

    When a user pastes multi-line text (e.g. "y\\ny\\ny\\n"), the first line
    is consumed by the current prompt and the remaining lines stay in the
    kernel's input queue. The next prompt would pick them up   auto-approving
    commands the user never reviewed. Calling tcflush(TCIFLUSH) before each
    prompt discards any pending input so every prompt gets a fresh answer.
    """
    try:
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except (OSError, ValueError, AttributeError):
        pass


def set_debug(flag):
    """Enable/disable process-wide debug output. Set once at startup from the
    CLI flag; agents (including subagents) read it as their default."""
    global _debug
    _debug = bool(flag)


def get_debug():
    return _debug


def set_mode(mode, *, auto_approve=False):
    """Switch the I/O mode. Must be called before the agent starts."""
    global _mode, _console, _auto_approve
    if mode not in (MODE_TERMINAL, MODE_ACP):
        raise ValueError(f"Unknown I/O mode: {mode}")
    _mode = mode
    _auto_approve = auto_approve
    _console = None


def get_mode():
    return _mode


def is_headless():
    """True when running without an interactive terminal (ACP mode)."""
    return _mode != MODE_TERMINAL


def set_auto_approve(flag):
    global _auto_approve
    _auto_approve = bool(flag)


def get_console():
    """Shared rich Console.

    Writes to stderr in ACP mode so stdout stays a clean protocol channel.
    """
    global _console
    if _console is None:
        _console = Console(stderr=is_headless())
    return _console


def set_permission_handler(handler):
    """Install a permission handler for the current thread.

    ACP prompt worker threads use this to route confirmations to the client
    via ``session/request_permission``. The handler is a callable
    ``(title: str, detail: str) -> bool``.
    """
    _local.permission_handler = handler


def clear_permission_handler():
    _local.permission_handler = None


def set_ask_handler(handler):
    """Install a free-form ask handler for the current thread.

    ACP prompt worker threads use this to route ``ask()`` questions to the
    client (e.g. the web UI's AskPanel). The handler is a callable
    ``(message: str) -> str``.
    """
    _local.ask_handler = handler


def clear_ask_handler():
    _local.ask_handler = None


def confirm(title, detail=""):
    """Ask the user to approve an action. Returns True when approved.

    In terminal mode, only ``y``/``Y`` (approve) and ``n``/``N`` (refuse) are
    accepted. Any other input re-prompts until a valid answer is given.
    """
    if _mode == MODE_TERMINAL:
        prompt_text = f"{title}\n"
        if detail:
            prompt_text += f"{detail}\n"
        prompt_text += "? (y/n): "
        while True:
            _flush_stdin()
            try:
                answer = input(prompt_text)
            except KeyboardInterrupt:
                print()
                raise SystemExit(0)
            except EOFError:
                print()
                raise SystemExit(0)
            stripped = answer.strip().lower()
            if stripped == "y":
                return True
            if stripped == "n":
                return False
            # Invalid input   re-prompt
            print("Please answer 'y' or 'n'.")

    handler = getattr(_local, "permission_handler", None)
    if handler is not None:
        title = _ANSI_RE.sub("", title)
        detail = _ANSI_RE.sub("", detail)
        try:
            return bool(handler(title, detail))
        except Exception as err:
            print(
                f"Permission request failed ({err}); falling back to policy.",
                file=sys.stderr,
            )
    return _auto_approve


# Return values for confirm_with_always.
ALLOW = "yes"
REJECT = "no"
ALLOW_ALWAYS = "always"


def confirm_with_always(title, detail=""):
    """Ask the user to approve an action with an "always" option.

    Returns one of ``ALLOW`` ("yes"), ``REJECT`` ("no"), or
    ``ALLOW_ALWAYS`` ("always"). In terminal mode, uses ``prompt_toolkit``
    for a proper input field. In headless/ACP mode, routes through the
    permission handler (which may offer an "allow_always" option) and
    falls back to the auto-approve policy.
    """
    if _mode == MODE_TERMINAL:
        from prompt_toolkit import prompt as pt_prompt
        from prompt_toolkit.formatted_text import ANSI as PtANSI

        # ANSI codes in the title are parsed into prompt_toolkit styles so
        # the confirmation renders in color (yellow title, blue options).
        prompt_text = f"{title}\n"
        if detail:
            prompt_text += f"{detail}\n"
        prompt_text += f"? {BLUE}(y)es (n)o (a)lways: {RESET}"
        while True:
            _flush_stdin()
            try:
                answer = pt_prompt(PtANSI(prompt_text))
            except KeyboardInterrupt:
                print()
                raise SystemExit(0)
            except EOFError:
                print()
                raise SystemExit(0)
            stripped = answer.strip().lower()
            if stripped in ("y", "yes"):
                return ALLOW
            if stripped in ("n", "no"):
                return REJECT
            if stripped in ("a", "always"):
                return ALLOW_ALWAYS
            print("Please answer 'y', 'n', or 'a'.")

    handler = getattr(_local, "permission_handler", None)
    if handler is not None:
        title = _ANSI_RE.sub("", title)
        detail = _ANSI_RE.sub("", detail)
        try:
            result = handler(title, detail, allow_always=True)
            if result == "always":
                return ALLOW_ALWAYS
            return ALLOW if result else REJECT
        except Exception as err:
            print(
                f"Permission request failed ({err}); falling back to policy.",
                file=sys.stderr,
            )
    return ALLOW if _auto_approve else REJECT


def ask(message, default="", options=None, allow_multiple=False):
    """Ask a free-form question. Headless modes return ``default``.

    In terminal mode, uses ``prompt_toolkit.prompt`` for a proper interactive
    input field (with line editing, history, etc.) instead of bare ``input()``.

    When a thread-local ask handler is installed (e.g. by an ACP worker
    thread), the question is routed to the handler instead. ``options`` is the
    list of predefined option dicts (label/description) from AskUser and
    ``allow_multiple`` says whether several may be selected together; web
    clients render them as clickable choices.
    """
    handler = getattr(_local, "ask_handler", None)
    if handler is not None:
        clean = _ANSI_RE.sub("", message)
        try:
            return str(handler(clean, options=list(options or []), allow_multiple=bool(allow_multiple)))
        except TypeError:
            # Handlers installed before option support existed.
            return str(handler(clean))
    if _mode == MODE_TERMINAL:
        try:
            from prompt_toolkit import prompt as pt_prompt
            # Strip ANSI codes for prompt_toolkit (it handles its own styling)
            clean = _ANSI_RE.sub("", message)
            _flush_stdin()
            return pt_prompt(clean)
        except (KeyboardInterrupt, EOFError):
            print()
            return default
    return default
