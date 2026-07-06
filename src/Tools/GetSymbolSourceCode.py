from pathlib import Path

from RAG.find import find_symbol_implementation
from .utils import is_within_cwd, BLUE, RESET


def handle(arguments, toolcall_id):
    symbol_name = arguments["symbol_name"]
    file_path = arguments.get("file_path")
    print(f"{BLUE}GetSymbolSourceCode {symbol_name}{RESET}")

    # Check if the file is outside the current working directory
    if file_path and not is_within_cwd(file_path):
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: access denied - path is outside the current working directory",
        }

    try:
        result = find_symbol_implementation(symbol_name, file_path)
    except Exception as e:
        result = f"Error finding symbol implementation: {str(e)}"
    
    return {
        "role": "tool",
        "tool_call_id": toolcall_id,
        "content": result,
    }
