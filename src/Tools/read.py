from pathlib import Path
import os

from .utils import is_ignored_by_gitignore, is_within_cwd, BLUE, RESET



def handle(arguments, toolcall_id):
    
    file_path = arguments["file_path"]
    print(f"{BLUE}Reading {file_path}{RESET}")

    try:
        # Check if the file is outside the current working directory
        if not is_within_cwd(file_path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "Error: access denied - path is outside the current working directory",
            }

        # Check if the file is gitignored
        if is_ignored_by_gitignore(file_path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "Error: file is gitignored",
            }

        with open(file_path, "r") as f:
            result = f.read()

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"{result}",
        }
    except FileNotFoundError:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "File not found",
        }
    except IsADirectoryError:
        dir_content = [item.name for item in Path(file_path).iterdir()]
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"directory contents: {', '.join(dir_content)}",
        }
