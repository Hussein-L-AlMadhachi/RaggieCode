from pathlib import Path

from RAG.document import update_symbol_description, get_symbol_description
from .utils import is_within_cwd, BLUE, RESET


def handle(arguments, toolcall_id):
    action = arguments.get("action", "update")
    symbol_name = arguments["symbol_name"]
    print(f"{BLUE}Document {symbol_name}{RESET}")
    symbol_type = arguments.get("symbol_type", "function")
    file_path = arguments.get("file_path")

    # Check if the file is outside the current working directory
    if file_path and not is_within_cwd(file_path):
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: access denied - path is outside the current working directory",
        }

    try:
        if action == "read":
            result = get_symbol_description(symbol_name, symbol_type, file_path)
        elif action == "update":
            description = arguments["description"]
            result = update_symbol_description(symbol_name, description, symbol_type, file_path)
        else:
            result = f"Error: Unknown action '{action}'. Must be 'read' or 'update'."
    except Exception as e:
        result = f"Error: {str(e)}"
    
    return {
        "role": "tool",
        "tool_call_id": toolcall_id,
        "content": result,
    }
