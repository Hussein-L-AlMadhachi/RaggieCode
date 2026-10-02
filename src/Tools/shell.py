import os
import re
import signal
import subprocess
import time

import io_backend
from .utils import YELLOW, is_ignored_by_gitignore, is_within_cwd, denial_content, BLUE, GREEN, RESET, reindex_after_change


def _looks_like_path(token):
    """Heuristic: does this token plausibly reference a filesystem path?

    Matches tokens containing a path separator, hidden files (.env), or a
    file extension (config.json). Bare words (echo, build, HEAD~1) are not
    treated as paths so plain command words never trigger the sandbox.
    """
    if "/" in token or "\\" in token or token.startswith("."):
        return True
    return re.search(r"\.[A-Za-z0-9]{1,5}$", token) is not None


# Standard device files that are safe to touch in any project and must never
# be treated as project paths by the path sandbox (e.g. `cmd > /dev/null`).
_SAFE_DEVICE_PATHS = frozenset({
    "/dev/null",
    "/dev/stdin",
    "/dev/stdout",
    "/dev/stderr",
})


def _extract_paths(command):
    """Extract potential file paths from a shell command string.

    Uses a simple heuristic: find tokens that look like paths (contain '/'
    or a known extension) and resolve them relative to cwd. This catches
    common cases like 'cat .env', 'sed -i file', 'rm -rf dir/', etc.
    Path-like tokens are returned even when they do not exist on disk, so
    the sandbox can deny commands touching gitignored paths (e.g.
    '.venv/bin/pytest' in a fresh worktree).
    """
    paths = set()
    cwd = os.getcwd()

    # Split on whitespace and common shell operators
    tokens = re.split(r'[\s;|&<>`$()]+', command)
    for token in tokens:
        token = token.strip().strip("'\"")
        if not token or len(token) < 2:
            continue
        # /dev/null and the standard streams are device files, not project
        # paths   never let them trigger the cwd/gitignore sandbox checks.
        if token in _SAFE_DEVICE_PATHS:
            continue
        # Skip flags and options
        if token.startswith('-'):
            continue
        if not _looks_like_path(token):
            continue
        # Resolve relative to cwd; non-existent paths resolve to the
        # cwd-relative candidate so cwd/ignore checks still apply.
        candidate = os.path.join(cwd, token)
        if os.path.lexists(candidate):
            paths.add(os.path.normpath(candidate))
        elif os.path.lexists(token):
            paths.add(os.path.normpath(token))
        else:
            paths.add(os.path.normpath(candidate))

    return paths


# Commands that only observe and print to stdout without mutating on their
# own. Output redirection into a real file is rejected separately by the
# generic `file_redirect` guard in `_is_read_only_command`, so `echo` is safe
# to auto-approve here: plain `echo hello` prints, while `echo hello > file`
# and `echo hello >> file` still fall through to the permission prompt.
_OBSERVATION_COMMANDS = {"head", "tail", "cat", "grep", "rg", "egrep", "fgrep", "ls", "wc", "echo"}

# find operators that can mutate the filesystem or run other commands.
_FIND_MUTATING_OPS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls", "-fprint", "-fprint0", "-fprintf"}

# sed script commands that execute shell (e) or write files (w). Matches an
# 'e'/'w' in command position: start of script or after a boundary such as
# an address digit, $, /, ;, {, }, !, or a quote.
_SED_SCRIPT_DANGER = re.compile(r"(^|[;{}\d$,!/!'\"])\s*[ew](\s|$)")

# Named tree-sitter-bash node types that can appear in an observation-only
# snippet. Anything outside this set (control flow, subshells, command
# substitution, process substitution, functions, ...) forces approval.
_SAFE_BASH_NODES = frozenset({
    "program", "list", "pipeline", "comment",
    "command", "command_name", "word", "number",
    "string", "string_content", "raw_string", "concatenation",
    "redirected_statement", "file_descriptor",
    "variable_assignment", "variable_name",
    "simple_expansion", "expansion", "ansi_c_string",
    "heredoc_redirect", "heredoc_start", "heredoc_body", "heredoc_end",
})

_bash_parser = None


def _get_bash_parser():
    global _bash_parser
    if _bash_parser is None:
        from tree_sitter import Parser
        from tree_sitter_language_pack import get_language
        _bash_parser = Parser(get_language("bash"))
    return _bash_parser


def _file_redirect_is_safe(redirect_text):
    """True for input redirects, fd duplication, and /dev/null sinks only.

    Watch out: bash treats `>&file` as "write stdout+stderr to file" (NOT an
    fd dup), and `<>file` opens read-write   both mutate, both rejected here.
    """
    t = redirect_text.strip()
    m = re.match(r"^(\d+)?(>>?|<<?)", t)
    if not m:
        return False
    op = m.group(2)
    rest = t[m.end():].strip().strip("\"'")
    if "<" in op and ">" in op:
        return False
    if "<" in op:
        if rest.startswith(">"):
            return False
        return True
    # Output redirect: only fd duplication (`>&2`, `2>&1`, `>&-`) or /dev/null.
    if re.fullmatch(r"&\d+&?|&-", rest):
        return True
    return rest == "/dev/null"


def _sed_read_only(args):
    """True when sed only filters to stdout: -n required, short flags only
    (no -i/--in-place, no -f script files), and no e/w script commands."""
    has_n = False
    script_handled = False
    i = 0
    while i < len(args):
        token = args[i]
        i += 1
        if token.startswith("--"):
            return False
        if token.startswith("-") and token != "-":
            letters = token[1:]
            if any(c not in "nerE" for c in letters):
                return False
            if "n" in letters:
                has_n = True
            # A cluster ending in 'e' consumes the next token as the script.
            if letters.endswith("e"):
                if i >= len(args) or _SED_SCRIPT_DANGER.search(args[i]):
                    return False
                script_handled = True
                i += 1
            continue
        if not script_handled:
            if _SED_SCRIPT_DANGER.search(token):
                return False
            script_handled = True
    return has_n


def _command_parts(command_node):
    """Extract (name, arg texts) from a tree-sitter `command` node,
    skipping leading env assignments and any redirects."""
    name = None
    args = []
    for child in command_node.children:
        ctype = child.type
        if ctype in ("variable_assignment", "file_redirect", "heredoc_redirect"):
            continue
        if ctype == "command_name":
            if name is None:
                name = child.text.decode().strip("'\"")
            continue
        if name is not None:
            args.append(child.text.decode().strip("'\""))
    return name, args


def _observation_command_ok(name, args):
    if name in _OBSERVATION_COMMANDS:
        return True
    if name == "find":
        return not any(t in _FIND_MUTATING_OPS for t in args)
    if name == "sed":
        return _sed_read_only(args)
    return False


def _is_read_only_command(command):
    """True when the command parses cleanly as bash and every statement is
    observation-only.

    Fails closed: parse errors, unknown node types, command subshells/
    substitutions, file-less? mutations, or any non-whitelisted command all
    require user approval.
    """
    try:
        tree = _get_bash_parser().parse(command.encode("utf-8", errors="replace"))
    except Exception:
        return False
    root = tree.root_node
    if root.type != "program" or root.has_error:
        return False

    command_nodes = []
    stack = [root]
    while stack:
        node = stack.pop()
        ntype = node.type
        if ntype == "command":
            command_nodes.append(node)
        elif ntype == "file_redirect":
            if not _file_redirect_is_safe(node.text.decode()):
                return False
        elif node.is_named and ntype not in _SAFE_BASH_NODES:
            return False
        stack.extend(node.children)

    if not command_nodes:
        return False
    for cmd_node in command_nodes:
        name, args = _command_parts(cmd_node)
        if name is None or not _observation_command_ok(name, args):
            return False
    return True


def _command_statements_approved(command, session_id):
    """True when every statement of the command is individually auto-approved.

    Statements are split with the tree-sitter bash parser (|, ;, &&, ||, &
    and subshells), then each one is checked. A statement passes when it is
    observation-only (read-only rules) or whitelisted for the session's
    role, so combinations like `python3 script.py | grep 25` run without a
    prompt once `python3 script.py` is whitelisted. Any statement that
    satisfies neither forces a prompt.
    """
    from Agent.chat_history_db import get_session_role, is_command_whitelisted
    statements = _extract_command_statements(command)
    if not statements:
        return False
    role = get_session_role(session_id) if session_id is not None else None
    for stmt in statements:
        if _is_read_only_command(stmt):
            continue
        if role and is_command_whitelisted(role, stmt):
            continue
        return False
    return True


def _extract_command_statements(command):
    """Parse a shell command and return the text of each individual statement.

    Uses the tree-sitter bash parser to split compound commands (pipelines,
    lists joined by ;, &&, ||) into their constituent command nodes. A
    `redirected_statement` (e.g. `echo hi > out.txt`) is kept whole so its
    redirect is never silently dropped when deciding auto-approval. Returns a
    list of stripped command strings. On parse failure, returns the original
    command as a single-element list as a fallback.
    """
    try:
        tree = _get_bash_parser().parse(command.encode("utf-8", errors="replace"))
    except Exception:
        return [command.strip()] if command.strip() else []

    root = tree.root_node
    if root.type != "program" or root.has_error:
        return [command.strip()] if command.strip() else []

    statements = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in ("command", "redirected_statement"):
            text = node.text.decode().strip()
            if text:
                statements.append(text)
            continue
        stack.extend(node.children)

    return statements if statements else ([command.strip()] if command.strip() else [])


def _whitelist_command_statements(command, session_id):
    """Parse a command into individual statements and whitelist each for the role."""
    from Agent.chat_history_db import get_session_role, add_to_command_whitelist
    role = get_session_role(session_id)
    if not role:
        return
    for stmt in _extract_command_statements(command):
        add_to_command_whitelist(role, stmt)


def _kill_process_tree(process):
    """SIGTERM the process group, escalate to SIGKILL after a short grace.

    Falls back to process.terminate()/kill() when the process group lookup
    fails (or on platforms without killpg). Never raises on a dead process.
    """
    if os.name == "posix":
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            try:
                process.terminate()
            except OSError:
                pass
    else:
        try:
            process.terminate()
        except OSError:
            pass

    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                process.kill()
        else:
            process.kill()


def handle(arguments, toolcall_id, session_id=None, code_indexer=None, cancel_check=None):

    command = arguments["command"]
    timeout = arguments.get("timeout", 30)
    print(f"{BLUE}Shell{RESET}")

    # Enforce sandbox: deny commands that touch paths outside cwd.
    # Approval happens only through the normal shell command confirmation.
    for path in _extract_paths(command):
        if not is_within_cwd(path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": denial_content(
                    f"Error: The command would operate on '{path}', "
                    "which is outside the current working directory. "
                    "Access to paths outside the project is not allowed."
                ),
            }

    # Enforce gitignore: deny commands that touch gitignored files.
    for path in _extract_paths(command):
        if is_ignored_by_gitignore(path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": denial_content(
                    f"Error: The command would operate on '{path}', "
                    "which is matched by .gitignore. Access to gitignored "
                    "paths is not allowed. Use the dedicated "
                    "tools (WriteFile, ReplaceText, RemoveFile) for "
                    "non-gitignored files, or instruct the user to make "
                    "this change themselves."
                ),
            }

    try:
        if _is_read_only_command(command):
            print(f"{BLUE}[shell] read-only command [auto-approved]{RESET}")
        elif session_id is not None and _command_statements_approved(command, session_id):
            print(f"{BLUE}[shell] all statements approved [auto-approved]{RESET}")
        else:
            choice = io_backend.confirm_with_always(
                f"{YELLOW}Do you want to allow the agent to run:",
                f"{GREEN}{command}{RESET}",
            )
            if choice == io_backend.REJECT:
                print("Command execution cancelled by user.")
                reason = io_backend.ask(
                    f"{BLUE}Reason for refusal (optional, press Enter to skip): {RESET}"
                ).strip()
                if reason:
                    return {
                        "role": "tool",
                        "tool_call_id": toolcall_id,
                        "content": f"The user refused running this command. Reason: {reason}",
                    }
                return {
                    "role": "tool",
                    "tool_call_id": toolcall_id,
                    "content": "The user refused running this command.",
                }
            if choice == io_backend.ALLOW_ALWAYS and session_id is not None:
                _whitelist_command_statements(command, session_id)
                print(f"{BLUE}[shell] command statements added to whitelist{RESET}")
                print(f"{BLUE}[shell] tip: review them anytime with /whitelist{RESET}")

        # Run under Popen with a short poll tick so cooperative cancellation
        # (cancel_check) can take effect mid-run instead of waiting out the
        # whole command. Partial output is preserved across communicate()
        # retries by the subprocess module itself.
        popen_kwargs = {
            "shell": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if os.name == "posix":
            # Always own the process group: killpg must NEVER be able to
            # reach the agent's own group (it would terminate the CLI/server
            # itself, e.g. from the tool-timeout path). Terminal Ctrl+C is
            # handled below by killing the child explicitly on
            # KeyboardInterrupt instead of relying on signal propagation.
            popen_kwargs["start_new_session"] = True

        process = subprocess.Popen(command, **popen_kwargs)

        cancelled = False
        timed_out = False
        deadline = None if timeout is None else time.monotonic() + timeout
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.25)
                    break
                except subprocess.TimeoutExpired as e:
                    if cancel_check is not None and cancel_check():
                        cancelled = True
                        break
                    if deadline is not None and time.monotonic() >= deadline:
                        timed_out = True
                        e_stdout = e.stdout or ""
                        e_stderr = e.stderr or ""
                        break
        except KeyboardInterrupt:
            # Terminal Ctrl+C: the child is in its own process group, so
            # take it down explicitly before propagating the interrupt.
            _kill_process_tree(process)
            raise
        if cancelled or timed_out:
            _kill_process_tree(process)
            # Reap; returns the full output captured up to the kill.
            stdout, stderr = process.communicate()

        if cancelled:
            msg = "Command cancelled by the user (process terminated)."
            partial_stdout = (stdout or "").strip()
            partial_stderr = (stderr or "").strip()
            if partial_stdout:
                msg += f"\nPartial stdout:\n{partial_stdout}"
            if partial_stderr:
                msg += f"\nPartial stderr:\n{partial_stderr}"
            print(msg)
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "exit_code": None,
                "content": msg,
            }

        if timed_out:
            output = e_stdout.strip()
            error_msg = e_stderr.strip()
            msg = f"Command timed out after {timeout} seconds and was killed."
            if output:
                msg += f"\nPartial stdout:\n{output}"
            if error_msg:
                msg += f"\nPartial stderr:\n{error_msg}"
            print(msg)
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "exit_code": None,
                "content": msg,
            }

        output = stdout
        if process.returncode != 0:
            error_msg = stderr.strip()
            if output:
                output += f"\n(exit code {process.returncode})\nstderr: {error_msg}"
            else:
                output = f"Command failed with exit code {process.returncode}\n{error_msg}"

        stripped = output.strip()
        if stripped:
            print(stripped)

        reindex_after_change(code_indexer)

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "exit_code": process.returncode,
            "content": f"{output.strip()}",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "exit_code": None,
            "content": f"Error executing command: {str(e)}",
        }
