import subprocess
import tempfile

import io_backend
from .utils import is_ignored_by_gitignore, is_within_cwd, denial_content, BLUE, RESET
from .shell import _extract_paths

# Module-level registry of background processes
_background_processes = {}


def handle(arguments, toolcall_id):
    command = arguments["command"]
    print(f"{BLUE}TempBackgroundService{RESET}")

    # Enforce sandbox: deny commands that touch paths outside cwd.
    # Approval happens only through the normal background service confirmation.
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
        if not io_backend.confirm(
            "Start background service:",
            f"{BLUE}{command}{RESET}",
        ):
            print("Command execution cancelled by user.")
            reason = io_backend.ask(f"{BLUE}Reason for refusal (optional, press Enter to skip): {RESET}").strip()
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

        # Create temp files for stdout and stderr
        stdout_file = tempfile.NamedTemporaryFile(
            mode="w+", delete=False, suffix=".out", prefix="raggie_bg_"
        )
        stderr_file = tempfile.NamedTemporaryFile(
            mode="w+", delete=False, suffix=".err", prefix="raggie_bg_"
        )

        process = subprocess.Popen(
            command,
            shell=True,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )

        pid = process.pid
        _background_processes[pid] = {
            "process": process,
            "command": command,
            "stdout_path": stdout_file.name,
            "stderr_path": stderr_file.name,
        }

        stdout_file.close()
        stderr_file.close()

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": (
                f"Background process started with PID {pid}.\n"
                f"Command: {command}\n"
                f"Use ShellKill with pid={pid} to terminate it."
            ),
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error starting background command: {str(e)}",
        }
