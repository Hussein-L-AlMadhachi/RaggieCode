#!/usr/bin/env python3
"""
Source-location lookup for frontend semantic entities.

Given a file path, line, and column, returns the most specific frontend
semantic entity at that location. Queries all frontend tables for entities
whose source range contains the position, returning the narrowest matches
sorted by range width.

This is the core building block for "go-to-definition", "hover", and
runtime element resolution (Phase 9) features.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class EntityMatch:
    """A single entity matched at a source location."""

    entity_type: str
    entity_id: int
    file_id: int
    file_path: str
    source_range: Dict[str, int]
    name: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "file_id": self.file_id,
            "file_path": self.file_path,
            "source_range": self.source_range,
            "name": self.name,
        }
        d.update(self.extra)
        return d


def _parse_range(raw: Optional[str]) -> Optional[Dict[str, int]]:
    """Parse a JSON source_range or location column value."""
    if not raw:
        return None
    try:
        r = json.loads(raw)
        if "start_line" not in r:
            return None
        return r
    except (json.JSONDecodeError, TypeError):
        return None


def _range_contains(r: Dict[str, int], line: int, column: int) -> bool:
    """Check if a 1-indexed line/column falls within the given source range."""
    sl = r.get("start_line", 0)
    sc = r.get("start_column", 0)
    el = r.get("end_line", 0)
    ec = r.get("end_column", 0)

    if line < sl or line > el:
        return False
    if line == sl and column < sc:
        return False
    if line == el and column >= ec:
        return False
    return True


def _range_width(r: Dict[str, int]) -> int:
    """Compute a rough width metric for sorting by narrowness."""
    sl = r.get("start_line", 0)
    sc = r.get("start_column", 0)
    el = r.get("end_line", 0)
    ec = r.get("end_column", 0)
    return (el - sl) * 10000 + (ec - sc)


# Table configurations: (table_name, entity_type_label, name_column, extra_columns)
# Ordered roughly from most specific (attributes/bindings) to broadest (components)
_FRONTEND_TABLES = [
    {
        "table": "frontend_events",
        "type": "event_binding",
        "name_col": "event_name",
        "extra_cols": ["handler_type", "handler_expression", "resolution_status", "element_id"],
    },
    {
        "table": "frontend_bindings",
        "type": "property_binding",
        "name_col": "binding_name",
        "extra_cols": ["binding_type", "binding_expression", "resolution_status", "element_id"],
    },
    {
        "table": "style_custom_properties",
        "type": "custom_property",
        "name_col": "name",
        "extra_cols": ["value", "scope_selector"],
    },
    {
        "table": "style_custom_property_usages",
        "type": "custom_property_usage",
        "name_col": "property_name",
        "extra_cols": ["resolved_property_id", "selector_id"],
    },
    {
        "table": "style_selectors",
        "type": "style_selector",
        "name_col": "selector_text",
        "extra_cols": ["selector_type", "normalized_selector", "is_scoped"],
    },
    {
        "table": "style_keyframes",
        "type": "keyframes",
        "name_col": "name",
        "extra_cols": [],
    },
    {
        "table": "style_imports",
        "type": "style_import",
        "name_col": "import_path",
        "extra_cols": ["is_external", "resolved_file_id"],
    },
    {
        "table": "markup_elements",
        "type": "markup_element",
        "name_col": "tag_name",
        "extra_cols": ["element_type", "element_id_attr", "component_id", "parent_element_id"],
    },
    {
        "table": "frontend_components",
        "type": "component",
        "name_col": "name",
        "extra_cols": ["framework", "is_exported", "impl_function_id", "impl_class_id"],
    },
    {
        "table": "frontend_diagnostics",
        "type": "diagnostic",
        "name_col": "diagnostic_type",
        "extra_cols": ["severity", "message"],
    },
]

# Backend tables that also have location data (for completeness)
_BACKEND_TABLES = [
    {
        "table": "functions",
        "type": "executable_symbol",
        "name_col": "name",
        "range_col": "location",
        "extra_cols": ["type", "parent_type"],
    },
    {
        "table": "classes",
        "type": "executable_symbol",
        "name_col": "name",
        "range_col": "location",
        "extra_cols": [],
    },
]


def lookup_entity_at_location(
    conn: sqlite3.Connection,
    file_path: str,
    line: int,
    column: int,
    include_backend: bool = False,
) -> List[EntityMatch]:
    """Find the most specific frontend semantic entity at a source location.

    Args:
        conn: SQLite connection to the index database.
        file_path: Project-relative path of the file to look up.
        line: 1-indexed line number.
        column: 0-indexed column number (consistent with tree-sitter columns).
        include_backend: If True, also search functions/classes tables.

    Returns:
        List of EntityMatch objects sorted by narrowest range first.
        Empty list if no entity contains the location or file is not found.
    """
    cursor = conn.cursor()

    # Resolve file_path to file_id
    cursor.execute("SELECT id, path FROM files WHERE path = ?", (file_path,))
    row = cursor.fetchone()
    if row is None:
        return []

    file_id, resolved_path = row[0], row[1]

    matches: List[EntityMatch] = []

    table_configs = list(_FRONTEND_TABLES)
    if include_backend:
        table_configs.extend(_BACKEND_TABLES)

    for cfg in table_configs:
        table = cfg["table"]
        range_col = cfg.get("range_col", "source_range")
        name_col = cfg["name_col"]
        extra_cols = cfg.get("extra_cols", [])
        entity_type = cfg["type"]

        cols = [range_col, name_col] + extra_cols
        col_list = ", ".join(cols)

        cursor.execute(
            f"SELECT id, {col_list} FROM {table} WHERE file_id = ?",
            (file_id,)
        )
        rows = cursor.fetchall()

        for row in rows:
            entity_id = row[0]
            raw_range = row[1]
            name = row[2]
            extra_values = row[3:]

            r = _parse_range(raw_range)
            if r is None:
                continue

            if _range_contains(r, line, column):
                extra = {}
                for i, col_name in enumerate(extra_cols):
                    extra[col_name] = extra_values[i]

                matches.append(EntityMatch(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    file_id=file_id,
                    file_path=resolved_path,
                    source_range=r,
                    name=name,
                    extra=extra,
                ))

    # Sort by narrowest range first
    matches.sort(key=lambda m: _range_width(m.source_range))

    return matches
