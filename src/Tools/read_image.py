import base64
from pathlib import Path
from .utils import is_ignored_by_gitignore, is_within_cwd, BLUE, RESET

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.tiff', '.ico', '.heic', '.heif'}

def handle(arguments, toolcall_id):
    file_path = arguments["file_path"]
    print(f"{BLUE}Reading image {file_path}{RESET}")

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

        path = Path(file_path)
        
        # Check if it's an image file
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Error: {path.suffix} is not a supported image format. Supported formats: {', '.join(IMAGE_EXTENSIONS)}",
            }

        # Read and encode image
        with open(file_path, "rb") as f:
            image_data = f.read()
        
        base64_data = base64.b64encode(image_data).decode('utf-8')
        mime_type = f"image/{path.suffix.lstrip('.').lower()}"
        
        # Return in format compatible with vision APIs
        result = {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Image read successfully. Format: {mime_type}, Size: {len(image_data)} bytes",
            "image_data": {
                "mime_type": mime_type,
                "base64_data": base64_data
            }
        }
        
        return result
        
    except FileNotFoundError:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "File not found",
        }
    except IsADirectoryError:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Path is a directory, not an image file",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error reading image: {str(e)}",
        }
