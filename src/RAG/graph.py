import json
from pathlib import Path

from indexing.code_index_sdk import CodeIndexSDK


def explore_code_structure(file_path: str, include_bodies: bool = False) -> str:
    """Explore the code structure and dependencies of a file.

    Args:
        file_path: Path to the file to analyze
        include_bodies: If True, include full source code for all functions and classes in the file

    Returns:
        YAML-like formatted string showing the dependency graph, optionally with symbol bodies.
        For frontend files (HTML, CSS, JSX, TSX), returns structured semantic output instead.
    """
    db_path = Path.cwd() / ".raggie" / ".code_index.raggie"

    if not db_path.exists():
        return f"Error: Code index database not found at {db_path}"

    try:
        with CodeIndexSDK(str(db_path)) as sdk:
            # Check if this is a frontend file
            from indexing.frontend.semantic_output import format_file_semantics
            semantic = format_file_semantics(sdk.conn, file_path)
            if semantic is not None:
                # Frontend file — return semantic output
                if include_bodies:
                    # Append raw source when bodies are explicitly requested
                    normalized = file_path[2:] if file_path.startswith('./') else file_path
                    file = sdk.get_file_by_path(normalized)
                    if file:
                        raw = sdk._read_source_lines(file.id, 1, 0) if hasattr(sdk, '_read_source_lines') else ""
                        if raw:
                            return semantic + "\n\n## Raw Source\n" + raw
                return semantic

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


def explore_frontend_structure(file_path: str) -> str:
    """Explore the frontend structure of a file (components, markup, styles, events).

    Args:
        file_path: Path to the frontend file (TSX, HTML, CSS).

    Returns:
        JSON string with component info, markup trees, events, bindings, and styles.
    """
    db_path = Path.cwd() / ".raggie" / ".code_index.raggie"

    if not db_path.exists():
        return json.dumps({"error": f"Code index database not found at {db_path}"})

    try:
        with CodeIndexSDK(str(db_path)) as sdk:
            file = sdk.get_file_by_path(file_path)
            if not file:
                from pathlib import Path as _Path
                filename = _Path(file_path[2:] if file_path.startswith('./') else file_path).name
                cursor = sdk.conn.cursor()
                cursor.execute("SELECT * FROM files WHERE path LIKE ?", (f"%{filename}",))
                row = cursor.fetchone()
                if row:
                    from indexing.models import File
                    file = File.from_row(row)
            if not file:
                return json.dumps({"error": f"File not found: {file_path}"})

            cursor = sdk.conn.cursor()

            # Get components in this file
            cursor.execute(
                "SELECT id, name, framework, is_exported FROM frontend_components WHERE file_id = ?",
                (file.id,)
            )
            components = [dict(row) for row in cursor.fetchall()]

            result = {
                "file_path": file_path,
                "components": [],
            }

            for comp in components:
                traversal = sdk.traverse_full_frontend(comp["id"])
                result["components"].append(traversal)

            # If no components, try markup elements (HTML)
            if not components:
                cursor.execute(
                    "SELECT id, tag_name, element_type FROM markup_elements WHERE file_id = ? ORDER BY id",
                    (file.id,)
                )
                elements = [dict(row) for row in cursor.fetchall()]
                if elements:
                    result["markup_elements"] = elements

                cursor.execute(
                    "SELECT id, selector_text, selector_type FROM style_selectors WHERE file_id = ? ORDER BY id",
                    (file.id,)
                )
                selectors = [dict(row) for row in cursor.fetchall()]
                if selectors:
                    result["style_selectors"] = selectors

            return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"Error exploring frontend structure: {str(e)}"})


def walk_render_tree(component_name: str, file_path: str = None,
                     max_depth: int = 10) -> str:
    """Walk the render tree starting from a component, depth-limited with cycle detection.

    Args:
        component_name: Name of the starting component.
        file_path: Optional file path to disambiguate same-name components.
        max_depth: Maximum traversal depth (default 10).

    Returns:
        JSON string with the render tree (children direction).
    """
    db_path = Path.cwd() / ".raggie" / ".code_index.raggie"

    if not db_path.exists():
        return json.dumps({"error": f"Code index database not found at {db_path}"})

    try:
        with CodeIndexSDK(str(db_path)) as sdk:
            cursor = sdk.conn.cursor()

            if file_path:
                file = sdk.get_file_by_path(file_path)
                if file:
                    cursor.execute(
                        "SELECT id FROM frontend_components WHERE name = ? AND file_id = ? LIMIT 1",
                        (component_name, file.id)
                    )
                else:
                    cursor.execute(
                        "SELECT id FROM frontend_components WHERE name = ? LIMIT 1",
                        (component_name,)
                    )
            else:
                cursor.execute(
                    "SELECT id FROM frontend_components WHERE name = ? LIMIT 1",
                    (component_name,)
                )

            row = cursor.fetchone()
            if not row:
                return json.dumps({"error": f"Component not found: {component_name}"})

            result = sdk.traverse_render_graph(row["id"], "children", max_depth)
            return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"Error walking render tree: {str(e)}"})
