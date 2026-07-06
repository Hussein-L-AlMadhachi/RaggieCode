import os
import shutil
from pathlib import Path

from .utils import is_ignored_by_gitignore, is_within_cwd, BLUE, RESET, auto_record_change, reindex_after_change


def handle(arguments, toolcall_id, session_id=None, code_indexer=None):
    file_path = arguments.get("file_path")
    print(f"{BLUE}Remove {file_path}{RESET}")

    try:
        # Check if the file is outside the current working directory
        if not is_within_cwd(file_path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "Error: access denied - path is outside the current working directory",
            }

        target = Path(file_path).resolve()

        # Check if the path exists
        if not target.exists():
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Error: '{file_path}' does not exist.",
            }

        # Refuse to remove anything that is gitignored
        if is_ignored_by_gitignore(str(target)):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "cannot remove sensitive information. DO NOT TRY TO REMOVE this using shell toolcalls either, instead instruct the user to make the changes themselves.",
            }

        if target.is_dir():
            shutil.rmtree(target)
            if session_id is not None:
                from Agent.chat_history_db import record_session_file
                record_session_file(session_id, file_path, "remove")
                auto_record_change(session_id, file_path, "file_delete", f"Removed directory {file_path}")
            reindex_after_change(code_indexer)
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Successfully removed directory '{file_path}'",
            }
        else:
            os.remove(target)
            if session_id is not None:
                from Agent.chat_history_db import record_session_file
                record_session_file(session_id, file_path, "remove")
                auto_record_change(session_id, file_path, "file_delete", f"Removed file {file_path}")
            reindex_after_change(code_indexer)
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Successfully removed file '{file_path}'",
            }

    except PermissionError:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error: Permission denied when trying to remove '{file_path}'",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error removing '{file_path}': {str(e)}",
        }
