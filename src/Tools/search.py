from ripgrep_rs import search
from .utils import is_within_cwd

def handle(arguments, toolcall_id, parent_session_id=None):
    search_term = arguments.get("search_term")
    directory = arguments.get("directory")

    # Check if the directory is outside the current working directory
    if directory and not is_within_cwd(directory):
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: access denied - path is outside the current working directory",
        }
    
    print(f"Searching for '{search_term}' in '{directory}'")
    
    try:
        results = search(
            patterns=[search_term],
            paths=[directory]
        )
        
        # ripgrep_rs returns a list of strings
        if not results:
            result = "No matches found."
        else:
            result = "".join(results)
            
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": result.strip(),
        }
    except Exception as e:
        print(f"Search error: {str(e)}")
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error executing search: {str(e)}",
        }
