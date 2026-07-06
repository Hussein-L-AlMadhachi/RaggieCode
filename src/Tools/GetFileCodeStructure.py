from pathlib import Path

from RAG.graph import explore_code_structure
from .utils import is_within_cwd, BLUE, RESET


def handle(arguments, toolcall_id):
    file_path = arguments["file_path"]
    include_bodies = arguments.get("include_bodies", False)
    print(f"{BLUE}GetFileCodeSemantics {file_path}{RESET}")

    # Check if the file is outside the current working directory
    if not is_within_cwd(file_path):
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: access denied - path is outside the current working directory",
        }

    try:
        path = Path(file_path)
        if path.is_dir():
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines = [f"Contents of {file_path} ({len(entries)} items):"]
            for entry in entries:
                if entry.is_dir():
                    lines.append(f"  [DIR]  {entry.name}/")
                else:
                    lines.append(f"  [FILE] {entry.name}")
            result = "\n".join(lines)
        else:
            result = explore_code_structure(file_path, include_bodies=include_bodies)
    except Exception as e:
        result = f"Error exploring code structure: {str(e)}"

    return {
        "role": "tool",
        "tool_call_id": toolcall_id,
        "content": result,
    }
