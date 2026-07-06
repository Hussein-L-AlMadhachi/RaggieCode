from pathlib import Path

from RAG.graph import walk_call_tree
from .utils import is_within_cwd, BLUE, RESET


def handle(arguments, toolcall_id):
    symbol_name = arguments["symbol_name"]
    file_path = arguments.get("file_path")
    max_depth = arguments.get("max_depth", 5)
    include_external = arguments.get("include_external", False)
    exclude = arguments.get("exclude")
    print(f"{BLUE}WalkCallTree {symbol_name} (depth={max_depth}){RESET}")

    # Check if the file is outside the current working directory
    if file_path and not is_within_cwd(file_path):
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: access denied - path is outside the current working directory",
        }

    try:
        result = walk_call_tree(symbol_name, file_path, max_depth, include_external, exclude)
    except Exception as e:
        result = f"Error walking call tree: {str(e)}"

    return {
        "role": "tool",
        "tool_call_id": toolcall_id,
        "content": result,
    }
