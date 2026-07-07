#!/usr/bin/env python3
"""
Query mixin for CodeIndexSDK.
All get_* and search_* methods that read entities from the SQLite index.
"""

from typing import List, Dict, Optional, Any

from indexing.models import (
    Function, Class, Variable, TypeAlias,
    Struct, Interface, Enum, Namespace, File, Dependency,
)


class QueryMixin:
    """
    Mixin providing all query methods for the code index.
    Expects self.conn to be a sqlite3.Connection set by the host class.
    """

    # ==================== File Queries ====================

    def get_files(self, language: Optional[str] = None) -> List[File]:
        """Get all files, optionally filtered by language."""
        cursor = self.conn.cursor()
        if language:
            cursor.execute("SELECT * FROM files WHERE language = ? ORDER BY path", (language,))
        else:
            cursor.execute("SELECT * FROM files ORDER BY path")
        return [File.from_row(row) for row in cursor.fetchall()]

    def get_file_by_path(self, path: str) -> Optional[File]:
        """Get a file by its relative path."""
        cursor = self.conn.cursor()
        # Normalize path: strip leading ./ prefix if present
        normalized_path = path[2:] if path.startswith('./') else path
        
        cursor.execute("SELECT * FROM files WHERE path = ?", (normalized_path,))
        row = cursor.fetchone()
        return File.from_row(row) if row else None

    def get_file_by_id(self, file_id: int) -> Optional[File]:
        """Get a file by its ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
        row = cursor.fetchone()
        return File.from_row(row) if row else None

    def get_files_by_language(self, language: str) -> List[File]:
        """Get all files for a specific language."""
        return self.get_files(language)

    # ==================== Function Queries ====================

    def get_functions(self, file_id: Optional[int] = None) -> List[Function]:
        """Get all functions, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM functions WHERE file_id = ? AND parent_id IS NULL ORDER BY name",
                (file_id,)
            )
        else:
            cursor.execute(
                "SELECT * FROM functions WHERE parent_id IS NULL ORDER BY name"
            )

        functions = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                functions.append(Function.from_row(row, file.path))
        return functions

    def get_function_by_id(self, func_id: int) -> Optional[Function]:
        """Get a function by its ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM functions WHERE id = ?", (func_id,))
        row = cursor.fetchone()
        if row:
            file = self.get_file_by_id(row['file_id'])
            return Function.from_row(row, file.path) if file else None
        return None

    def get_function_by_name(self, name: str, file_id: Optional[int] = None) -> List[Function]:
        """Get functions by name, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM functions WHERE name = ? AND file_id = ? ORDER BY id",
                (name, file_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM functions WHERE name = ? ORDER BY id",
                (name,)
            )

        functions = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                functions.append(Function.from_row(row, file.path))
        return functions

    def search_functions(self, pattern: str, file_id: Optional[int] = None) -> List[Function]:
        """Search functions by name pattern (SQL LIKE)."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM functions WHERE name LIKE ? AND file_id = ? ORDER BY name",
                (f"%{pattern}%", file_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM functions WHERE name LIKE ? ORDER BY name",
                (f"%{pattern}%",)
            )

        functions = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                functions.append(Function.from_row(row, file.path))
        return functions

    def get_file_functions(self, file_id: int) -> List[Function]:
        """Get all top-level functions in a file."""
        return self.get_functions(file_id)

    def get_functions_by_complexity(self,
                                     min_branches: Optional[int] = None,
                                     min_lines: Optional[int] = None,
                                     max_branches: Optional[int] = None,
                                     max_lines: Optional[int] = None,
                                     match_any: bool = False,
                                     file_id: Optional[int] = None) -> List[Function]:
        """Filter functions by branch count and/or lines of code.

        Args:
            min_branches: Minimum number of branches (inclusive)
            min_lines: Minimum lines of code (inclusive)
            max_branches: Maximum number of branches (inclusive)
            max_lines: Maximum lines of code (inclusive)
            match_any: If True, uses LOGICAL OR (match either condition).
                      If False, uses LOGICAL AND (match all conditions).
            file_id: Optional file ID to filter by file

        Returns:
            List of Function objects matching the criteria
        """
        cursor = self.conn.cursor()
        conditions = []
        params = []

        # Build branch count conditions
        if min_branches is not None:
            conditions.append("branch_count >= ?")
            params.append(min_branches)
        if max_branches is not None:
            conditions.append("branch_count <= ?")
            params.append(max_branches)

        # Build lines of code conditions (parsed from location JSON)
        # location format: {"start_line": X, "end_line": Y, ...}
        if min_lines is not None:
            conditions.append("(json_extract(location, '$.end_line') - json_extract(location, '$.start_line') + 1) >= ?")
            params.append(min_lines)
        if max_lines is not None:
            conditions.append("(json_extract(location, '$.end_line') - json_extract(location, '$.start_line') + 1) <= ?")
            params.append(max_lines)

        if not conditions:
            return self.get_functions(file_id)

        # Determine operator: AND for all conditions, OR if match_any is True
        operator = " OR " if match_any else " AND "
        where_clause = f"parent_id IS NULL AND {operator.join(conditions)}"

        if file_id is not None:
            where_clause = f"file_id = ? AND {where_clause}"
            params.insert(0, file_id)

        query = f"SELECT * FROM functions WHERE {where_clause} ORDER BY branch_count DESC, name"
        cursor.execute(query, params)

        functions = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                functions.append(Function.from_row(row, file.path))
        return functions

    def get_complex_symbols(self,
                            min_branches: int = 5,
                            min_lines: int = 30,
                            match_any: bool = True) -> List[Function]:
        """Get "complex" functions matching either branch or LOC thresholds.

        Convenience method that finds functions that are likely complex:
        - High branching (many conditionals)
        - Long functions (many lines)

        Args:
            min_branches: Minimum branches threshold (default: 5)
            min_lines: Minimum lines threshold (default: 30)
            match_any: If True, returns functions with EITHER high branches OR long LOC.
                      If False, returns functions with BOTH high branches AND long LOC.

        Returns:
            List of Function objects sorted by complexity (branches desc)
        """
        return self.get_functions_by_complexity(
            min_branches=min_branches,
            min_lines=min_lines,
            match_any=match_any
        )

    def get_methods_by_complexity(self,
                                   class_id: int,
                                   min_branches: Optional[int] = None,
                                   min_lines: Optional[int] = None,
                                   max_branches: Optional[int] = None,
                                   max_lines: Optional[int] = None,
                                   match_any: bool = False) -> List[Function]:
        """Filter methods of a class by branch count and/or lines of code.

        Args match get_functions_by_complexity().
        """
        cursor = self.conn.cursor()
        conditions = ["parent_id = ?", "parent_type = 'class'"]
        params = [class_id]

        if min_branches is not None:
            conditions.append("branch_count >= ?")
            params.append(min_branches)
        if max_branches is not None:
            conditions.append("branch_count <= ?")
            params.append(max_branches)
        if min_lines is not None:
            conditions.append("(json_extract(location, '$.end_line') - json_extract(location, '$.start_line') + 1) >= ?")
            params.append(min_lines)
        if max_lines is not None:
            conditions.append("(json_extract(location, '$.end_line') - json_extract(location, '$.start_line') + 1) <= ?")
            params.append(max_lines)

        operator = " OR " if match_any else " AND "
        where_clause = operator.join(conditions)
        query = f"SELECT * FROM functions WHERE {where_clause} ORDER BY branch_count DESC, name"

        cursor.execute(query, params)
        methods = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                methods.append(Function.from_row(row, file.path))
        return methods

    # ==================== Method Queries ====================

    def get_methods(self, class_id: int) -> List[Function]:
        """Get all methods of a class."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM functions WHERE parent_id = ? AND parent_type = 'class' ORDER BY name",
            (class_id,)
        )

        methods = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                methods.append(Function.from_row(row, file.path))
        return methods

    def get_method_by_name(self, class_id: int, name: str) -> Optional[Function]:
        """Get a method by name within a class."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM functions WHERE parent_id = ? AND parent_type = 'class' AND name = ?",
            (class_id, name)
        )
        row = cursor.fetchone()
        if row:
            file = self.get_file_by_id(row['file_id'])
            return Function.from_row(row, file.path) if file else None
        return None

    # ==================== Class Queries ====================

    def get_classes(self, file_id: Optional[int] = None) -> List[Class]:
        """Get all top-level classes, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM classes WHERE file_id = ? AND parent_id IS NULL ORDER BY name",
                (file_id,)
            )
        else:
            cursor.execute(
                "SELECT * FROM classes WHERE parent_id IS NULL ORDER BY name"
            )

        classes = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                classes.append(Class.from_row(row, file.path))
        return classes

    def get_class_by_id(self, class_id: int) -> Optional[Class]:
        """Get a class by its ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM classes WHERE id = ?", (class_id,))
        row = cursor.fetchone()
        if row:
            file = self.get_file_by_id(row['file_id'])
            return Class.from_row(row, file.path) if file else None
        return None

    def get_class_by_name(self, name: str, file_id: Optional[int] = None) -> List[Class]:
        """Get classes by name, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM classes WHERE name = ? AND file_id = ? ORDER BY id",
                (name, file_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM classes WHERE name = ? ORDER BY id",
                (name,)
            )

        classes = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                classes.append(Class.from_row(row, file.path))
        return classes

    def search_classes(self, pattern: str, file_id: Optional[int] = None) -> List[Class]:
        """Search classes by name pattern (SQL LIKE)."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM classes WHERE name LIKE ? AND file_id = ? ORDER BY name",
                (f"%{pattern}%", file_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM classes WHERE name LIKE ? ORDER BY name",
                (f"%{pattern}%",)
            )

        classes = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                classes.append(Class.from_row(row, file.path))
        return classes

    def get_file_classes(self, file_id: int) -> List[Class]:
        """Get all top-level classes in a file."""
        return self.get_classes(file_id)

    def get_nested_classes(self, class_id: int) -> List[Class]:
        """Get all nested classes within a class."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM classes WHERE parent_id = ? ORDER BY name",
            (class_id,)
        )

        classes = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                classes.append(Class.from_row(row, file.path))
        return classes

    def get_class_methods(self, class_id: int) -> List[Function]:
        """Get all methods of a class."""
        return self.get_methods(class_id)

    def get_class_variables(self, class_id: int) -> List[Variable]:
        """Get all class attributes/variables."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM variables WHERE parent_id = ? AND parent_type = 'class' ORDER BY name",
            (class_id,)
        )

        variables = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                variables.append(Variable.from_row(row, file.path))
        return variables

    # ==================== Variable Queries ====================

    def get_variables(self, file_id: Optional[int] = None) -> List[Variable]:
        """Get all top-level variables, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM variables WHERE file_id = ? AND parent_id IS NULL ORDER BY name",
                (file_id,)
            )
        else:
            cursor.execute(
                "SELECT * FROM variables WHERE parent_id IS NULL ORDER BY name"
            )

        variables = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                variables.append(Variable.from_row(row, file.path))
        return variables

    def get_variable_by_id(self, var_id: int) -> Optional[Variable]:
        """Get a variable by its ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM variables WHERE id = ?", (var_id,))
        row = cursor.fetchone()
        if row:
            file = self.get_file_by_id(row['file_id'])
            return Variable.from_row(row, file.path) if file else None
        return None

    def get_variable_by_name(self, name: str, file_id: Optional[int] = None) -> List[Variable]:
        """Get variables by name, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM variables WHERE name = ? AND file_id = ? ORDER BY id",
                (name, file_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM variables WHERE name = ? ORDER BY id",
                (name,)
            )

        variables = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                variables.append(Variable.from_row(row, file.path))
        return variables

    def search_variables(self, pattern: str, file_id: Optional[int] = None) -> List[Variable]:
        """Search variables by name pattern (SQL LIKE)."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM variables WHERE name LIKE ? AND file_id = ? ORDER BY name",
                (f"%{pattern}%", file_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM variables WHERE name LIKE ? ORDER BY name",
                (f"%{pattern}%",)
            )

        variables = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                variables.append(Variable.from_row(row, file.path))
        return variables

    def get_file_variables(self, file_id: int) -> List[Variable]:
        """Get all top-level variables in a file."""
        return self.get_variables(file_id)

    # ==================== Type Alias Queries ====================

    def get_type_aliases(self, file_id: Optional[int] = None) -> List[TypeAlias]:
        """Get all type aliases, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM type_aliases WHERE file_id = ? ORDER BY name",
                (file_id,)
            )
        else:
            cursor.execute("SELECT * FROM type_aliases ORDER BY name")

        type_aliases = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                type_aliases.append(TypeAlias.from_row(row, file.path))
        return type_aliases

    def get_type_alias_by_id(self, alias_id: int) -> Optional[TypeAlias]:
        """Get a type alias by its ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM type_aliases WHERE id = ?", (alias_id,))
        row = cursor.fetchone()
        if row:
            file = self.get_file_by_id(row['file_id'])
            return TypeAlias.from_row(row, file.path) if file else None
        return None

    def get_type_alias_by_name(self, name: str, file_id: Optional[int] = None) -> List[TypeAlias]:
        """Get type aliases by name, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM type_aliases WHERE name = ? AND file_id = ? ORDER BY id",
                (name, file_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM type_aliases WHERE name = ? ORDER BY id",
                (name,)
            )

        type_aliases = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                type_aliases.append(TypeAlias.from_row(row, file.path))
        return type_aliases

    def search_type_aliases(self, pattern: str, file_id: Optional[int] = None) -> List[TypeAlias]:
        """Search type aliases by name pattern (SQL LIKE)."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM type_aliases WHERE name LIKE ? AND file_id = ? ORDER BY name",
                (f"%{pattern}%", file_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM type_aliases WHERE name LIKE ? ORDER BY name",
                (f"%{pattern}%",)
            )

        type_aliases = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                type_aliases.append(TypeAlias.from_row(row, file.path))
        return type_aliases

    # ==================== Struct Queries ====================

    def get_structs(self, file_id: Optional[int] = None) -> List[Struct]:
        """Get all structs, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM structs WHERE file_id = ? ORDER BY name",
                (file_id,)
            )
        else:
            cursor.execute("SELECT * FROM structs ORDER BY name")

        structs = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                structs.append(Struct.from_row(row, file.path))
        return structs

    def get_struct_by_id(self, struct_id: int) -> Optional[Struct]:
        """Get a struct by its ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM structs WHERE id = ?", (struct_id,))
        row = cursor.fetchone()
        if row:
            file = self.get_file_by_id(row['file_id'])
            return Struct.from_row(row, file.path) if file else None
        return None

    def get_struct_by_name(self, name: str, file_id: Optional[int] = None) -> List[Struct]:
        """Get structs by name, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM structs WHERE name = ? AND file_id = ? ORDER BY id",
                (name, file_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM structs WHERE name = ? ORDER BY id",
                (name,)
            )

        structs = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                structs.append(Struct.from_row(row, file.path))
        return structs

    # ==================== Enum Queries ====================

    def get_enums(self, file_id: Optional[int] = None) -> List[Enum]:
        """Get all enums, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM enums WHERE file_id = ? ORDER BY name",
                (file_id,)
            )
        else:
            cursor.execute("SELECT * FROM enums ORDER BY name")

        enums = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                enums.append(Enum.from_row(row, file.path))
        return enums

    def get_enum_by_id(self, enum_id: int) -> Optional[Enum]:
        """Get an enum by its ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM enums WHERE id = ?", (enum_id,))
        row = cursor.fetchone()
        if row:
            file = self.get_file_by_id(row['file_id'])
            return Enum.from_row(row, file.path) if file else None
        return None

    def get_enum_by_name(self, name: str, file_id: Optional[int] = None) -> List[Enum]:
        """Get enums by name, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM enums WHERE name = ? AND file_id = ? ORDER BY id",
                (name, file_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM enums WHERE name = ? ORDER BY id",
                (name,)
            )

        enums = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                enums.append(Enum.from_row(row, file.path))
        return enums

    # ==================== Namespace Queries ====================

    def get_namespaces(self, file_id: Optional[int] = None) -> List[Namespace]:
        """Get all namespaces, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM namespaces WHERE file_id = ? ORDER BY name",
                (file_id,)
            )
        else:
            cursor.execute("SELECT * FROM namespaces ORDER BY name")

        namespaces = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                namespaces.append(Namespace.from_row(row, file.path))
        return namespaces

    def get_namespace_by_id(self, namespace_id: int) -> Optional[Namespace]:
        """Get a namespace by its ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM namespaces WHERE id = ?", (namespace_id,))
        row = cursor.fetchone()
        if row:
            file = self.get_file_by_id(row['file_id'])
            return Namespace.from_row(row, file.path) if file else None
        return None

    def get_namespace_by_name(self, name: str, file_id: Optional[int] = None) -> List[Namespace]:
        """Get namespaces by name, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM namespaces WHERE name = ? AND file_id = ? ORDER BY id",
                (name, file_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM namespaces WHERE name = ? ORDER BY id",
                (name,)
            )

        namespaces = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                namespaces.append(Namespace.from_row(row, file.path))
        return namespaces

    def get_file_namespaces(self, file_id: int) -> List[Namespace]:
        """Get all namespaces in a file."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM namespaces WHERE file_id = ? ORDER BY name",
            (file_id,)
        )
        namespaces = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                namespaces.append(Namespace.from_row(row, file.path))
        return namespaces

    # ==================== Interface Queries ====================

    def get_interfaces(self, file_id: Optional[int] = None) -> List[Interface]:
        """Get all interfaces, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM interfaces WHERE file_id = ? ORDER BY name",
                (file_id,)
            )
        else:
            cursor.execute("SELECT * FROM interfaces ORDER BY name")

        interfaces = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                interfaces.append(Interface.from_row(row, file.path))
        return interfaces

    def get_interface_by_id(self, interface_id: int) -> Optional[Interface]:
        """Get an interface by its ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM interfaces WHERE id = ?", (interface_id,))
        row = cursor.fetchone()
        if row:
            file = self.get_file_by_id(row['file_id'])
            return Interface.from_row(row, file.path) if file else None
        return None

    def get_interface_by_name(self, name: str, file_id: Optional[int] = None) -> List[Interface]:
        """Get interfaces by name, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM interfaces WHERE name = ? AND file_id = ? ORDER BY id",
                (name, file_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM interfaces WHERE name = ? ORDER BY id",
                (name,)
            )

        interfaces = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                interfaces.append(Interface.from_row(row, file.path))
        return interfaces

    # ==================== Statistics ====================

    def get_statistics(self) -> Dict[str, int]:
        """Get overall statistics about the code index."""
        cursor = self.conn.cursor()

        stats = {}

        cursor.execute("SELECT COUNT(*) FROM files")
        stats['total_files'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM functions WHERE parent_id IS NULL")
        stats['total_functions'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM functions WHERE parent_id IS NOT NULL")
        stats['total_methods'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM classes WHERE parent_id IS NULL")
        stats['total_classes'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM variables WHERE parent_id IS NULL")
        stats['total_variables'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM type_aliases")
        stats['total_type_aliases'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM structs")
        stats['total_structs'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM interfaces")
        stats['total_interfaces'] = cursor.fetchone()[0]

        return stats

    def get_language_statistics(self) -> Dict[str, int]:
        """Get statistics grouped by language."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT language, COUNT(*) as count FROM files GROUP BY language ORDER BY count DESC")
        return {row['language']: row['count'] for row in cursor.fetchall()}

    # ==================== Dependency Queries ====================

    def get_dependencies(self, file_id: Optional[int] = None) -> List[Dependency]:
        """Get all dependencies, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM dependencies WHERE file_id = ? ORDER BY dependency_type, name",
                (file_id,)
            )
        else:
            cursor.execute("SELECT * FROM dependencies ORDER BY dependency_type, name")

        dependencies = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                dependencies.append(Dependency.from_row(row, file.path))
        return dependencies

    def get_file_imports(self, file_id: int) -> List[Dependency]:
        """Get all imports for a file."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM dependencies WHERE file_id = ? AND dependency_type = 'import' ORDER BY name",
            (file_id,)
        )

        imports = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                imports.append(Dependency.from_row(row, file.path))
        return imports

    def get_external_imports(self, file_id: Optional[int] = None) -> List[Dependency]:
        """Get external (third-party) imports, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM dependencies WHERE file_id = ? AND dependency_type = 'import' AND is_external = 1 ORDER BY name",
                (file_id,)
            )
        else:
            cursor.execute(
                "SELECT * FROM dependencies WHERE dependency_type = 'import' AND is_external = 1 ORDER BY name"
            )

        imports = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                imports.append(Dependency.from_row(row, file.path))
        return imports

    def get_internal_imports(self, file_id: Optional[int] = None) -> List[Dependency]:
        """Get internal (project) imports, optionally filtered by file."""
        cursor = self.conn.cursor()
        if file_id:
            cursor.execute(
                "SELECT * FROM dependencies WHERE file_id = ? AND dependency_type = 'import' AND is_external = 0 ORDER BY name",
                (file_id,)
            )
        else:
            cursor.execute(
                "SELECT * FROM dependencies WHERE dependency_type = 'import' AND is_external = 0 ORDER BY name"
            )

        imports = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                imports.append(Dependency.from_row(row, file.path))
        return imports

    def get_function_calls(self, function_id: int) -> List[Dependency]:
        """Get all function calls made by a specific function."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM dependencies WHERE source_function_id = ? AND dependency_type = 'function_call' ORDER BY name",
            (function_id,)
        )

        calls = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                calls.append(Dependency.from_row(row, file.path))
        return calls

    def get_function_dependencies(self, function_id: int, dependency_type: Optional[str] = None) -> List[Dependency]:
        """Get all dependencies of a specific function, optionally filtered by type.
        
        Args:
            function_id: The ID of the function to query
            dependency_type: Optional filter for dependency type. Can be:
                - 'import': Module imports
                - 'function_call': Function calls
                - 'method_call': Method calls
                - 'class_reference': Class references/instantiations
                - 'variable_reference': Variable references
                - 'module_reference': Module references
                If None, returns all dependency types.
        
        Returns:
            List of Dependency objects with precise location information
        """
        cursor = self.conn.cursor()
        if dependency_type:
            cursor.execute(
                "SELECT * FROM dependencies WHERE source_function_id = ? AND dependency_type = ? ORDER BY name",
                (function_id, dependency_type)
            )
        else:
            cursor.execute(
                "SELECT * FROM dependencies WHERE source_function_id = ? ORDER BY dependency_type, name",
                (function_id,)
            )

        dependencies = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                dependencies.append(Dependency.from_row(row, file.path))
        return dependencies

    def get_function_method_calls(self, function_id: int) -> List[Dependency]:
        """Get all method calls made by a specific function."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM dependencies WHERE source_function_id = ? AND dependency_type = 'method_call' ORDER BY name",
            (function_id,)
        )

        calls = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                calls.append(Dependency.from_row(row, file.path))
        return calls

    def get_function_class_references(self, function_id: int) -> List[Dependency]:
        """Get all class references made by a specific function."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM dependencies WHERE source_function_id = ? AND dependency_type = 'class_reference' ORDER BY name",
            (function_id,)
        )

        refs = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                refs.append(Dependency.from_row(row, file.path))
        return refs

    def get_function_variable_references(self, function_id: int) -> List[Dependency]:
        """Get all variable references made by a specific function."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM dependencies WHERE source_function_id = ? AND dependency_type = 'variable_reference' ORDER BY name",
            (function_id,)
        )

        refs = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                refs.append(Dependency.from_row(row, file.path))
        return refs

    def get_function_dependencies_by_name(self, function_name: str, file_id: Optional[int] = None, dependency_type: Optional[str] = None) -> List[Dependency]:
        """Get dependencies for a function by name, optionally filtered by file and dependency type.
        
        Args:
            function_name: The name of the function to query
            file_id: Optional file ID to disambiguate functions with the same name
            dependency_type: Optional filter for dependency type
        
        Returns:
            List of Dependency objects with precise location information
        """
        functions = self.get_function_by_name(function_name, file_id)
        if not functions:
            return []

        func = functions[0]
        return self.get_function_dependencies(func.id, dependency_type)

    def get_function_dependencies_grouped(self, function_id: int) -> Dict[str, List[Dependency]]:
        """Get all dependencies of a function grouped by type.
        
        Returns a dictionary with keys:
            - 'function_call': Function calls
            - 'method_call': Method calls
            - 'class_reference': Class references
            - 'variable_reference': Variable references
            - 'import': Module imports (if any)
        """
        all_deps = self.get_function_dependencies(function_id)
        grouped = {
            'function_call': [],
            'method_call': [],
            'class_reference': [],
            'variable_reference': [],
            'import': [],
            'module_reference': []
        }

        for dep in all_deps:
            if dep.dependency_type in grouped:
                grouped[dep.dependency_type].append(dep)

        return grouped

    def get_file_function_calls(self, file_id: int) -> List[Dependency]:
        """Get all function calls in a file."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM dependencies WHERE file_id = ? AND dependency_type = 'function_call' ORDER BY name",
            (file_id,)
        )

        calls = []
        for row in cursor.fetchall():
            file = self.get_file_by_id(row['file_id'])
            if file:
                calls.append(Dependency.from_row(row, file.path))
        return calls


class DescriptionMixin:
    """Mixin providing description update methods for code index entities."""

    def set_function_description(self, func_id: int, description: str) -> bool:
        """Set description for a function by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE functions SET description = ? WHERE id = ?",
            (description, func_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_function_description_by_name(self, name: str, description: str, file_path: Optional[str] = None) -> bool:
        """Set description for a function by name."""
        cursor = self.conn.cursor()
        if file_path:
            cursor.execute(
                """UPDATE functions SET description = ?
                   WHERE name = ? AND file_id = (SELECT id FROM files WHERE path = ?)""",
                (description, name, file_path)
            )
        else:
            cursor.execute(
                "UPDATE functions SET description = ? WHERE name = ?",
                (description, name)
            )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_method_description(self, method_id: int, description: str) -> bool:
        """Set description for a method by ID."""
        return self.set_function_description(method_id, description)

    def set_class_description(self, class_id: int, description: str) -> bool:
        """Set description for a class by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE classes SET description = ? WHERE id = ?",
            (description, class_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_class_description_by_name(self, name: str, description: str, file_path: Optional[str] = None) -> bool:
        """Set description for a class by name."""
        cursor = self.conn.cursor()
        if file_path:
            cursor.execute(
                """UPDATE classes SET description = ?
                   WHERE name = ? AND file_id = (SELECT id FROM files WHERE path = ?)""",
                (description, name, file_path)
            )
        else:
            cursor.execute(
                "UPDATE classes SET description = ? WHERE name = ?",
                (description, name)
            )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_variable_description(self, var_id: int, description: str) -> bool:
        """Set description for a variable by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE variables SET description = ? WHERE id = ?",
            (description, var_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_variable_description_by_name(self, name: str, description: str, file_path: Optional[str] = None) -> bool:
        """Set description for a variable by name."""
        cursor = self.conn.cursor()
        if file_path:
            cursor.execute(
                """UPDATE variables SET description = ?
                   WHERE name = ? AND file_id = (SELECT id FROM files WHERE path = ?)""",
                (description, name, file_path)
            )
        else:
            cursor.execute(
                "UPDATE variables SET description = ? WHERE name = ?",
                (description, name)
            )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_type_alias_description(self, alias_id: int, description: str) -> bool:
        """Set description for a type alias by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE type_aliases SET description = ? WHERE id = ?",
            (description, alias_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_type_alias_description_by_name(self, name: str, description: str, file_path: Optional[str] = None) -> bool:
        """Set description for a type alias by name."""
        cursor = self.conn.cursor()
        if file_path:
            cursor.execute(
                """UPDATE type_aliases SET description = ?
                   WHERE name = ? AND file_id = (SELECT id FROM files WHERE path = ?)""",
                (description, name, file_path)
            )
        else:
            cursor.execute(
                "UPDATE type_aliases SET description = ? WHERE name = ?",
                (description, name)
            )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_struct_description(self, struct_id: int, description: str) -> bool:
        """Set description for a struct by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE structs SET description = ? WHERE id = ?",
            (description, struct_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_struct_description_by_name(self, name: str, description: str, file_path: Optional[str] = None) -> bool:
        """Set description for a struct by name."""
        cursor = self.conn.cursor()
        if file_path:
            cursor.execute(
                """UPDATE structs SET description = ?
                   WHERE name = ? AND file_id = (SELECT id FROM files WHERE path = ?)""",
                (description, name, file_path)
            )
        else:
            cursor.execute(
                "UPDATE structs SET description = ? WHERE name = ?",
                (description, name)
            )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_interface_description(self, interface_id: int, description: str) -> bool:
        """Set description for an interface by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE interfaces SET description = ? WHERE id = ?",
            (description, interface_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_enum_description(self, enum_id: int, description: str) -> bool:
        """Set description for an enum by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE enums SET description = ? WHERE id = ?",
            (description, enum_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_enum_description_by_name(self, name: str, description: str, file_path: Optional[str] = None) -> bool:
        """Set description for an enum by name."""
        cursor = self.conn.cursor()
        if file_path:
            cursor.execute(
                """UPDATE enums SET description = ?
                   WHERE name = ? AND file_id = (SELECT id FROM files WHERE path = ?)""",
                (description, name, file_path)
            )
        else:
            cursor.execute(
                "UPDATE enums SET description = ? WHERE name = ?",
                (description, name)
            )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_interface_description_by_name(self, name: str, description: str, file_path: Optional[str] = None) -> bool:
        """Set description for an interface by name."""
        cursor = self.conn.cursor()
        if file_path:
            cursor.execute(
                """UPDATE interfaces SET description = ?
                   WHERE name = ? AND file_id = (SELECT id FROM files WHERE path = ?)""",
                (description, name, file_path)
            )
        else:
            cursor.execute(
                "UPDATE interfaces SET description = ? WHERE name = ?",
                (description, name)
            )
        self.conn.commit()
        return cursor.rowcount > 0

    def set_symbol_description(self, symbol_type: str, symbol_id: int, description: str) -> bool:
        """Set description for any symbol type by ID."""
        dispatch = {
            'function': self.set_function_description,
            'method': self.set_method_description,
            'class': self.set_class_description,
            'variable': self.set_variable_description,
            'type_alias': self.set_type_alias_description,
            'struct': self.set_struct_description,
            'interface': self.set_interface_description,
            'enum': self.set_enum_description,
        }

        if symbol_type not in dispatch:
            raise ValueError(f"Unknown symbol type: {symbol_type}. Must be one of: {list(dispatch.keys())}")

        return dispatch[symbol_type](symbol_id, description)

    def get_symbol_description(self, symbol_type: str, symbol_id: int) -> Optional[str]:
        """Get description for any symbol type by ID."""
        cursor = self.conn.cursor()
        table_map = {
            'function': 'functions',
            'method': 'functions',
            'class': 'classes',
            'variable': 'variables',
            'type_alias': 'type_aliases',
            'struct': 'structs',
            'interface': 'interfaces',
            'enum': 'enums',
        }

        if symbol_type not in table_map:
            raise ValueError(f"Unknown symbol type: {symbol_type}. Must be one of: {list(table_map.keys())}")

        table = table_map[symbol_type]
        cursor.execute(f"SELECT description FROM {table} WHERE id = ?", (symbol_id,))
        row = cursor.fetchone()
        return row['description'] if row else None

    def get_symbol_description_by_name(self, symbol_type: str, name: str, file_path: Optional[str] = None) -> Optional[str]:
        """Get description for a symbol by name and type."""
        cursor = self.conn.cursor()
        table_map = {
            'function': 'functions',
            'method': 'functions',
            'class': 'classes',
            'variable': 'variables',
            'type_alias': 'type_aliases',
            'struct': 'structs',
            'interface': 'interfaces',
            'enum': 'enums',
        }

        if symbol_type not in table_map:
            raise ValueError(f"Unknown symbol type: {symbol_type}. Must be one of: {list(table_map.keys())}")

        table = table_map[symbol_type]
        if file_path:
            cursor.execute(
                f"SELECT description FROM {table} WHERE name = ? AND file_id = (SELECT id FROM files WHERE path = ?)",
                (name, file_path)
            )
        else:
            cursor.execute(f"SELECT description FROM {table} WHERE name = ?", (name,))
        row = cursor.fetchone()
        return row['description'] if row else None

    def search_descriptions(self, query: str, symbol_types: Optional[List[str]] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Search for symbols by description content.

        Args:
            query: Search query string (searches description field using SQL LIKE)
            symbol_types: Optional list of symbol types to search (e.g., ['function', 'class']).
                         If None, searches all symbol types.
            limit: Maximum number of results to return

        Returns:
            List of dicts with keys: type, name, file_path, description
        """
        cursor = self.conn.cursor()
        like_pattern = f"%{query}%"
        results = []

        if symbol_types is None:
            symbol_types = ['function', 'class', 'variable', 'type_alias', 'struct', 'interface', 'enum']

        table_map = {
            'function': ('functions', 'function'),
            'method': ('functions', 'method'),
            'class': ('classes', 'class'),
            'variable': ('variables', 'variable'),
            'type_alias': ('type_aliases', 'type_alias'),
            'struct': ('structs', 'struct'),
            'interface': ('interfaces', 'interface'),
            'enum': ('enums', 'enum'),
        }

        for symbol_type in symbol_types:
            if symbol_type not in table_map:
                continue

            table, label = table_map[symbol_type]
            cursor.execute(
                f"SELECT name, file_id, description FROM {table} WHERE description LIKE ? LIMIT ?",
                (like_pattern, limit)
            )

            for row in cursor.fetchall():
                file = self.get_file_by_id(row['file_id'])
                if file:
                    results.append({
                        'type': label,
                        'name': row['name'],
                        'file_path': file.path,
                        'description': row['description']
                    })

        return results[:limit]

    def get_undocumented_symbols(self, symbol_types: Optional[List[str]] = None, file_id: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Get symbols that have no description.

        Args:
            symbol_types: Optional list of symbol types to check (e.g., ['function', 'class']).
                         If None, checks all symbol types.
            file_id: Optional file ID to filter by file

        Returns:
            Dict with symbol types as keys and lists of symbol info as values
        """
        cursor = self.conn.cursor()
        undocumented = {}

        if symbol_types is None:
            symbol_types = ['function', 'class', 'variable', 'type_alias', 'struct', 'interface', 'enum']

        table_map = {
            'function': ('functions', 'function', "parent_id IS NULL"),
            'method': ('functions', 'method', "parent_id IS NOT NULL AND parent_type = 'class'"),
            'class': ('classes', 'class', "parent_id IS NULL"),
            'variable': ('variables', 'variable', "parent_id IS NULL"),
            'type_alias': ('type_aliases', 'type_alias', "1=1"),
            'struct': ('structs', 'struct', "1=1"),
            'interface': ('interfaces', 'interface', "1=1"),
            'enum': ('enums', 'enum', "1=1"),
        }

        for symbol_type in symbol_types:
            if symbol_type not in table_map:
                continue

            table, label, extra_condition = table_map[symbol_type]
            conditions = ["(description IS NULL OR description = '')", extra_condition]
            params = []

            if file_id is not None:
                conditions.append("file_id = ?")
                params.append(file_id)

            where_clause = " AND ".join(conditions)
            query = f"SELECT name, file_id FROM {table} WHERE {where_clause} ORDER BY name"
            cursor.execute(query, params)

            symbols = []
            for row in cursor.fetchall():
                file = self.get_file_by_id(row['file_id'])
                if file:
                    symbols.append({
                        'name': row['name'],
                        'file_path': file.path
                    })

            if symbols:
                undocumented[label] = symbols

        return undocumented
