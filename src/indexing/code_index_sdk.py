#!/usr/bin/env python3
"""
Code Index SDK for AI Agents
Provides a high-level API for querying and traversing code indices stored in SQLite.
"""

import json
import sqlite3
from collections import deque
from pathlib import Path
from typing import List, Dict, Optional, Any, Union
from dataclasses import asdict

from indexing.models import (
    Function, Class, File, Dependency,
)
from indexing.queries import QueryMixin, DescriptionMixin


class CodeIndexSDK(QueryMixin, DescriptionMixin):
    """
    SDK for querying and traversing code indices.
    
    Example usage:
        sdk = CodeIndexSDK("code_index.db")
        
        # Get all files
        files = sdk.get_files()
        
        # Search for functions by name
        functions = sdk.search_functions("render")
        
        # Get a class and its methods
        cls = sdk.get_class_by_name("UserService")
        methods = sdk.get_class_methods(cls.id)
        
        # Get all functions in a file
        file_funcs = sdk.get_file_functions(file_id)
    """

    def __init__(self, db_path: str, root_dir: str = None):
        """Initialize the SDK with a database path and optional root directory for indexing."""
        self.db_path = db_path
        self.root_dir = root_dir
        self.conn = None
        self._connect()

    def index_directory(self, force_reindex: bool = False, verbose: bool = False):
        """Index the codebase directory into the database.

        Delegates to the internal CodeIndexer. This is the public API for
        triggering a re-index; external consumers should not import CodeIndexer directly.
        """
        from indexing.code_indexer import CodeIndexer
        indexer = CodeIndexer(
            root_dir=self.root_dir,
            db_path=self.db_path,
            force_reindex=force_reindex,
            verbose=verbose,
        )
        indexer.index_directory()
        self._connect()

    def _connect(self):
        """Establish database connection. Does not raise if the database does not exist yet
        (it will be created by index_directory)."""
        if not Path(self.db_path).exists():
            self.conn = None
            return
        self.conn = sqlite3.connect(self.db_path, timeout=30)  # Increase timeout for concurrent access
        self.conn.row_factory = sqlite3.Row

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    # ==================== Convenience Methods ====================

    def get_file_summary(self, file_id: int) -> Dict[str, Any]:
        """Get a summary of all code elements in a file."""
        file = self.get_file_by_id(file_id)
        if not file:
            return {}
        
        return {
            'file': asdict(file),
            'functions': [asdict(f) for f in self.get_file_functions(file_id)],
            'classes': [asdict(c) for c in self.get_file_classes(file_id)],
            'variables': [asdict(v) for v in self.get_file_variables(file_id)],
            'type_aliases': [asdict(t) for t in self.get_type_aliases(file_id)],
            'structs': [asdict(s) for s in self.get_structs(file_id)],
            'interfaces': [asdict(i) for i in self.get_interfaces(file_id)]
        }
    
    def get_class_summary(self, class_id: int) -> Dict[str, Any]:
        """Get a summary of a class including its methods and variables."""
        cls = self.get_class_by_id(class_id)
        if not cls:
            return {}
        
        return {
            'class': asdict(cls),
            'methods': [asdict(m) for m in self.get_class_methods(class_id)],
            'variables': [asdict(v) for v in self.get_class_variables(class_id)],
            'nested_classes': [asdict(c) for c in self.get_nested_classes(class_id)]
        }
    
    def search_all(self, pattern: str) -> Dict[str, List[Dict]]:
        """Search for pattern across all entity types."""
        return {
            'functions': [asdict(f) for f in self.search_functions(pattern)],
            'classes': [asdict(c) for c in self.search_classes(pattern)],
            'variables': [asdict(v) for v in self.search_variables(pattern)],
            'type_aliases': [asdict(t) for t in self.search_type_aliases(pattern)]
        }

    def search_symbols(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for symbols across functions, classes, and variables by name and description.

        Uses SQL LIKE for substring matching on both name and description fields.
        Results are ranked: exact name matches first, then partial name matches,
        then description matches.

        Args:
            query: Search query string
            limit: Maximum number of results to return

        Returns:
            List of dicts with keys: type, name, file_path, description, match_reason
        """
        cursor = self.conn.cursor()
        like_pattern = f"%{query}%"
        results = []

        # Exact name matches (highest priority)
        for table, label in [('functions', 'function'), ('classes', 'class'), ('variables', 'variable')]:
            cursor.execute(
                f"SELECT name, file_id, description FROM {table} WHERE name = ? LIMIT ?",
                (query, limit)
            )
            for row in cursor.fetchall():
                file = self.get_file_by_id(row['file_id'])
                if file:
                    results.append({
                        'type': label,
                        'name': row['name'],
                        'file_path': file.path,
                        'description': row['description'] if 'description' in row.keys() else None,
                        'match_reason': 'exact name match',
                        'rank': 0,
                    })

        # Partial name matches
        for table, label in [('functions', 'function'), ('classes', 'class'), ('variables', 'variable')]:
            cursor.execute(
                f"SELECT name, file_id, description FROM {table} WHERE name LIKE ? AND name != ? LIMIT ?",
                (like_pattern, query, limit)
            )
            for row in cursor.fetchall():
                file = self.get_file_by_id(row['file_id'])
                if file:
                    results.append({
                        'type': label,
                        'name': row['name'],
                        'file_path': file.path,
                        'description': row['description'] if 'description' in row.keys() else None,
                        'match_reason': 'partial name match',
                        'rank': 1,
                    })

        # Description matches (lower priority)
        for table, label in [('functions', 'function'), ('classes', 'class'), ('variables', 'variable')]:
            cursor.execute(
                f"SELECT name, file_id, description FROM {table} WHERE description LIKE ? AND name NOT LIKE ? LIMIT ?",
                (like_pattern, like_pattern, limit)
            )
            for row in cursor.fetchall():
                file = self.get_file_by_id(row['file_id'])
                if file:
                    results.append({
                        'type': label,
                        'name': row['name'],
                        'file_path': file.path,
                        'description': row['description'],
                        'match_reason': 'description match',
                        'rank': 2,
                    })

        # Sort by rank, then by name
        results.sort(key=lambda r: (r['rank'], r['name']))
        return results[:limit]
    
    def _render_callable_deps(self, lines: List[str], deps: Dict[str, List], indent: str) -> None:
        """Append 'depending on:' lines for a function/method's grouped deps."""
        lines.append(f'{indent}depending on:')
        dep_indent = indent + '  '
        seen_deps: set = set()

        type_labels = [
            ('function_call', 'function', '()'),
            ('method_call',   'method',   '()'),
            ('class_reference', 'class',  ''),
            ('variable_reference', 'variable', ''),
        ]
        resolvers = {
            'function_call':     self._resolve_function_definition,
            'method_call':       self._resolve_method_definition,
            'class_reference':   self._resolve_class_definition,
            'variable_reference': self._resolve_variable_definition,
        }

        for dep_type, label, suffix in type_labels:
            for dep in deps[dep_type]:
                if self._is_likely_literal(dep.name):
                    continue
                dep_key = f"{label}:{dep.name}"
                if dep_key in seen_deps:
                    continue
                def_info = resolvers[dep_type](dep.name)
                if def_info:
                    lines.append(f'{dep_indent}- {label} {dep.name}{suffix} in file "{def_info["file_path"]}"')
                    seen_deps.add(dep_key)

        if not seen_deps:
            lines.append(f'{dep_indent}NONE')

    def _render_class_members(self, lines: List[str], cls: 'Class', method_indent: str) -> None:
        """Append member lines (methods + variables) for a class."""
        methods = self.get_class_methods(cls.id)
        class_vars = self.get_class_variables(cls.id)

        if not methods and not class_vars:
            lines.append(f'{method_indent}  NONE')
            return

        for method in methods:
            params_str = self._format_parameters(method.parameters)
            desc_annotation = f"  # {method.description}" if method.description else ""
            lines.append(f'{method_indent}- method {method.name}({params_str}){desc_annotation}:')
            deps = self.get_function_dependencies_grouped(method.id)
            self._render_callable_deps(lines, deps, method_indent + '     ')

        for var in class_vars:
            type_suffix = f" : {var.field_type}" if var.field_type else ""
            desc_annotation = f"  # {var.description}" if var.description else ""
            lines.append(f'{method_indent}- variable {var.name}{type_suffix}{desc_annotation}')

    def _render_nested_classes(self, lines: List[str], func: 'Function', file: 'File') -> None:
        """Append 'contains: nested classes' block for a function if any."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM classes WHERE parent_id = ? AND file_id = ?",
            (func.id, file.id)
        )
        nested_rows = cursor.fetchall()
        if not nested_rows:
            return

        lines.append('     contains:')
        for row in nested_rows:
            nested_cls = Class.from_row(row, file.path)
            desc_annotation = f"  # {nested_cls.description}" if nested_cls.description else ""
            lines.append(f'       - class {nested_cls.name}{desc_annotation}:')
            lines.append(f'           members:')
            self._render_class_members(lines, nested_cls, '             ')

    def get_dependency_graph(self, file_path: str) -> str:
        """Get a YAML-like formatted dependency graph for a file.
        
        Args:
            file_path: Relative path to the file in the database
        
        Returns:
            YAML-like formatted string showing the dependency graph
        """
        normalized_path = file_path[2:] if file_path.startswith('./') else file_path
        file = self.get_file_by_path(normalized_path)

        if not file:
            filename = Path(normalized_path).name
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM files WHERE path LIKE ?", (f"%{filename}",))
            row = cursor.fetchone()
            if row:
                file = File.from_row(row)

        if not file:
            return f"Error: File not found in database: {file_path}"

        lines = [f'file "{file_path}":']

        for func in self.get_file_functions(file.id):
            params_str = self._format_parameters(func.parameters)
            desc_annotation = f"  # {func.description}" if func.description else ""
            lines.append(f'  - function {func.name}({params_str}) in file "{file_path}"{desc_annotation}')
            deps = self.get_function_dependencies_grouped(func.id)
            self._render_callable_deps(lines, deps, '     ')
            self._render_nested_classes(lines, func, file)

        seen_vars: set = set()
        for var in self.get_file_variables(file.id):
            if var.name in seen_vars:
                continue
            seen_vars.add(var.name)
            type_suffix = f" : {var.field_type}" if var.field_type else ""
            desc_annotation = f"  # {var.description}" if var.description else ""
            lines.append(f'  - variable {var.name}{type_suffix} in file "{file_path}"{desc_annotation}')

        for imp in self.get_file_imports(file.id):
            lines.append(f'  - imported {imp.name} in file "{file_path}"')

        for ns in self.get_file_namespaces(file.id):
            lines.append(f'  - namespace {ns.name} in file "{file_path}"')

        for cls in self.get_file_classes(file.id):
            desc_annotation = f"  # {cls.description}" if cls.description else ""
            ns_annotation = f"  # namespace: {cls.namespace}" if cls.namespace else ""
            lines.append(f'  - class {cls.name} in file "{file_path}"{desc_annotation}{ns_annotation}:')
            lines.append(f'      members:')
            self._render_class_members(lines, cls, '        ')

        return '\n'.join(lines)
    
    def _resolve_function_definition(self, name: str) -> Optional[Dict]:
        """Resolve a function name to its definition location."""
        functions = self.get_function_by_name(name)
        if functions:
            # Return the first match
            func = functions[0]
            return {"file_path": func.file_path}
        return None
    
    def _resolve_method_definition(self, name: str) -> Optional[Dict]:
        """Resolve a method name to its definition location."""
        # Strip the object part (e.g., "self.init" -> "init", "context.SaveChangesAsync" -> "SaveChangesAsync")
        method_name = name.rsplit('.', 1)[-1] if '.' in name else name
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT f.*, file.path FROM functions f JOIN files file ON f.file_id = file.id WHERE f.name = ? AND f.parent_type = 'class' LIMIT 1",
            (method_name,)
        )
        row = cursor.fetchone()
        if row:
            return {"file_path": row['path']}
        return None
    
    def _resolve_class_definition(self, name: str) -> Optional[Dict]:
        """Resolve a class name to its definition location."""
        classes = self.get_class_by_name(name)
        if classes:
            cls = classes[0]
            return {"file_path": cls.file_path}
        return None
    
    def _resolve_variable_definition(self, name: str) -> Optional[Dict]:
        """Resolve a variable name to its definition location."""
        variables = self.get_variable_by_name(name)
        if variables:
            var = variables[0]
            return {"file_path": var.file_path}
        return None
    
    def _is_likely_literal(self, name: str) -> bool:
        """Check if a dependency name is likely a literal string or unimplemented function.
        
        Returns True if the name appears to be:
        - A string literal (contains quotes, spaces, or special characters)
        - A temporary/inline expression
        """
        # Check for string literals with quotes
        if '"' in name or "'" in name:
            return True
        
        # Check for spaces (indicates multi-word string literal)
        if ' ' in name:
            return True
        
        # Check for common literal patterns (command-like)
        if name.startswith(('echo ', 'print ', 'return ', 'cd ', 'ls ', 'cat ')):
            return True
        
        # Check for format patterns (string formatting)
        if '.format(' in name or ('%' in name and '(' in name and name.count('%') > 1):
            return True
        
        # Check for obvious expressions (multiple operators without function-like structure)
        # Allow single operators like "x++" or "x--" but filter complex expressions
        operator_count = sum(1 for op in ['+', '-', '*', '/', '=', '==', '!=', '<', '>', '<=', '>='] if op in name)
        if operator_count >= 2:
            return True
        
        return False
    
    def _format_parameters(self, parameters: Union[List[Dict], str]) -> str:
        """Format parameters list into a string."""
        if not parameters:
            return ""

        # Handle case where parameters might be a string (JSON not parsed)
        if isinstance(parameters, str):
            try:
                parameters = json.loads(parameters)
            except:
                return parameters

        param_strs = []
        for param in parameters:
            if isinstance(param, str):
                param_strs.append(param)
            elif isinstance(param, dict):
                name = param.get('name', '')
                param_type = param.get('type', '')
                if param_type:
                    param_strs.append(f"{name}: {param_type}")
                else:
                    param_strs.append(name)
        
        return ', '.join(param_strs)

    # ==================== Source Body Reading ====================

    def _read_source_lines(self, file_id: int, start_line: int, end_line: int) -> Optional[str]:
        """Read lines [start_line, end_line] (1-indexed, inclusive) from a source file.
        
        Uses File.absolute_path from the index; falls back to resolving the relative
        path against cwd and cwd/src if the absolute path no longer exists.
        Returns None if the file cannot be found.
        """
        db_file = self.get_file_by_id(file_id)
        if not db_file:
            return None

        source = Path(db_file.absolute_path)
        if not source.exists():
            for base in (Path.cwd(), Path.cwd() / "src"):
                candidate = base / db_file.path
                if candidate.exists():
                    source = candidate
                    break

        if not source.exists():
            return None

        with open(source, 'r', encoding='utf-8') as f:
            lines = f.read().split('\n')

        return '\n'.join(lines[start_line - 1:end_line])

    def get_function_body(self, function_name: str, file_path: Optional[str] = None) -> Optional[str]:
        """Get the source body of a function or method by name.
        
        Args:
            function_name: Name of the function/method.
            file_path: Optional relative file path to disambiguate same-name functions.
        
        Returns:
            Source code string with description, or None if not found / file unresolvable.
        """
        file_id = None
        if file_path:
            f = self.get_file_by_path(file_path)
            if f:
                file_id = f.id

        matches = self.get_function_by_name(function_name, file_id)
        if not matches:
            return None

        # Prefer implementations (methods inside classes) over interface declarations
        # Interface declarations are standalone functions with no body — implementations
        # have parent_type='class' and contain actual code
        func = matches[0]
        if len(matches) > 1:
            impls = [m for m in matches if m.parent_type == 'class']
            if impls:
                func = impls[0]
        body = self._read_source_lines(func.file_id, func.location.start_line, func.location.end_line)
        
        if func.description:
            return f"# Description: {func.description}\n\n{body}"
        return body

    def walk_call_tree(self, symbol_name: str, file_path: Optional[str] = None,
                       max_depth: int = 5, include_external: bool = False,
                       exclude: Optional[List[str]] = None) -> str:
        """Walk the call tree starting from a function/method, depth-limited with cycle detection.

        Returns JSON lines (one JSON object per line), sorted by depth then name. Each node has:
            id: unique ID for follow-up queries (e.g. "f:123")
            name: symbol name
            kind: "function" or "method"
            file: relative file path
            line: start line number
            snippet: first line of the body (one-liner)
            depth: distance from root
            cycle: true if this node appeared earlier in the path
            callees: list of child node IDs

        Args:
            symbol_name: Name of the starting function/method. Can be "ClassName.method" syntax.
            file_path: Optional file path to disambiguate same-name symbols.
            max_depth: Maximum depth to traverse (default 5).
            include_external: If True, include external/third-party calls (unresolved).
            exclude: Optional list of path prefixes to exclude (e.g. ["tests/"]).
        """
        file_id = None
        if file_path:
            f = self.get_file_by_path(file_path)
            if f:
                file_id = f.id

        # First check if it's a class name (for walking all methods)
        classes = self.get_class_by_name(symbol_name, file_id)
        if classes:
            # Class-based walk: walk all methods of the class
            cls = classes[0]
            methods = self.get_class_methods(cls.id)
            if not methods:
                return json.dumps({"error": f"Class '{symbol_name}' has no methods"})
            
            # Return information about the class and its methods
            result = {
                "type": "class",
                "name": cls.name,
                "file": cls.file_path,
                "line": cls.location.start_line,
                "methods": [
                    {
                        "id": f"f:{m.id}",
                        "name": m.name,
                        "line": m.location.start_line,
                        "snippet": self._read_one_line_snippet(m.file_id, m.location.start_line)
                    }
                    for m in methods
                ]
            }
            return json.dumps(result, ensure_ascii=False)

        # Handle Class.method syntax
        if '.' in symbol_name:
            parts = symbol_name.split('.', 1)
            class_name = parts[0]
            method_name = parts[1]
            
            # Find the class
            classes = self.get_class_by_name(class_name, file_id)
            if not classes:
                return json.dumps({"error": f"Class not found: {class_name}"})
            
            cls = classes[0]
            # Find the method within the class
            method = self.get_method_by_name(cls.id, method_name)
            if not method:
                return json.dumps({"error": f"Method '{method_name}' not found in class '{class_name}'"})
            
            root_func = method
        else:
            # Handle plain function/method name
            functions = self.get_function_by_name(symbol_name, file_id)
            if not functions:
                return json.dumps({"error": f"Symbol not found: {symbol_name}"})
            root_func = functions[0]
            # Prefer implementations (methods inside classes) over interface declarations
            if len(functions) > 1:
                impls = [f for f in functions if f.parent_type == 'class']
                if impls:
                    root_func = impls[0]

        root_id = f"f:{root_func.id}"
        root_snippet = self._read_one_line_snippet(root_func.file_id, root_func.location.start_line)

        nodes: Dict[str, Dict[str, Any]] = {}
        nodes[root_id] = {
            "id": root_id,
            "name": root_func.name,
            "kind": root_func.type,
            "file": root_func.file_path,
            "line": root_func.location.start_line,
            "snippet": root_snippet,
            "depth": 0,
            "cycle": False,
            "callees": [],
        }

        queue: deque = deque()
        queue.append((root_func.id, root_id, 0, frozenset([root_func.id])))

        cursor = self.conn.cursor()

        while queue:
            func_id, parent_node_id, depth, ancestors = queue.popleft()
            if depth >= max_depth:
                continue

            # Get the file_id for this function to pass to resolver
            cursor.execute("SELECT file_id FROM functions WHERE id = ?", (func_id,))
            row = cursor.fetchone()
            source_file_id = row['file_id'] if row else None

            cursor.execute(
                """SELECT * FROM dependencies
                   WHERE source_function_id = ?
                     AND dependency_type IN ('function_call', 'method_call', 'class_reference')
                   ORDER BY name""",
                (func_id,)
            )

            seen_callees = set()  # Track seen callees to avoid duplicates
            for row in cursor.fetchall():
                dep = Dependency.from_row(row, "")
                if self._is_likely_literal(dep.name):
                    continue

                # Create a unique key for deduplication (include dependency_type to distinguish class_reference from function_call)
                callee_key = (dep.name, dep.target_function_id, dep.dependency_type)
                if callee_key in seen_callees:
                    continue
                seen_callees.add(callee_key)

                callee_func = self._resolve_call_target(dep, source_file_id)
                if callee_func is None:
                    if include_external and dep.name:
                        ext_id = f"ext:{dep.name}"
                        if ext_id not in nodes:
                            nodes[ext_id] = {
                                "id": ext_id,
                                "name": dep.name,
                                "kind": "external",
                                "file": "",
                                "line": 0,
                                "snippet": "",
                                "depth": depth + 1,
                                "cycle": False,
                                "callees": [],
                            }
                        # Only add to parent's callees if not already present
                        if ext_id not in nodes[parent_node_id]["callees"]:
                            nodes[parent_node_id]["callees"].append(ext_id)
                    continue

                # Skip callees in excluded paths
                if exclude and any(callee_func.file_path.startswith(p) for p in exclude):
                    continue

                callee_id = f"f:{callee_func.id}"
                is_cycle = callee_func.id in ancestors

                if callee_id not in nodes:
                    snippet = self._read_one_line_snippet(
                        callee_func.file_id, callee_func.location.start_line
                    )
                    nodes[callee_id] = {
                        "id": callee_id,
                        "name": callee_func.name,
                        "kind": callee_func.type,
                        "file": callee_func.file_path,
                        "line": callee_func.location.start_line,
                        "snippet": snippet,
                        "depth": depth + 1,
                        "cycle": is_cycle,
                        "callees": [],
                    }
                elif is_cycle:
                    nodes[callee_id]["cycle"] = True

                # Only add to parent's callees if not already present
                if callee_id not in nodes[parent_node_id]["callees"]:
                    nodes[parent_node_id]["callees"].append(callee_id)

                if not is_cycle and depth + 1 < max_depth:
                    queue.append((callee_func.id, callee_id, depth + 1,
                                  ancestors | {callee_func.id}))

        sorted_nodes = sorted(nodes.values(), key=lambda n: (n["depth"], n["name"]))
        lines = [json.dumps(node, ensure_ascii=False) for node in sorted_nodes]
        return "\n".join(lines)

    def _resolve_call_target(self, dep: Dependency, source_file_id: Optional[int] = None) -> Optional['Function']:
        """Resolve a function_call, method_call, or class_reference dependency to its Function definition.
        
        Args:
            dep: The dependency to resolve
            source_file_id: Optional file ID of the source making the call, used for disambiguation
        """
        if dep.dependency_type == 'function_call':
            # Prefer functions in the same file if available
            if source_file_id:
                funcs = self.get_function_by_name(dep.name, source_file_id)
                if funcs:
                    return funcs[0]
            # Fall back to any function with that name
            funcs = self.get_function_by_name(dep.name)
            if funcs:
                return funcs[0]
        elif dep.dependency_type == 'method_call':
            # For method calls, strip the object part (e.g., "self.init" -> "init")
            method_name = dep.name.rsplit('.', 1)[-1] if '.' in dep.name else dep.name
            cursor = self.conn.cursor()
            # Prefer methods in the same file
            if source_file_id:
                cursor.execute(
                    "SELECT f.*, file.path FROM functions f JOIN files file ON f.file_id = file.id "
                    "WHERE f.name = ? AND f.parent_type = 'class' AND f.file_id = ? LIMIT 1",
                    (method_name, source_file_id)
                )
                row = cursor.fetchone()
                if row:
                    return Function.from_row(row, row['path'])
            # Fall back to any method with that name
            cursor.execute(
                "SELECT f.*, file.path FROM functions f JOIN files file ON f.file_id = file.id "
                "WHERE f.name = ? AND f.parent_type = 'class' LIMIT 1",
                (method_name,)
            )
            row = cursor.fetchone()
            if row:
                return Function.from_row(row, row['path'])
        elif dep.dependency_type == 'class_reference':
            # For class references (instantiations), try to find the class's __init__ method
            cursor = self.conn.cursor()
            
            # Use target_class_id if available (already resolved during indexing)
            class_id = dep.target_class_id
            
            # Otherwise, find the class by name
            if class_id is None:
                if source_file_id:
                    cursor.execute(
                        "SELECT id FROM classes WHERE name = ? AND file_id = ? LIMIT 1",
                        (dep.name, source_file_id)
                    )
                    row = cursor.fetchone()
                    if row:
                        class_id = row['id']
                
                if class_id is None:
                    cursor.execute(
                        "SELECT id FROM classes WHERE name = ? LIMIT 1",
                        (dep.name,)
                    )
                    row = cursor.fetchone()
                    if row:
                        class_id = row['id']
            
            # If we found the class, get its __init__ method
            if class_id is not None:
                cursor.execute(
                    "SELECT f.*, file.path FROM functions f JOIN files file ON f.file_id = file.id "
                    "WHERE f.name = '__init__' AND f.parent_id = ? AND f.parent_type = 'class' LIMIT 1",
                    (class_id,)
                )
                row = cursor.fetchone()
                if row:
                    return Function.from_row(row, row['path'])
        return None

    def _read_one_line_snippet(self, file_id: int, start_line: int) -> str:
        """Read the first actual code line after the function signature as a one-line snippet.
        
        Skips blank lines, comments, docstrings, and nested function definitions to find the first executable line.
        """
        # Read up to 50 lines to find the first actual code line (increased for robustness)
        max_lines = 50
        for offset in range(1, max_lines + 1):
            line = self._read_source_lines(file_id, start_line + offset, start_line + offset)
            if not line:
                break
            
            stripped = line.strip()
            # Skip empty lines
            if not stripped:
                continue
            # Skip comment lines (Python #, C-style //, etc.)
            if stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('/*'):
                continue
            # Skip docstring-like lines (triple quotes)
            if stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Skip decorator lines
            if stripped.startswith('@'):
                continue
            # Skip nested function/class definitions (def, class)
            if stripped.startswith('def ') or stripped.startswith('class '):
                continue
            # Skip opening/closing braces (C#, Java, etc.)
            if stripped in ('{', '}', '};'):
                continue
            # Skip print statements that might be debug output
            if stripped.startswith('print('):
                continue
            
            # Found a code line - return it truncated
            return stripped[:120]
        
        return ""

    def get_class_body(self, class_name: str, file_path: Optional[str] = None) -> Optional[str]:
        """Get the source body of a class by name.
        
        Args:
            class_name: Name of the class.
            file_path: Optional relative file path to disambiguate same-name classes.
        
        Returns:
            Source code string with description, or None if not found / file unresolvable.
        """
        file_id = None
        if file_path:
            f = self.get_file_by_path(file_path)
            if f:
                file_id = f.id

        matches = self.get_class_by_name(class_name, file_id)
        if not matches:
            return None

        cls = matches[0]
        body = self._read_source_lines(cls.file_id, cls.location.start_line, cls.location.end_line)
        
        if cls.description:
            return f"# Description: {cls.description}\n\n{body}"
        return body
