from pathlib import Path

from indexing.code_index_sdk import CodeIndexSDK


def search_descriptions(query: str, symbol_types: list = None, limit: int = 50) -> str:
    """Search for symbols by description content.

    Args:
        query: Search query string
        symbol_types: Optional list of symbol types to search (e.g., ['function', 'class'])
        limit: Maximum number of results to return

    Returns:
        Formatted string with search results
    """
    db_path = Path.cwd() / ".raggie" / ".code_index.raggie"
    
    if not db_path.exists():
        return f"Error: Code index database not found at {db_path}"
    
    try:
        with CodeIndexSDK(str(db_path)) as sdk:
            results = sdk.search_descriptions(query, symbol_types, limit)
            
            if not results:
                return f"No symbols found with descriptions matching '{query}'"
            
            lines = [f"Found {len(results)} symbols with descriptions matching '{query}':"]
            for r in results:
                lines.append(f"  - {r['type']}: {r['name']} in {r['file_path']}")
                lines.append(f"    Description: {r['description']}")
            
            return "\n".join(lines)
    except Exception as e:
        return f"Error searching descriptions: {str(e)}"


def get_undocumented_symbols(symbol_types: list = None, file_path: str = None) -> str:
    """Get symbols that have no description.

    Args:
        symbol_types: Optional list of symbol types to check (e.g., ['function', 'class'])
        file_path: Optional file path to filter by file

    Returns:
        Formatted string with undocumented symbols
    """
    db_path = Path.cwd() / ".raggie" / ".code_index.raggie"
    
    if not db_path.exists():
        return f"Error: Code index database not found at {db_path}"
    
    try:
        with CodeIndexSDK(str(db_path)) as sdk:
            file_id = None
            if file_path:
                file = sdk.get_file_by_path(file_path)
                if file:
                    file_id = file.id
                else:
                    return f"Error: File not found in database: {file_path}"
            
            undocumented = sdk.get_undocumented_symbols(symbol_types, file_id)
            
            if not undocumented:
                return "All symbols have descriptions" + (f" in {file_path}" if file_path else "")
            
            lines = [f"Undocumented symbols" + (f" in {file_path}" if file_path else "") + ":"]
            for symbol_type, symbols in undocumented.items():
                lines.append(f"\n  {symbol_type}s ({len(symbols)}):")
                for s in symbols:
                    lines.append(f"    - {s['name']} in {s['file_path']}")
            
            return "\n".join(lines)
    except Exception as e:
        return f"Error getting undocumented symbols: {str(e)}"


def find_symbol_location(symbol_name: str, file_path: str = None):
    """Find the file path, line range, and current source of a symbol.

    Args:
        symbol_name: Name of the symbol to find
        file_path: Optional file path to disambiguate same-name symbols

    Returns:
        dict with keys: file_path, start_line, end_line, source, kind
        or None if not found
    """
    db_path = Path.cwd() / ".raggie" / ".code_index.raggie"

    if not db_path.exists():
        return None

    try:
        with CodeIndexSDK(str(db_path)) as sdk:
            file_id = None
            if file_path:
                f = sdk.get_file_by_path(file_path)
                if f:
                    file_id = f.id

            # Try function first
            funcs = sdk.get_function_by_name(symbol_name, file_id)
            if funcs:
                func = funcs[0]
                if len(funcs) > 1:
                    impls = [m for m in funcs if m.parent_type == 'class']
                    if impls:
                        func = impls[0]
                source = sdk._read_source_lines(func.file_id, func.location.start_line, func.location.end_line)
                if source is not None:
                    return {
                        "file_path": func.file_path,
                        "start_line": func.location.start_line,
                        "end_line": func.location.end_line,
                        "source": source,
                        "kind": "function",
                    }

            # Try class
            classes = sdk.get_class_by_name(symbol_name, file_id)
            if classes:
                cls = classes[0]
                source = sdk._read_source_lines(cls.file_id, cls.location.start_line, cls.location.end_line)
                if source is not None:
                    return {
                        "file_path": cls.file_path,
                        "start_line": cls.location.start_line,
                        "end_line": cls.location.end_line,
                        "source": source,
                        "kind": "class",
                    }

            return None
    except Exception:
        return None


def find_symbol_implementation(symbol_name: str, file_path: str = None) -> str:
    """Find and return the source implementation of a symbol (function or class).

    Args:
        symbol_name: Name of the symbol to find
        file_path: Optional file path to disambiguate same-name symbols

    Returns:
        Source code string of the symbol, or error message if not found
    """
    db_path = Path.cwd() / ".raggie" / ".code_index.raggie"
    
    if not db_path.exists():
        return f"Error: Code index database not found at {db_path}"
    
    try:
        with CodeIndexSDK(str(db_path)) as sdk:
            # Try to find as function first
            func_body = sdk.get_function_body(symbol_name, file_path)
            if func_body:
                return func_body
            
            # Try to find as class
            class_body = sdk.get_class_body(symbol_name, file_path)
            if class_body:
                return class_body
            
            # Search for similar symbols by name and description
            matches = sdk.search_symbols(symbol_name, limit=10)
            
            if matches:
                lines = [f"Symbol '{symbol_name}' not found by exact name. Similar symbols:"]
                for m in matches:
                    desc_suffix = f" — {m['description']}" if m.get('description') else ""
                    lines.append(f"  - {m['type']}: {m['name']} in {m['file_path']} ({m['match_reason']}){desc_suffix}")
                return "\n".join(lines)
            
            return f"Error: Symbol '{symbol_name}' not found in code index."
    except Exception as e:
        return f"Error querying code index: {str(e)}"
