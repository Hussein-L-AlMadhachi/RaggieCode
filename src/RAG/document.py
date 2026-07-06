from pathlib import Path

from indexing.code_index_sdk import CodeIndexSDK


def get_symbol_description(symbol_name: str, symbol_type: str = "function", file_path: str = None) -> str:
    """Get the description of a symbol from the code index database.
    
    Args:
        symbol_name: Name of the symbol to query
        symbol_type: Type of symbol ("function", "method", "class", or "variable")
        file_path: Optional file path to disambiguate same-name symbols
    
    Returns:
        Description string or error message
    """
    db_path = Path.cwd() / ".raggie" / ".code_index.raggie"
    
    if not db_path.exists():
        return f"Error: Code index database not found at {db_path}"

    with CodeIndexSDK(str(db_path)) as sdk:
        description = sdk.get_symbol_description_by_name(symbol_type, symbol_name, file_path)
        
        if description is None:
            return f"No description found for {symbol_type} '{symbol_name}'" + (f" in '{file_path}'" if file_path else "")
        
        return description


def update_symbol_description(symbol_name: str, description: str, symbol_type: str = "function", file_path: str = None) -> str:
    """Update the description of a symbol in the code index database.
    
    Args:
        symbol_name: Name of the symbol to update
        description: The description to set
        symbol_type: Type of symbol ("function", "method", "class", or "variable")
        file_path: Optional file path to disambiguate same-name symbols
    
    Returns:
        Success message or error message
    """
    db_path = Path.cwd() / ".raggie" / ".code_index.raggie"
    
    if not db_path.exists():
        return f"Error: Code index database not found at {db_path}"

    with CodeIndexSDK(str(db_path)) as sdk:
        if symbol_type in ("function", "method"):
            matches = sdk.get_function_by_name(symbol_name)
            if not matches:
                return f"Error: {symbol_type.capitalize()} '{symbol_name}' not found in code index."
            
            # Filter by type if method
            if symbol_type == "method":
                matches = [f for f in matches if f.type == "method"]
                if not matches:
                    return f"Error: Method '{symbol_name}' not found in code index."
            
            # If file_path provided, filter by file
            if file_path:
                matches = [f for f in matches if f.file_path == file_path]
                if not matches:
                    return f"Error: {symbol_type.capitalize()} '{symbol_name}' not found in file '{file_path}'."
            
            func = matches[0]
            cursor = sdk.conn.cursor()
            cursor.execute(
                "UPDATE functions SET description = ? WHERE id = ?",
                (description, func.id)
            )
            sdk.conn.commit()
            
            return f"Successfully updated description for {symbol_type} '{symbol_name}' in '{func.file_path}'"
        
        elif symbol_type == "class":
            matches = sdk.get_class_by_name(symbol_name)
            if not matches:
                return f"Error: Class '{symbol_name}' not found in code index."
            
            # If file_path provided, filter by file
            if file_path:
                matches = [c for c in matches if c.file_path == file_path]
                if not matches:
                    return f"Error: Class '{symbol_name}' not found in file '{file_path}'."
            
            cls = matches[0]
            cursor = sdk.conn.cursor()
            cursor.execute(
                "UPDATE classes SET description = ? WHERE id = ?",
                (description, cls.id)
            )
            sdk.conn.commit()
            
            return f"Successfully updated description for class '{symbol_name}' in '{cls.file_path}'"
        
        elif symbol_type == "variable":
            matches = sdk.get_variable_by_name(symbol_name)
            if not matches:
                return f"Error: Variable '{symbol_name}' not found in code index."
            
            # If file_path provided, filter by file
            if file_path:
                matches = [v for v in matches if v.file_path == file_path]
                if not matches:
                    return f"Error: Variable '{symbol_name}' not found in file '{file_path}'."
            
            var = matches[0]
            cursor = sdk.conn.cursor()
            cursor.execute(
                "UPDATE variables SET description = ? WHERE id = ?",
                (description, var.id)
            )
            sdk.conn.commit()
            
            return f"Successfully updated description for variable '{symbol_name}' in '{var.file_path}'"
        
        else:
            return f"Error: Invalid symbol_type '{symbol_type}'. Must be 'function', 'method', 'class', or 'variable'."
