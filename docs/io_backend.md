# io_backend: Stable API Specification

Version: 1.0 (stable)
Module: `src/io_backend.py`
Audience: developers building custom (non-terminal) frontends for raggie.

This document specifies the public interface of the `io_backend` module. It
is the stable contract between the raggie agent core and any frontend that
wants to drive the agent, whether that frontend is the built-in interactive
terminal, the ACP protocol server, or your own GUI/web/embedded frontend.

---

## 1. Overview and architecture

`io_backend` is the ONLY place where agent code (the `Agent` class, tools in
`src/Tools/`, and commands in `src/Commands/`) touches user-facing I/O. No
tool reads stdin directly or opens its own console: everything goes through
this module. As a result, a frontend plugs into the entire agent stack by
doing exactly two things:

1. Choose a mode (`io_backend.set_mode`).
2. Optionally install a permission handler
   (`io_backend.set_permission_handler`) so permission prompts can be routed
   to your UI.

Architecture diagram:

```
+---------------------------+
| Agent (src/Agent/agent.py)|
+---------------------------+
   |            |        |
   v            v        v
+---------+ +--------+ +-----------+
| Tools/  | |Commands| | Agent loop|
+---------+ +--------+ +-----------+
   \           |        /
    \          v       /
     +--------------------+
     |     io_backend     |   <- the only I/O boundary
     +--------------------+
        |              |
        v              v
 +-------------+  +--------------------+
 | Terminal I/O|  | Headless frontend  |
 | (prompt_    |  | (permission handler|
 |  toolkit,   |  |  + get_console()   |
 |  rich,      |  |  rendered by YOUR  |
 |  stderr)    |  |  UI / protocol)    |
 +-------------+  +--------------------+
```

Reference implementations:

- Terminal frontend: `src/interactive.py` (default mode; `raggie.py main()`
  never calls `set_mode`, so the module defaults to terminal behavior).
- Headless frontend: `src/acp_server/` (`run_stdio` / `run_http` / `run_web`
  call `io_backend.set_mode(io_backend.MODE_ACP, auto_approve=...)` and
  `io_backend.set_debug(...)` before creating the agent
  `RaggieACPAgent`).

Everything below is what you must know to build a third kind of frontend.

---

## 2. Initialization contract

Before you create an `Agent`, you MUST initialize `io_backend`:

```python
import io_backend

io_backend.set_mode(io_backend.MODE_ACP, auto_approve=False)
io_backend.set_debug(debug)
```

### Constants

| Constant         | Value         | Meaning                              |
|------------------|---------------|--------------------------------------|
| `MODE_TERMINAL`  | `'terminal'`  | Interactive terminal frontend        |
| `MODE_ACP`       | `'acp'`       | Headless / protocol (ACP) frontend   |

The module-level default is `MODE_TERMINAL`: a fresh import behaves like the
terminal frontend without any configuration.

### `set_mode(mode, *, auto_approve=False)`

- Switches the I/O mode. Must be called before the agent starts.
- `auto_approve` sets the policy fallback (see section 6).
- Raises `ValueError` if `mode` is not `MODE_TERMINAL` or `MODE_ACP`.
- Changing the mode later resets the shared console created by
  `get_console()`; it will be recreated lazily with the correct
  stderr/stdout target on the next `get_console()` call.

### `set_debug(flag: bool)`

- Enables or disables process-wide debug output. Call it once at startup,
  from your CLI flag; agents (including subagents) read it as their default.

Reference implementations of this contract:

- `src/raggie.py`, `main()`: calls `io_backend.set_debug(...)` first for
  terminal mode (mode stays at the `MODE_TERMINAL` default).
- `src/acp_server/__init__.py`, `run_stdio()`, `run_http()` and `run_web()`
  (web UI): call `io_backend.set_mode(io_backend.MODE_ACP,
  auto_approve=...)` then `io_backend.set_debug(...)` before constructing
  `RaggieACPAgent`.

---

## 3. Output API: `get_console()`

```python
io_backend.get_console() -> rich.console.Console
```

- Returns a shared `rich` `Console` instance. All agent output should go
  through this console.
- The console is created lazily on first call and cached.
- In headless modes (`MODE_ACP`), the console writes to **stderr** so that
  stdout remains a clean protocol channel. In terminal mode it writes to
  stdout as usual.
- A frontend running in a stdio/protocol mode must never write to stdout
  directly; use `get_console()` (which handles the redirection) or stderr.

`set_mode` resets the cached console, so call `get_console()` again after a
mode change rather than holding onto an old instance across modes.

---

## 4. User-interaction API (the core contract)

These three functions are how the agent asks the user anything. Every
frontend must provide sensible behavior for them, either via the terminal
(built-in) or via a permission handler + policy fallback (headless).

### `io_backend.ask(message, default="") -> str`

Free-form question.

- **Thread-local ask handler installed:** routed to the handler (section 5),
  stripped of ANSI codes; the handler's string return becomes the answer.
  This is how the web UI receives `ask_user` questions mid-turn.
- **Terminal mode:** uses `prompt_toolkit.prompt` for a proper interactive
  input field (line editing, history). ANSI escape codes are stripped from
  `message` before it is shown (prompt_toolkit does its own styling).
  `KeyboardInterrupt`/`EOFError` return `default`.
- **Headless modes without a handler:** returns `default` immediately. No
  stdin is touched   this is critical in protocol modes where stdin is the
  protocol stream.

Install/clear helpers: `set_ask_handler(handler)` and
`clear_ask_handler()`, mirroring the permission handler (thread-local).
`src/acp_server/agent.py::_make_ask_handler` is the reference: in web mode
it pushes the question to the browser via `session/request_ask` and returns
the answer from `session/respond_ask`; in stdio mode there is no interactive
client, so it returns `""` (question skipped).

### `io_backend.confirm(title, detail="") -> bool`

Approve/refuse question. Returns `True` when approved.

- **Terminal mode:** prints `title` followed by `? (y/n): ` and enforces
  strict `y`/`Y` / `n`/`N`. Any other input re-prompts until a valid answer
  is given. `KeyboardInterrupt`/`EOFError` exit the process cleanly.
- **Headless modes:** routes to the thread-local permission handler
  (section 5). If no handler is installed, or the handler raises, it falls
  back to the auto-approve policy (section 6); the exception is printed to
  stderr before falling back.
- **Handler semantics:** the handler is called as `handler(title, detail)`
  and ANY truthy return value means approved (`bool(handler(...))` is the
  final answer).

### `io_backend.confirm_with_always(title, detail="") -> str`

Three-way permission question. Returns one of the module constants:

| Constant        | Value      | Meaning                        |
|-----------------|------------|--------------------------------|
| `ALLOW`         | `'yes'`    | Approve once                   |
| `REJECT`        | `'no'`     | Refuse                         |
| `ALLOW_ALWAYS`  | `'always'` | Approve and remember (always)  |

- **Terminal mode:** renders the title (ANSI codes in the title are parsed
  into prompt_toolkit styles, so color survives) with options
  `(y)es (n)o (a)lways` and enforces `y`/`yes`, `n`/`no`, `a`/`always`,
  re-prompting on anything else.
- **Headless modes:** the thread-local permission handler is called as
  `handler(title, detail, allow_always=True)`. The handler may return:
  - a `bool`, `True` maps to `ALLOW`, `False` maps to `REJECT`; or
  - the string `'always'`, mapped to `ALLOW_ALWAYS`.
- If no handler is installed, or the handler raises, the auto-approve policy
  is used: `ALLOW` if auto-approve is on, otherwise `REJECT`.
- `KeyboardInterrupt`/`EOFError` in terminal mode exit the process cleanly.

### ANSI stripping guarantee

Both `confirm` and `confirm_with_always` strip ANSI escape codes from
`title` and `detail` (module-level regex, internal) before passing them to
the handler. Handlers always receive plain text. `ask` applies the same
stripping to its message in terminal mode.

### Who calls these (important for custom frontends)

Path-permission prompts and agent questions route through the same
primitives, you do not need special handling for them:

- **Path-access requests:** `Tools/utils.prompt_path_permission(file_path,
  operation, reason)` guards restricted file access (outside the working
  directory, gitignored files, etc.). In headless modes it calls
  `io_backend.confirm_with_always("Permission requested: <operation> <path>",
  "Reason: <reason>")` and treats `ALLOW_ALWAYS` as "remember for this path
  for the session". On denial it collects an optional denial reason via
  `io_backend.ask(...)` and surfaces it back to the agent. A custom frontend
  therefore receives path-access requests as ordinary three-way permission
  prompts through its handler.
- **Agent questions:** the `ask_user` tool (`src/Tools/ask_user.py`) lets the
  agent ask the user free-form or multiple-choice questions. In headless
  modes it uses `io_backend.ask(hint)` to collect the answer (an empty
  answer is reported to the agent as "User skipped the question"). Your
  frontend receives these as ordinary `ask` prompts; to present them nicely,
  render the question the tool printed via `get_console()` and return the
  user's input through the `ask` contract.

So: implement `ask`, `confirm`, and `confirm_with_always` correctly in your
handler/UI, and path permissions and agent questions work for free.

---

## 5. Permission handler API (the headless integration point)

```python
io_backend.set_permission_handler(handler)
io_backend.clear_permission_handler()
```

The handler is the hook that routes permission prompts to your UI in
headless modes. It is stored in **thread-local storage** (`threading.local`).

### Thread-local means: one handler per worker thread

- `set_permission_handler(handler)` installs `handler` for the **current
  thread only**. Threads that never install a handler see none.
- If your frontend processes each request/prompt on its own thread (the ACP
  server does: each `prompt()` invocation runs on a worker thread), that
  thread MUST install its own handler before running the agent, and should
  clear it afterwards.
- Reference pattern (from `src/acp_server/agent.py`):

```python
def prompt(self, ...):
    io_backend.set_permission_handler(
        self._make_permission_handler(session)
    )
    try:
        ...  # run the agent turn
    finally:
        io_backend.clear_permission_handler()
```

### Handler contract

| Called by                 | Signature                                     | Return                                                        |
|---------------------------|-----------------------------------------------|---------------------------------------------------------------|
| `confirm(title, detail)`  | `handler(title: str, detail: str) -> bool`    | Any truthy value = approved                                   |
| `confirm_with_always`     | `handler(title: str, detail: str, allow_always: bool) -> bool \| str` | `True` -> `ALLOW`, `False` -> `REJECT`, `'always'` -> `ALLOW_ALWAYS` |

Notes:

- `title` and `detail` arrive ANSI-stripped (plain text).
- `confirm` calls the handler with exactly two positional arguments;
  `confirm_with_always` calls it with `allow_always=True` as a keyword
  argument. Define your handler as `(title, detail, allow_always=False)` to
  satisfy both.
- Exceptions raised inside the handler are caught by `io_backend`: an error
  message goes to stderr and the auto-approve policy is applied instead.
  A handler must not assume it can crash the agent turn.
- Reference mapping (ACP): `acp_server/agent.py::_make_permission_handler`
  maps the ACP `session/request_permission` outcome, option id `'allow'`
  to `True`, `'allow_always'` to the string `'always'`, anything else to
  `False`.

---

## 6. Policy fallback: auto-approve

```python
io_backend.set_auto_approve(flag: bool)
```

- Sets the fallback policy used whenever no permission handler is available
  (or the handler raised). `set_mode(mode, auto_approve=...)` sets the same
  flag at initialization time.
- `auto_approve=True` means tools run **without asking**: no prompt is shown
  to any user and permission requests are silently approved.

Behavior per function when falling back:

| Function                | No handler / handler error -> returns      |
|-------------------------|--------------------------------------------|
| `confirm`               | `_auto_approve` (`True`/`False`)           |
| `confirm_with_always`   | `ALLOW` if `_auto_approve` else `REJECT`   |

`ask` never consults the handler or the policy; it simply returns `default`
in headless modes.

---

## 7. Other getters

| Function          | Returns                                                        |
|-------------------|----------------------------------------------------------------|
| `get_mode()`      | Current mode string (`MODE_TERMINAL` or `MODE_ACP`)            |
| `is_headless()`   | `True` when `mode != MODE_TERMINAL`                            |
| `get_debug()`     | Current debug flag (set via `set_debug`)                       |
| `set_debug(flag)` | Sets the process-wide debug flag                               |

Use `is_headless()` in your frontend code to decide how to render things
(e.g. suppress terminal-only decorations); agent code uses it internally to
decide whether stdin may be touched.

---

## 8. Building a custom frontend: step-by-step recipe

This recipe wires a full non-terminal frontend (GUI, web, embedded, etc.).
A complete minimal example follows.

### Step 1, Initialize io_backend before creating the Agent

```python
import io_backend

io_backend.set_mode(io_backend.MODE_ACP, auto_approve=False)
io_backend.set_debug(debug_flag)
```

Use `MODE_ACP` (the headless mode) for any non-terminal frontend; `auto_approve=False` keeps permission prompts flowing to your UI.

### Step 2, Build and run the agent

Follow `raggie.py::_build_agent`: construct `Agent`, then attach tools and
commands:

```python
from Agent.agent import Agent
from Tools import setup_toolcalls      # tool registration
from Commands import setup_commands    # command registration

agent = Agent(role, chat_id=chat_id, debug=debug_flag)
setup_toolcalls(agent.tool_registry)
setup_commands(agent.command_registry)
```

### Step 3, Install a permission handler on each request thread

If your frontend handles each user request on its own thread (recommended),
install the handler inside that thread's run function with the try/finally
pattern (section 5). The example below maps the handler to a simple GUI
dialog:

```python
def handle_request(agent, user_input):
    def handler(title, detail, allow_always=False):
        # Show a dialog in your UI. Return:
        #   True/False for confirm()
        #   True, False, or 'always' for confirm_with_always()
        return my_gui_dialog.ask(title, detail, show_always=allow_always)

    io_backend.set_permission_handler(handler)
    try:
        agent.run(user_input)   # or your equivalent entry point
    finally:
        io_backend.clear_permission_handler()
```

### Step 4, Render agent output from get_console()

Point your UI at the shared console's output. The console writes to stderr
in headless modes, so capture stderr and render the rich markup, or wrap
`get_console()` with a `rich` file object backed by your UI's text widget.

### Complete minimal example

```python
import sys
import threading

import io_backend


def main():
    # 1. Initialize io_backend BEFORE creating the Agent
    #    (reference: acp_server.run_stdio / raggie.main)
    io_backend.set_mode(io_backend.MODE_ACP, auto_approve=False)
    io_backend.set_debug(False)

    # 2. Capture protocol streams BEFORE any stdout redirection.
    #    In a stdio-based frontend, bind the raw stdin/stdout first
    #    (reference: acp_server.run_stdio, which calls stdio_streams()
    #    before `sys.stdout = sys.stderr`), then reroute agent console
    #    output (stderr) to your UI.
    protocol_in, protocol_out = sys.stdin, sys.stdout  # your transport

    # 3. Build the agent like raggie._build_agent
    from Agent.agent import Agent
    from Tools import setup_toolcalls
    from Commands import setup_commands

    agent = Agent("code", chat_id=None, debug=False)
    setup_toolcalls(agent.tool_registry)
    setup_commands(agent.command_registry)

    # 4. Per-request worker thread: install a permission handler that
    #    maps io_backend prompts to your UI.
    def worker(user_input):
        def handler(title, detail, allow_always=False):
            # Replace with your GUI/web dialog.
            print(f"[permission] {title}\n  {detail}", file=sys.stderr)
            answer = input("allow? [y/n/a]: ").strip().lower()
            if not allow_always:
                return answer == "y"
            if answer == "a":
                return "always"
            return answer == "y"

        io_backend.set_permission_handler(handler)
        try:
            agent.run(user_input)
        finally:
            io_backend.clear_permission_handler()

    # 5. Render agent output: in headless mode get_console() writes to
    #    stderr; route it into your UI instead of the terminal.
    console = io_backend.get_console()
    console.print("[green]frontend ready[/green]")

    while True:
        user_input = protocol_in.readline()
        if not user_input:
            break
        t = threading.Thread(target=worker, args=(user_input.strip(),))
        t.start()
        t.join()


if __name__ == "__main__":
    main()
```

### ACP stdio note

If your frontend speaks a protocol over stdio (as the ACP server does),
capture the protocol streams **before** redirecting stdout to stderr.
`src/acp_server/__init__.py::run_stdio` is the reference: it binds the
stdio protocol streams first (the underlying library captures
`sys.stdout` at call time) and only afterwards sets
`sys.stdout = sys.stderr` so that agent console output cannot corrupt the
protocol channel. If you redirect stdout first, the protocol stream is
lost.

---

## 9. Stability guarantees and versioning

### Guaranteed stable (public API)

- Function names and signatures:
  `set_mode(mode, *, auto_approve=False)`, `set_debug(flag)`,
  `get_console()`, `ask(message, default="")`, `confirm(title, detail="")`,
  `confirm_with_always(title, detail="")`,
  `set_permission_handler(handler)`, `clear_permission_handler()`,
  `set_ask_handler(handler)`, `clear_ask_handler()`,
  `set_auto_approve(flag)`, `get_mode()`, `is_headless()`, `get_debug()`.
- Return constants: `MODE_TERMINAL`, `MODE_ACP`, `ALLOW` (`'yes'`),
  `REJECT` (`'no'`), `ALLOW_ALWAYS` (`'always'`), and the string `'always'`
  as a valid handler return value.
- The permission handler contract (section 5), including ANSI-stripped
  plain-text arguments and the exception-to-policy-fallback behavior.
- The initialization contract: `set_mode` before agent creation;
  `get_console()` writes to stderr in headless modes; `ask` never touches
  stdin in headless modes.

### NOT stable (module-private)

Anything prefixed with an underscore is an implementation detail and may
change at any time. Frontends must never use:

- `_flush_stdin()` (terminal stdin hygiene)
- `_ANSI_RE` (the ANSI-stripping regex)
- `_local` (the thread-local storage holding the permission handler)
- `_console`, `_mode`, `_auto_approve`, `_debug` (module globals, use the
  public getters/setters)

If you find you need something from this private list, open an issue
proposing a public API instead of reaching into internals.

---

## 10. Testing guidance

To test agent behavior in headless mode without a real frontend:

```python
import io_backend

def setup_headless(auto_approve=False):
    io_backend.set_mode(io_backend.MODE_ACP, auto_approve=auto_approve)

    def handler(title, detail, allow_always=False):
        # Your scripted answers, e.g.:
        # return "always" to test the ALLOW_ALWAYS path
        return True

    io_backend.set_permission_handler(handler)
```

Key points:

- `set_mode(io_backend.MODE_ACP, auto_approve=...)` makes the module
  headless: prompts route through the handler or the auto-approve policy,
  no terminal, no stdin access. `ask()` follows the same pattern via the
  thread-local ask handler, returning `default` when no handler answers.
- `set_permission_handler` and `set_ask_handler` are thread-local: install
  them on the **same thread that runs the agent**. If your test runs the
  agent on the main thread, setting the handler there is enough; if you use
  worker threads, install the handler inside each worker.
- `auto_approve=True` is the simplest way to run unattended tests: no
  handler is needed and all permission requests are approved.
- Call `io_backend.clear_permission_handler()` in test teardown to avoid
  leaking handlers between tests that share a thread.
- Remember `set_mode` resets the shared console; call `get_console()` after
  changing modes if your test asserts on console output.
