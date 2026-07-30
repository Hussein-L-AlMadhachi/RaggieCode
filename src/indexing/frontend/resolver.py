#!/usr/bin/env python3
"""
Cross-file resolution utilities for frontend semantic indexing.

Provides path normalization, alias resolution, and extension inference
for resolving file-path references (@import, <script src>, <link href>,
CSS module imports) during inline indexing.

These functions are called inline during _insert_frontend_data(), not
as a post-indexing pass.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional


# Extensions to try when a path has no extension
CANDIDATE_EXTENSIONS = [".tsx", ".ts", ".jsx", ".js", ".css", ".html", ".mjs", ".cjs"]


def normalize_import_path(import_path: str, source_file_path: str, root_dir: str,
                          aliases: Optional[Dict[str, str]] = None) -> str:
    """Resolve a relative or aliased import path to a normalized project-relative path.

    Args:
        import_path: The raw import path (e.g. "./Button", "../styles/global.css", "@/components/Card").
        source_file_path: Absolute path of the file making the import.
        root_dir: Absolute path of the project root directory.
        aliases: Optional pre-loaded path aliases from load_path_aliases(). If None, will load lazily.

    Returns:
        Normalized project-relative path (e.g. "src/components/Button.tsx").
        For external URLs (http://, https://, //), returns the original path unchanged.
    """
    # External URLs — return as-is
    if import_path.startswith(("http://", "https://", "//")):
        return import_path

    root = Path(root_dir).resolve()
    source_dir = Path(source_file_path).resolve().parent

    # Handle path aliases (@/, ~/, etc.)
    if aliases is None:
        aliases = load_path_aliases(root_dir)
    resolved = resolve_path_alias(import_path, aliases, root_dir)
    if resolved != import_path:
        # Alias was applied — resolve relative to root
        candidate = root / resolved
    elif import_path.startswith("/"):
        # Root-relative path
        candidate = root / import_path.lstrip("/")
    else:
        # Relative path — resolve against source file directory
        candidate = (source_dir / import_path).resolve()

    # Try to infer extension if the path doesn't exist as-is
    if not candidate.exists():
        candidate = infer_extension_path(candidate)

    # Return project-relative path
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        # Path is outside root — return best-effort normalized
        return str(candidate)


def infer_extension_path(base_path: Path) -> Path:
    """Try to find a file by appending common extensions to the path.

    Args:
        base_path: Path without an extension (or with one that doesn't exist).

    Returns:
        The first matching path with an extension, or the original path if none match.
    """
    # If the path already has an extension and exists, return it
    if base_path.suffix and base_path.exists():
        return base_path

    # If the path has an extension but doesn't exist, try index files in that directory
    if base_path.suffix:
        # e.g. "./components" might be a directory with index.tsx
        if base_path.with_suffix("").is_dir():
            for ext in CANDIDATE_EXTENSIONS:
                index_file = base_path.with_suffix("") / f"index{ext}"
                if index_file.exists():
                    return index_file
        return base_path

    # No extension — try each candidate
    for ext in CANDIDATE_EXTENSIONS:
        candidate = base_path.with_suffix(ext)
        if candidate.exists():
            return candidate

    # Try as a directory with index file
    if base_path.is_dir():
        for ext in CANDIDATE_EXTENSIONS:
            index_file = base_path / f"index{ext}"
            if index_file.exists():
                return index_file

    return base_path


def infer_extension(base_path: str) -> str:
    """Try to infer the file extension for a base path string.

    Args:
        base_path: Path string without an extension.

    Returns:
        The first extension (including dot) that matches an existing file,
        or the first candidate extension if none match.
    """
    p = Path(base_path)
    for ext in CANDIDATE_EXTENSIONS:
        candidate = p.with_suffix(ext)
        if candidate.exists():
            return ext
    return CANDIDATE_EXTENSIONS[0]


def load_path_aliases(root_dir: str) -> Dict[str, str]:
    """Load path aliases from tsconfig.json or jsconfig.json.

    Reads compilerOptions.paths from the config file and returns a mapping
    of alias patterns to resolved paths.

    Args:
        root_dir: Project root directory path.

    Returns:
        Dict mapping alias patterns (e.g. "@/*") to resolved path prefixes (e.g. "src/*").
        Empty dict if no config file found or no paths configured.
    """
    root = Path(root_dir)

    for config_name in ("tsconfig.json", "jsconfig.json"):
        config_path = root / config_name
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                paths = config.get("compilerOptions", {}).get("paths", {})
                if paths:
                    # Also get baseUrl for resolution
                    base_url = config.get("compilerOptions", {}).get("baseUrl", "")
                    result = {}
                    for alias, targets in paths.items():
                        if targets:
                            target = targets[0]
                            if base_url:
                                target = str(Path(base_url) / target)
                            result[alias] = target
                    return result
            except (json.JSONDecodeError, OSError):
                continue

    return {}


def resolve_path_alias(import_path: str, aliases: Dict[str, str], root_dir: str) -> str:
    """Apply alias mapping to an import path.

    Args:
        import_path: The raw import path (e.g. "@/components/Button").
        aliases: Alias mapping from load_path_aliases().
        root_dir: Project root directory path.

    Returns:
        Resolved path if alias matched, or the original import_path if no alias matched.
    """
    for alias_pattern, target_pattern in aliases.items():
        # Handle wildcard patterns like "@/*"
        if alias_pattern.endswith("/*"):
            prefix = alias_pattern[:-2]  # "@/"
            if import_path.startswith(prefix):
                suffix = import_path[len(prefix):]
                resolved = target_pattern.rstrip("*").rstrip("/") + "/" + suffix.lstrip("/")
                return resolved
        elif alias_pattern == import_path:
            return target_pattern
        else:
            # Exact prefix match without wildcard
            if import_path.startswith(alias_pattern + "/"):
                suffix = import_path[len(alias_pattern):]
                resolved = target_pattern + suffix
                return resolved

    return import_path


class FrontendResolver:
    """Post-indexing cross-file resolution pass.

    Called after all files have been indexed to refresh cross-file relationships
    that couldn't be resolved during inline insertion (e.g. because the target
    file hadn't been indexed yet, or was indexed in the wrong order).
    """

    def __init__(self, conn, root_dir):
        self.conn = conn
        self.root_dir = root_dir
        self.aliases = load_path_aliases(root_dir)

    def resolve_all(self):
        """Run all cross-file resolution passes.

        Resolves:
        1. render_relationships.child_component_id by name lookup
        2. style_imports.resolved_file_id by path lookup
        3. style_custom_property_usages.resolved_property_id by name lookup
        4. frontend_events.handler_symbol_id by expression lookup
        5. style_selector_matches — recompute from selectors and elements
        """
        self._resolve_render_relationships()
        self._resolve_style_imports()
        self._resolve_custom_property_usages()
        self._resolve_event_handlers()
        self._resolve_selector_matches()
        self.conn.commit()

    def _resolve_render_relationships(self):
        """Resolve render_relationships.child_component_id by looking up child_component_name."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT rr.id, rr.child_component_name FROM render_relationships rr "
            "WHERE rr.child_component_id IS NULL AND rr.child_component_name IS NOT NULL"
        )
        rows = cursor.fetchall()
        if not rows:
            return

        # Batch-load all component name -> id mappings
        cursor.execute("SELECT name, id FROM frontend_components")
        component_map = {}
        for name, comp_id in cursor.fetchall():
            if name not in component_map:
                component_map[name] = comp_id

        batch = []
        for row_id, child_name in rows:
            comp_id = component_map.get(child_name)
            if comp_id:
                batch.append((comp_id, row_id))
        if batch:
            cursor.executemany(
                "UPDATE render_relationships SET child_component_id = ? WHERE id = ?",
                batch
            )

    def _resolve_style_imports(self):
        """Resolve style_imports.resolved_file_id by looking up import paths."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT si.id, si.import_path, f.absolute_path "
            "FROM style_imports si "
            "JOIN files f ON si.file_id = f.id "
            "WHERE si.resolved_file_id IS NULL AND si.is_external = 0"
        )
        rows = cursor.fetchall()
        if not rows:
            return

        # Batch-load all file path -> id mappings
        cursor.execute("SELECT path, id FROM files")
        file_map = {path: fid for path, fid in cursor.fetchall()}

        batch = []
        for row_id, import_path, source_file_path in rows:
            resolved_path = normalize_import_path(
                import_path, source_file_path, self.root_dir, self.aliases
            )
            file_id = file_map.get(resolved_path)
            if file_id:
                batch.append((file_id, row_id))
        if batch:
            cursor.executemany(
                "UPDATE style_imports SET resolved_file_id = ? WHERE id = ?",
                batch
            )

    def _resolve_custom_property_usages(self):
        """Resolve style_custom_property_usages.resolved_property_id by name lookup."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, property_name FROM style_custom_property_usages "
            "WHERE resolved_property_id IS NULL"
        )
        rows = cursor.fetchall()
        if not rows:
            return

        # Batch-load all property name -> id mappings
        cursor.execute("SELECT name, id FROM style_custom_properties")
        prop_map = {}
        for name, prop_id in cursor.fetchall():
            if name not in prop_map:
                prop_map[name] = prop_id

        batch = []
        for row_id, prop_name in rows:
            prop_id = prop_map.get(prop_name)
            if prop_id:
                batch.append((prop_id, row_id))
        if batch:
            cursor.executemany(
                "UPDATE style_custom_property_usages SET resolved_property_id = ? WHERE id = ?",
                batch
            )

    def _resolve_event_handlers(self):
        """Resolve frontend_events.handler_symbol_id by looking up handler expressions."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT fe.id, fe.handler_expression, fe.file_id "
            "FROM frontend_events fe "
            "WHERE fe.handler_symbol_id IS NULL "
            "AND fe.handler_type = 'inline' "
            "AND fe.handler_expression IS NOT NULL"
        )
        rows = cursor.fetchall()
        if not rows:
            return

        # Group unresolved events by file_id for batch function lookups
        events_by_file = {}
        for row_id, handler_expr, file_id in rows:
            expr = handler_expr.strip()
            func_name = expr.rstrip("()").strip()
            if func_name and "(" not in func_name:
                events_by_file.setdefault(file_id, []).append((row_id, func_name))

        batch = []
        for file_id, events in events_by_file.items():
            func_names = set(fn for _, fn in events)
            placeholders = ','.join('?' * len(func_names))
            cursor.execute(
                f"SELECT name, id FROM functions WHERE file_id = ? AND name IN ({placeholders})",
                [file_id] + list(func_names)
            )
            func_map = {name: fid for name, fid in cursor.fetchall()}
            for row_id, func_name in events:
                func_id = func_map.get(func_name)
                if func_id:
                    batch.append((func_id, 'resolved', row_id))

        if batch:
            cursor.executemany(
                "UPDATE frontend_events SET handler_symbol_id = ?, resolution_status = ? WHERE id = ?",
                batch
            )

    def _resolve_selector_matches(self):
        """Recompute style_selector_matches from selectors and elements.

        Clears all existing matches and recomputes them by matching selectors
        against markup elements across all files.

        Optimized: pre-decodes element JSON once, groups selectors by type to
        reduce cross-product work, and batch-inserts results.
        """
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM style_selector_matches")

        cursor.execute(
            "SELECT ss.id, ss.selector_text, ss.selector_type "
            "FROM style_selectors ss"
        )
        selectors = cursor.fetchall()

        cursor.execute(
            "SELECT me.id, me.tag_name, me.element_id_attr, me.static_classes "
            "FROM markup_elements me "
            "WHERE me.element_type IN ('element', 'custom_component', 'native')"
        )
        elements = cursor.fetchall()

        # Pre-decode static_classes JSON once per element
        decoded_elements = []
        for elem_id, tag_name, elem_id_attr, static_classes in elements:
            classes = json.loads(static_classes) if static_classes else []
            decoded_elements.append((elem_id, tag_name, elem_id_attr, classes))

        # Group selectors by type for targeted matching
        selectors_by_type = {}
        for sel_id, sel_text, sel_type in selectors:
            selectors_by_type.setdefault(sel_type, []).append((sel_id, sel_text))

        # Build lookup indexes from elements
        elements_by_tag = {}
        elements_by_id_attr = {}
        elements_by_class = {}
        for elem_id, tag_name, elem_id_attr, classes in decoded_elements:
            tag_lower = tag_name.lower()
            elements_by_tag.setdefault(tag_lower, []).append(elem_id)
            if elem_id_attr:
                elements_by_id_attr.setdefault(elem_id_attr, []).append(elem_id)
            for cls in classes:
                elements_by_class.setdefault(cls, []).append(elem_id)

        batch = []
        # Match class selectors using class index
        for sel_id, sel_text in selectors_by_type.get("class", []):
            target_class = sel_text.lstrip(".")
            matched_ids = elements_by_class.get(target_class, [])
            for elem_id in matched_ids:
                batch.append((sel_id, elem_id, 'static', 'high'))

        # Match id selectors using id index
        for sel_id, sel_text in selectors_by_type.get("id", []):
            target_id = sel_text.lstrip("#")
            matched_ids = elements_by_id_attr.get(target_id, [])
            for elem_id in matched_ids:
                batch.append((sel_id, elem_id, 'static', 'high'))

        # Match tag selectors using tag index
        for sel_id, sel_text in selectors_by_type.get("tag", []):
            tag_lower = sel_text.lower()
            matched_ids = elements_by_tag.get(tag_lower, [])
            for elem_id in matched_ids:
                batch.append((sel_id, elem_id, 'static', 'high'))

        # Match compound selectors (still requires cross-product but only for compound selectors)
        compound_selectors = selectors_by_type.get("compound", [])
        if compound_selectors:
            for sel_id, sel_text in compound_selectors:
                for elem_id, tag_name, elem_id_attr, classes in decoded_elements:
                    if self._selector_matches_element(sel_text, "compound", tag_name, elem_id_attr, classes):
                        batch.append((sel_id, elem_id, 'static', 'high'))

        # Match any remaining selector types with full cross-product
        remaining_types = set(selectors_by_type.keys()) - {"class", "id", "tag", "compound"}
        if remaining_types:
            for sel_type in remaining_types:
                for sel_id, sel_text in selectors_by_type[sel_type]:
                    for elem_id, tag_name, elem_id_attr, classes in decoded_elements:
                        if self._selector_matches_element(sel_text, sel_type, tag_name, elem_id_attr, classes):
                            batch.append((sel_id, elem_id, 'static', 'high'))

        # Batch insert all matches
        if batch:
            cursor.executemany(
                "INSERT INTO style_selector_matches (selector_id, element_id, match_type, confidence) "
                "VALUES (?, ?, ?, ?)",
                batch
            )

    @staticmethod
    def _selector_matches_element(selector_text, selector_type, tag_name, elem_id_attr, static_classes):
        """Check if a CSS selector matches a markup element.

        static_classes can be a pre-decoded list or a JSON string.
        """
        if isinstance(static_classes, str):
            classes = json.loads(static_classes) if static_classes else []
        else:
            classes = static_classes

        if selector_type == "class":
            target_class = selector_text.lstrip(".")
            return target_class in classes
        elif selector_type == "id":
            target_id = selector_text.lstrip("#")
            return elem_id_attr == target_id
        elif selector_type == "tag":
            return tag_name.lower() == selector_text.lower()
        elif selector_type == "compound":
            parts = selector_text.replace(".", " .").replace("#", " #").split()
            for part in parts:
                if part.startswith("."):
                    if part[1:] not in classes:
                        return False
                elif part.startswith("#"):
                    if elem_id_attr != part[1:]:
                        return False
                else:
                    if tag_name.lower() != part.lower():
                        return False
            return True
        return False
