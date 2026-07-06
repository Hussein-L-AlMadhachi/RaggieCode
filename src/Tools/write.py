import os
from .utils import is_ignored_by_gitignore, is_within_cwd, BLUE, RESET, auto_record_change, reindex_after_change


def handle(arguments, toolcall_id, session_id=None, code_indexer=None):
    file_path = arguments["file_path"]
    content = arguments["content"]
    print(f"{BLUE}Writing {file_path}{RESET}")

    try:
        # Check if the file is outside the current working directory
        if not is_within_cwd(file_path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "Error: access denied - path is outside the current working directory",
            }

        # Check if file is in .gitignore
        if is_ignored_by_gitignore(file_path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Error: File '{file_path}' is in .gitignore. Operations on gitignored files are not allowed.",
            }

        with open(file_path, "w") as f:
            f.write(content)

        if session_id is not None:
            from Agent.chat_history_db import record_session_file
            record_session_file(session_id, file_path, "write")
            auto_record_change(session_id, file_path, "file_create", f"Created file {file_path}")

        reindex_after_change(code_indexer)

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"file {file_path} written successfully",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error writing file: {str(e)}",
        }
