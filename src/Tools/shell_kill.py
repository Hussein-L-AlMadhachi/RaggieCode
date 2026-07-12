import os

from .utils import BLUE, RED, RESET
from .temp_background_service import _background_processes


def handle(arguments, toolcall_id):
    pid = arguments.get("pid")
    print(f"{BLUE}ShellKill{RESET}")

    if pid is None:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'pid' parameter is required.",
        }

    pid = int(pid)

    if pid not in _background_processes:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error: No background process found with PID {pid}.",
        }

    entry = _background_processes[pid]
    process = entry["process"]
    command = entry["command"]

    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            process.kill()
            process.wait(timeout=5)

        # Read any captured output
        output = ""
        stdout_path = entry.get("stdout_path")
        stderr_path = entry.get("stderr_path")

        if stdout_path and os.path.exists(stdout_path):
            with open(stdout_path, "r") as f:
                stdout_content = f.read().strip()
            if stdout_content:
                output += stdout_content

        if stderr_path and os.path.exists(stderr_path):
            with open(stderr_path, "r") as f:
                stderr_content = f.read().strip()
            if stderr_content:
                if output:
                    output += f"\nstderr: {stderr_content}"
                else:
                    output = f"stderr: {stderr_content}"

        # Clean up temp files
        for path in [stdout_path, stderr_path]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError as e:
                    print(f"{RED}Warning: Failed to clean up temp file {path}: {e}{RESET}")

        del _background_processes[pid]

        return_code = process.returncode
        result = (
            f"Process {pid} terminated (exit code {return_code}).\n"
            f"Command: {command}"
        )
        if output:
            result += f"\nOutput:\n{output}"

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": result,
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error killing process {pid}: {str(e)}",
        }
