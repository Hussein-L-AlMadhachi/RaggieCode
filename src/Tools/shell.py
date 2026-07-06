import os
import re
import subprocess
from pathlib import Path

from .utils import is_ignored_by_gitignore, is_within_cwd, BLUE, RESET, reindex_after_change


def _extract_paths(command):
    """Extract potential file paths from a shell command string.

    Uses a simple heuristic: find tokens that look like paths (contain '/'
    or a known extension) and resolve them relative to cwd. This catches
    common cases like 'cat .env', 'sed -i file', 'rm -rf dir/', etc.
    """
    paths = set()
    cwd = os.getcwd()

    # Split on whitespace and common shell operators
    tokens = re.split(r'[\s;|&<>`$()]+', command)
    for token in tokens:
        token = token.strip().strip("'\"")
        if not token or len(token) < 2:
            continue
        # Skip flags and options
        if token.startswith('-'):
            continue
        # Resolve relative to cwd
        candidate = os.path.join(cwd, token)
        if os.path.lexists(candidate):
            paths.add(os.path.normpath(candidate))
        elif os.path.lexists(token):
            paths.add(os.path.normpath(token))

    return paths


def handle(arguments, toolcall_id, code_indexer=None):

    command = arguments["command"]
    timeout = arguments.get("timeout", 30)
    print(f"{BLUE}Shell{RESET}")

    # Enforce sandbox: block commands that touch paths outside cwd
    for path in _extract_paths(command):
        if not is_within_cwd(path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": (
                    f"Error: The command would operate on '{path}', "
                    "which is outside the current working directory. "
                    "Access to paths outside the project is not allowed."
                ),
            }

    # Enforce gitignore: block commands that touch gitignored files
    for path in _extract_paths(command):
        if is_ignored_by_gitignore(path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": (
                    f"Error: The command would operate on '{path}', "
                    "which is matched by .gitignore. Use the dedicated "
                    "tools (WriteFile, ReplaceText, RemoveFile) for "
                    "non-gitignored files, or instruct the user to make "
                    "this change themselves."
                ),
            }

    try:
        confirmation = ""
        try:
            confirmation = input(f"{BLUE}Execute command: {command}\n? (y/n): {RESET}")
        except KeyboardInterrupt:
            print()
            exit(0)
        except EOFError:
            print()
            exit(0)

        if confirmation.lower() != "y":
            print("Command execution cancelled by user.")
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "The user refused running this command.",
            }

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            output = (e.stdout or "").strip()
            error_msg = (e.stderr or "").strip()
            msg = f"Command timed out after {timeout} seconds and was killed."
            if output:
                msg += f"\nPartial stdout:\n{output}"
            if error_msg:
                msg += f"\nPartial stderr:\n{error_msg}"
            print(msg)
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": msg,
            }

        output = result.stdout
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            if output:
                output += f"\n(exit code {result.returncode})\nstderr: {error_msg}"
            else:
                output = f"Command failed with exit code {result.returncode}\n{error_msg}"

        stripped = output.strip()
        if stripped:
            print(stripped)

        reindex_after_change(code_indexer)

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"{output.strip()}",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error executing command: {str(e)}",
        }
