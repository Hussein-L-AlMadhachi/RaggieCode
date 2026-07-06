import json
from pathlib import Path

from indexing.code_index_sdk import CodeIndexSDK


def explore_code_structure(file_path: str, include_bodies: bool = False) -> str:
    """Explore the code structure and dependencies of a file.

    Args:
        file_path: Path to the file to analyze
        include_bodies: If True, include full source code for all functions and classes in the file

    Returns:
        YAML-like formatted string showing the dependency graph, optionally with symbol bodies
    """
    db_path = Path.cwd() / ".raggie" / ".code_index.raggie"

    if not db_path.exists():
        return f"Error: Code index database not found at {db_path}"

    try:
        with CodeIndexSDK(str(db_path)) as sdk:
            graph = sdk.get_dependency_graph(file_path)

            if not include_bodies:
                return graph

            # Get the file to fetch all symbols
            file = sdk.get_file_by_path(file_path)
            if not file:
                # Fallback: try matching by filename (same logic as get_dependency_graph)
                from pathlib import Path as _Path
                filename = _Path(file_path[2:] if file_path.startswith('./') else file_path).name
                cursor = sdk.conn.cursor()
                cursor.execute("SELECT * FROM files WHERE path LIKE ?", (f"%{filename}",))
                row = cursor.fetchone()
                if row:
                    from indexing.models import File
                    file = File.from_row(row)
            if not file:
                return graph

            # Get all functions and classes in the file
            functions = sdk.get_file_functions(file.id)
            classes = sdk.get_file_classes(file.id)

            # Build the bodies section
            bodies_section = []
            if functions:
                bodies_section.append("\n## Function Bodies")
                for func in functions:
                    body = sdk._read_source_lines(func.file_id, func.location.start_line, func.location.end_line)
                    desc = f"# Description: {func.description}\n\n" if func.description else ""
                    bodies_section.append(f"\n### {func.name}\n{desc}{body}")

            if classes:
                bodies_section.append("\n## Class Bodies")
                for cls in classes:
                    body = sdk._read_source_lines(cls.file_id, cls.location.start_line, cls.location.end_line)
                    desc = f"# Description: {cls.description}\n\n" if cls.description else ""
                    bodies_section.append(f"\n### {cls.name}\n{desc}{body}")

            if bodies_section:
                return graph + "\n" + "".join(bodies_section)

            return graph
    except Exception as e:
        return f"Error querying code index: {str(e)}"


def walk_call_tree(symbol_name: str, file_path: str = None,
                   max_depth: int = 5, include_external: bool = False,
                   exclude: list = None) -> str:
    """Walk the call tree starting from a function/method, depth-limited with cycle detection.

    Args:
        symbol_name: Name of the starting function/method.
        file_path: Optional file path to disambiguate same-name symbols.
        max_depth: Maximum depth to traverse (default 5).
        include_external: If True, include external/third-party calls.
        exclude: Optional list of path prefixes to exclude (e.g. ["tests/"]).

    Returns:
        JSON lines string, one object per node, sorted by depth then name.
    """
    db_path = Path.cwd() / ".raggie" / ".code_index.raggie"

    if not db_path.exists():
        return json.dumps({"error": f"Code index database not found at {db_path}"})

    try:
        with CodeIndexSDK(str(db_path)) as sdk:
            return sdk.walk_call_tree(symbol_name, file_path, max_depth, include_external, exclude)
    except Exception as e:
        return json.dumps({"error": f"Error walking call tree: {str(e)}"})
