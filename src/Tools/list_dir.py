from pathlib import Path
from .utils import BLUE, RESET


def _list_directory(path: Path, depth: int, current_depth: int, indent: str, items: list):
    for item in sorted(path.iterdir()):
        item_type = "DIR" if item.is_dir() else "FILE"
        size = item.stat().st_size if item.is_file() else 0
        items.append(f"{indent}{item_type}: {item.name} ({size} bytes)")
        if item.is_dir() and current_depth < depth:
            _list_directory(item, depth, current_depth + 1, indent + "  ", items)


def handle(arguments, toolcall_id):
    directory_path = arguments["directory_path"]
    depth = arguments.get("depth", 1)
    print(f"{BLUE}Listing directory {directory_path} (depth={depth}){RESET}")

    try:
        path = Path(directory_path)
        
        if not path.exists():
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "Directory not found",
            }
        
        if not path.is_dir():
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "Path is not a directory",
            }

        items = []
        _list_directory(path, depth, 1, "", items)
        
        result = f"Directory contents ({len(items)} items):\n" + "\n".join(items)
        
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": result,
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error listing directory: {str(e)}",
        }
