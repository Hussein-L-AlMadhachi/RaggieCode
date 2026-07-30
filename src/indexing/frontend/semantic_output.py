#!/usr/bin/env python3
"""
Structured semantic output formatters for frontend files (Phase 10).

Converts indexed frontend data into compressed, structured text for agent
consumption.  Instead of dumping raw HTML/CSS/JSX source, these formatters
produce a concise summary of components, markup, styles, events, and bindings.

Four public functions:
  - format_html_semantics(conn, file_id)       → HTML/JSX/TSX files
  - format_css_semantics(conn, file_id)        → CSS files
  - format_component_semantics(conn, component_id) → single component deep-dive
  - format_frontend_overview(conn, file_id)    → combined view for any frontend file
"""

import json
import sqlite3
from typing import Dict, List, Optional, Any


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _parse_json(raw: Optional[str]) -> Optional[Any]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _get_file(conn, file_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT id, path, language, content_hash FROM files WHERE id = ?",
        (file_id,)
    ).fetchone()
    return dict(row) if row else None


def _get_file_by_path(conn, file_path: str) -> Optional[Dict[str, Any]]:
    normalized = file_path[2:] if file_path.startswith("./") else file_path
    row = conn.execute(
        "SELECT id, path, language, content_hash FROM files WHERE path = ?",
        (normalized,)
    ).fetchone()
    if not row:
        import os
        filename = os.path.basename(normalized)
        row = conn.execute(
            "SELECT id, path, language, content_hash FROM files WHERE path LIKE ?",
            (f"%{filename}",)
        ).fetchone()
    return dict(row) if row else None


def _is_frontend_file(file_info: Dict[str, Any]) -> bool:
    lang = file_info.get("language", "")
    return lang in ("html", "css", "javascript", "tsx", "typescript")


def _is_html_like(file_info: Dict[str, Any]) -> bool:
    lang = file_info.get("language", "")
    path = file_info.get("path", "")
    return lang in ("html", "tsx", "javascript") or path.endswith((".html", ".htm", ".tsx", ".jsx"))


def _is_css(file_info: Dict[str, Any]) -> bool:
    lang = file_info.get("language", "")
    path = file_info.get("path", "")
    return lang == "css" or path.endswith(".css")


def _format_source_range(sr: Optional[Dict]) -> str:
    if not sr:
        return "?"
    return f"L{sr.get('start_line', '?')}"


def _format_classes(classes: Optional[List[str]]) -> str:
    if not classes:
        return ""
    return "." + ".".join(classes)


def _format_element_id(elem_id: Optional[str]) -> str:
    if not elem_id:
        return ""
    return f"#{elem_id}"


def _relationship_tag(status: str) -> str:
    """Tag for distinguishing relationship confidence."""
    if status == "resolved":
        return "exact"
    elif status == "conditional":
        return "conditional"
    elif status == "heuristic":
        return "heuristic"
    elif status == "unresolved":
        return "unresolved"
    return status


# ──────────────────────────────────────────────────────────────
# format_html_semantics
# ──────────────────────────────────────────────────────────────

def format_html_semantics(conn: sqlite3.Connection, file_id: int) -> str:
    """Structured semantic output for HTML/JSX/TSX files.

    Returns a concise summary of components, markup elements, events,
    bindings, and style relationships — not raw HTML.
    """
    file_info = _get_file(conn, file_id)
    if not file_info:
        return f"Error: File not found (id={file_id})"

    lines = [f'file "{file_info["path"]}" (frontend semantics):']

    # 1. Components
    components = conn.execute(
        """SELECT c.id, c.name, c.framework, c.is_exported, c.source_range,
                  c.impl_function_id, c.impl_class_id
           FROM frontend_components c
           WHERE c.file_id = ?
           ORDER BY c.id""",
        (file_id,)
    ).fetchall()

    if components:
        lines.append("  components:")
        for comp in components:
            exported = " (exported)" if comp["is_exported"] else ""
            sr = _parse_json(comp["source_range"])
            impl = ""
            if comp["impl_function_id"]:
                impl = f" → function#{comp['impl_function_id']}"
            elif comp["impl_class_id"]:
                impl = f" → class#{comp['impl_class_id']}"
            lines.append(f"    - {comp['name']} [{comp['framework']}]{exported} @ {_format_source_range(sr)}{impl}")

            # Rendered children
            children = conn.execute(
                """SELECT rr.child_component_id, rr.child_component_name, rr.render_type,
                          rr.controlling_expr, rr.child_element_id
                   FROM render_relationships rr
                   WHERE rr.parent_component_id = ?
                   ORDER BY rr.id""",
                (comp["id"],)
            ).fetchall()
            if children:
                lines.append("      renders:")
                for ch in children:
                    if ch["child_component_id"]:
                        tag = "exact"
                        cond = f" (conditional: {ch['controlling_expr']})" if ch["controlling_expr"] else ""
                        lines.append(f"        - component {ch['child_component_name']} [{tag}]{cond}")
                    elif ch["child_component_name"]:
                        tag = "unresolved"
                        lines.append(f"        - component {ch['child_component_name']} [{tag}] (unresolved)")
                    elif ch["child_element_id"]:
                        elem = conn.execute(
                            "SELECT tag_name FROM markup_elements WHERE id = ?",
                            (ch["child_element_id"],)
                        ).fetchone()
                        tag_name = elem["tag_name"] if elem else "?"
                        lines.append(f"        - element <{tag_name}> [exact]")

    # 2. Markup elements (summary)
    elements = conn.execute(
        """SELECT m.id, m.tag_name, m.element_type, m.element_id_attr,
                  m.static_classes, m.is_conditional, m.is_repeated,
                  m.source_range, m.component_id
           FROM markup_elements m
           WHERE m.file_id = ?
           ORDER BY m.id""",
        (file_id,)
    ).fetchall()

    if elements:
        lines.append("  markup:")
        for elem in elements:
            etype = elem["element_type"]
            if etype in ("text", "#text"):
                continue  # Skip text nodes in summary
            if etype == "expression":
                expr_tag = " (expression)"
                sr = _parse_json(elem["source_range"])
                lines.append(f"    - {{expr}}{expr_tag} @ {_format_source_range(sr)}")
                continue

            classes = _parse_json(elem["static_classes"]) or []
            class_str = _format_classes(classes)
            id_str = _format_element_id(elem["element_id_attr"])
            cond = " (conditional)" if elem["is_conditional"] else ""
            rep = " (repeated)" if elem["is_repeated"] else ""
            sr = _parse_json(elem["source_range"])
            comp_ref = f" in {elem['component_id']}" if elem["component_id"] else ""
            lines.append(f"    - <{elem['tag_name']}>{id_str}{class_str}{cond}{rep} @ {_format_source_range(sr)}{comp_ref}")

    # 3. Events
    events = conn.execute(
        """SELECT e.id, e.element_id, e.event_name, e.handler_type,
                  e.handler_expression, e.handler_symbol_id, e.resolution_status
           FROM frontend_events e
           WHERE e.file_id = ?
           ORDER BY e.id""",
        (file_id,)
    ).fetchall()

    if events:
        lines.append("  events:")
        for ev in events:
            elem = conn.execute(
                "SELECT tag_name, element_id_attr FROM markup_elements WHERE id = ?",
                (ev["element_id"],)
            ).fetchone()
            elem_desc = f"<{elem['tag_name']}>" if elem else "?"
            if elem and elem["element_id_attr"]:
                elem_desc += f"#{elem['element_id_attr']}"
            handler = ev["handler_expression"] or "?"
            sym = f" → function#{ev['handler_symbol_id']}" if ev["handler_symbol_id"] else ""
            tag = _relationship_tag(ev["resolution_status"])
            lines.append(f"    - {ev['event_name']} on {elem_desc} → {handler}{sym} [{tag}]")

    # 4. Bindings
    bindings = conn.execute(
        """SELECT b.id, b.element_id, b.binding_type, b.binding_name,
                  b.binding_expression, b.resolution_status
           FROM frontend_bindings b
           WHERE b.file_id = ?
           ORDER BY b.id""",
        (file_id,)
    ).fetchall()

    if bindings:
        lines.append("  bindings:")
        for b in bindings:
            elem = conn.execute(
                "SELECT tag_name, element_id_attr FROM markup_elements WHERE id = ?",
                (b["element_id"],)
            ).fetchone()
            elem_desc = f"<{elem['tag_name']}>" if elem else "?"
            if elem and elem["element_id_attr"]:
                elem_desc += f"#{elem['element_id_attr']}"
            tag = _relationship_tag(b["resolution_status"])
            lines.append(f"    - {b['binding_type']}:{b['binding_name']} on {elem_desc} = {b['binding_expression']} [{tag}]")

    # 5. Style relationships (selectors defined in this file)
    selectors = conn.execute(
        """SELECT s.id, s.selector_text, s.selector_type, s.is_scoped
           FROM style_selectors s
           WHERE s.file_id = ?
           ORDER BY s.id""",
        (file_id,)
    ).fetchall()

    if selectors:
        lines.append("  styles defined:")
        for sel in selectors:
            scoped = " (scoped)" if sel["is_scoped"] else ""
            lines.append(f"    - {sel['selector_text']} [{sel['selector_type']}]{scoped}")

    # 6. Stylesheet imports
    imports = conn.execute(
        """SELECT si.import_path, si.is_external, si.resolved_file_id
           FROM style_imports si
           WHERE si.file_id = ?
           ORDER BY si.id""",
        (file_id,)
    ).fetchall()

    if imports:
        lines.append("  imports:")
        for imp in imports:
            if imp["is_external"]:
                tag = "external"
            elif imp["resolved_file_id"]:
                tag = "resolved"
            else:
                tag = "unresolved"
            lines.append(f"    - {imp['import_path']} [{tag}]")

    # 7. Embedded scripts
    scripts = conn.execute(
        """SELECT DISTINCT f2.id, f2.path
           FROM files f2
           WHERE f2.path LIKE '%script%' AND f2.id != ?
           LIMIT 10""",
        (file_id,)
    ).fetchall()

    # Check for inline scripts via diagnostics or other markers
    # This is a simplified approach — in practice inline scripts are parsed
    # as part of the HTML file's functions
    funcs = conn.execute(
        "SELECT id, name, type FROM functions WHERE file_id = ? ORDER BY id",
        (file_id,)
    ).fetchall()
    if funcs:
        lines.append("  embedded symbols:")
        for fn in funcs:
            lines.append(f"    - {fn['type']} {fn['name']}")

    if len(lines) == 1:
        lines.append("  (no frontend semantic entities found)")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# format_css_semantics
# ──────────────────────────────────────────────────────────────

def format_css_semantics(conn: sqlite3.Connection, file_id: int) -> str:
    """Structured semantic output for CSS files.

    Returns selectors, custom properties, keyframes, imports, and
    selector usages — not raw CSS.
    """
    file_info = _get_file(conn, file_id)
    if not file_info:
        return f"Error: File not found (id={file_id})"

    lines = [f'file "{file_info["path"]}" (CSS semantics):']

    # 1. Selectors
    selectors = conn.execute(
        """SELECT s.id, s.selector_text, s.selector_type, s.is_scoped,
                  s.component_id, s.source_range
           FROM style_selectors s
           WHERE s.file_id = ?
           ORDER BY s.id""",
        (file_id,)
    ).fetchall()

    if selectors:
        lines.append("  selectors:")
        for sel in selectors:
            scoped = " (scoped)" if sel["is_scoped"] else ""
            comp = f" → component#{sel['component_id']}" if sel["component_id"] else ""
            sr = _parse_json(sel["source_range"])
            lines.append(f"    - {sel['selector_text']} [{sel['selector_type']}]{scoped} @ {_format_source_range(sr)}{comp}")

            # Selector usages (which elements match)
            matches = conn.execute(
                """SELECT sm.element_id, sm.match_type, sm.confidence,
                          m.tag_name, m.element_id_attr, m.static_classes
                   FROM style_selector_matches sm
                   JOIN markup_elements m ON sm.element_id = m.id
                   WHERE sm.selector_id = ?
                   ORDER BY sm.id""",
                (sel["id"],)
            ).fetchall()
            if matches:
                for m in matches:
                    classes = _parse_json(m["static_classes"]) or []
                    class_str = _format_classes(classes)
                    id_str = _format_element_id(m["element_id_attr"])
                    tag = _relationship_tag(m["match_type"])
                    conf = ""
                    if m["confidence"]:
                        try:
                            conf = f" (conf={m['confidence']})" if float(m["confidence"]) < 1.0 else ""
                        except (ValueError, TypeError):
                            pass
                    lines.append(f"      matches: <{m['tag_name']}>{id_str}{class_str} [{tag}]{conf}")

    # 2. Custom properties
    custom_props = conn.execute(
        """SELECT cp.id, cp.name, cp.value, cp.scope_selector, cp.source_range
           FROM style_custom_properties cp
           WHERE cp.file_id = ?
           ORDER BY cp.id""",
        (file_id,)
    ).fetchall()

    if custom_props:
        lines.append("  custom properties:")
        for cp in custom_props:
            scope = f" (scope: {cp['scope_selector']})" if cp["scope_selector"] else ""
            sr = _parse_json(cp["source_range"])
            lines.append(f"    - {cp['name']}: {cp['value']}{scope} @ {_format_source_range(sr)}")

    # 3. Custom property usages
    prop_usages = conn.execute(
        """SELECT cpu.id, cpu.property_name, cpu.resolved_property_id, cpu.selector_id
           FROM style_custom_property_usages cpu
           WHERE cpu.file_id = ?
           ORDER BY cpu.id""",
        (file_id,)
    ).fetchall()

    if prop_usages:
        lines.append("  custom property usages:")
        for pu in prop_usages:
            if pu["resolved_property_id"]:
                tag = "resolved"
                ref = f" → property#{pu['resolved_property_id']}"
            else:
                tag = "unresolved"
                ref = ""
            sel_ref = f" in selector#{pu['selector_id']}" if pu["selector_id"] else ""
            lines.append(f"    - var({pu['property_name']}) [{tag}]{ref}{sel_ref}")

    # 4. Keyframes
    keyframes = conn.execute(
        """SELECT k.id, k.name, k.source_range
           FROM style_keyframes k
           WHERE k.file_id = ?
           ORDER BY k.id""",
        (file_id,)
    ).fetchall()

    if keyframes:
        lines.append("  keyframes:")
        for kf in keyframes:
            sr = _parse_json(kf["source_range"])
            lines.append(f"    - @keyframes {kf['name']} @ {_format_source_range(sr)}")

    # 5. Imports
    imports = conn.execute(
        """SELECT si.import_path, si.is_external, si.resolved_file_id
           FROM style_imports si
           WHERE si.file_id = ?
           ORDER BY si.id""",
        (file_id,)
    ).fetchall()

    if imports:
        lines.append("  imports:")
        for imp in imports:
            if imp["is_external"]:
                tag = "external"
            elif imp["resolved_file_id"]:
                tag = "resolved"
            else:
                tag = "unresolved"
            lines.append(f"    - @import {imp['import_path']} [{tag}]")

    # 6. Component associations
    comp_associations = conn.execute(
        """SELECT DISTINCT s.component_id, c.name
           FROM style_selectors s
           JOIN frontend_components c ON s.component_id = c.id
           WHERE s.file_id = ? AND s.component_id IS NOT NULL
           ORDER BY c.name""",
        (file_id,)
    ).fetchall()

    if comp_associations:
        lines.append("  component associations:")
        for ca in comp_associations:
            lines.append(f"    - {ca['name']} (component#{ca['component_id']})")

    if len(lines) == 1:
        lines.append("  (no CSS semantic entities found)")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# format_component_semantics
# ──────────────────────────────────────────────────────────────

def format_component_semantics(conn: sqlite3.Connection, component_id: int) -> str:
    """Deep-dive semantic output for a single component.

    Returns component info, rendered children, markup tree summary,
    events, bindings, styles, and rendering parents.
    """
    comp = conn.execute(
        """SELECT c.*, f.path as file_path
           FROM frontend_components c
           JOIN files f ON c.file_id = f.id
           WHERE c.id = ?""",
        (component_id,)
    ).fetchone()

    if not comp:
        return f"Error: Component not found (id={component_id})"

    sr = _parse_json(comp["source_range"])
    exported = " (exported)" if comp["is_exported"] else ""
    impl = ""
    if comp["impl_function_id"]:
        impl = f" → function#{comp['impl_function_id']}"
    elif comp["impl_class_id"]:
        impl = f" → class#{comp['impl_class_id']}"

    lines = [
        f'component "{comp["name"]}" [{comp["framework"]}]{exported} @ {comp["file_path"]}:{_format_source_range(sr)}{impl}',
    ]

    # 1. Rendered children
    children = conn.execute(
        """SELECT rr.child_component_id, rr.child_component_name, rr.render_type,
                  rr.controlling_expr, rr.child_element_id
           FROM render_relationships rr
           WHERE rr.parent_component_id = ?
           ORDER BY rr.id""",
        (component_id,)
    ).fetchall()

    if children:
        lines.append("  renders:")
        for ch in children:
            if ch["child_component_id"]:
                tag = "exact"
                cond = f" (conditional: {ch['controlling_expr']})" if ch["controlling_expr"] else ""
                lines.append(f"    - component {ch['child_component_name']} [{tag}]{cond}")
            elif ch["child_component_name"]:
                lines.append(f"    - component {ch['child_component_name']} [unresolved] (unresolved reference)")
            elif ch["child_element_id"]:
                elem = conn.execute(
                    "SELECT tag_name FROM markup_elements WHERE id = ?",
                    (ch["child_element_id"],)
                ).fetchone()
                tag_name = elem["tag_name"] if elem else "?"
                lines.append(f"    - element <{tag_name}> [exact]")

    # 2. Markup tree summary
    elements = conn.execute(
        """SELECT m.id, m.tag_name, m.element_type, m.element_id_attr,
                  m.static_classes, m.is_conditional, m.is_repeated,
                  m.source_range, m.parent_element_id
           FROM markup_elements m
           WHERE m.component_id = ?
           ORDER BY m.id""",
        (component_id,)
    ).fetchall()

    if elements:
        lines.append("  markup tree:")
        # Build a simple indented tree
        by_id = {e["id"]: e for e in elements}
        roots = [e for e in elements if e["parent_element_id"] is None or e["parent_element_id"] not in by_id]

        def _render_element(elem, depth=1):
            indent = "    " * depth
            etype = elem["element_type"]
            if etype in ("text", "#text"):
                return
            if etype == "expression":
                sr = _parse_json(elem["source_range"])
                lines.append(f"{indent}{{expr}} @ {_format_source_range(sr)}")
                return

            classes = _parse_json(elem["static_classes"]) or []
            class_str = _format_classes(classes)
            id_str = _format_element_id(elem["element_id_attr"])
            cond = " (conditional)" if elem["is_conditional"] else ""
            rep = " (repeated)" if elem["is_repeated"] else ""
            sr = _parse_json(elem["source_range"])
            lines.append(f"{indent}<{elem['tag_name']}>{id_str}{class_str}{cond}{rep} @ {_format_source_range(sr)}")

            # Children
            children = [e for e in elements if e["parent_element_id"] == elem["id"]]
            for child in children:
                _render_element(child, depth + 1)

        for root in roots:
            _render_element(root)

    # 3. Events
    events = conn.execute(
        """SELECT e.id, e.element_id, e.event_name, e.handler_type,
                  e.handler_expression, e.handler_symbol_id, e.resolution_status
           FROM frontend_events e
           WHERE e.element_id IN (
               SELECT id FROM markup_elements WHERE component_id = ?
           )
           ORDER BY e.id""",
        (component_id,)
    ).fetchall()

    if events:
        lines.append("  events:")
        for ev in events:
            elem = conn.execute(
                "SELECT tag_name, element_id_attr FROM markup_elements WHERE id = ?",
                (ev["element_id"],)
            ).fetchone()
            elem_desc = f"<{elem['tag_name']}>" if elem else "?"
            if elem and elem["element_id_attr"]:
                elem_desc += f"#{elem['element_id_attr']}"
            handler = ev["handler_expression"] or "?"
            sym = f" → function#{ev['handler_symbol_id']}" if ev["handler_symbol_id"] else ""
            tag = _relationship_tag(ev["resolution_status"])
            lines.append(f"    - {ev['event_name']} on {elem_desc} → {handler}{sym} [{tag}]")

    # 4. Bindings
    bindings = conn.execute(
        """SELECT b.id, b.element_id, b.binding_type, b.binding_name,
                  b.binding_expression, b.resolution_status
           FROM frontend_bindings b
           WHERE b.element_id IN (
               SELECT id FROM markup_elements WHERE component_id = ?
           )
           ORDER BY b.id""",
        (component_id,)
    ).fetchall()

    if bindings:
        lines.append("  bindings:")
        for b in bindings:
            elem = conn.execute(
                "SELECT tag_name, element_id_attr FROM markup_elements WHERE id = ?",
                (b["element_id"],)
            ).fetchone()
            elem_desc = f"<{elem['tag_name']}>" if elem else "?"
            if elem and elem["element_id_attr"]:
                elem_desc += f"#{elem['element_id_attr']}"
            tag = _relationship_tag(b["resolution_status"])
            lines.append(f"    - {b['binding_type']}:{b['binding_name']} on {elem_desc} = {b['binding_expression']} [{tag}]")

    # 5. Styles
    selectors = conn.execute(
        """SELECT s.id, s.selector_text, s.selector_type, s.is_scoped
           FROM style_selectors s
           WHERE s.component_id = ?
           ORDER BY s.id""",
        (component_id,)
    ).fetchall()

    if selectors:
        lines.append("  styles:")
        for sel in selectors:
            scoped = " (scoped)" if sel["is_scoped"] else ""
            lines.append(f"    - {sel['selector_text']} [{sel['selector_type']}]{scoped}")

    # 6. Rendering parents
    parents = conn.execute(
        """SELECT rr.parent_component_id, c.name
           FROM render_relationships rr
           JOIN frontend_components c ON rr.parent_component_id = c.id
           WHERE rr.child_component_id = ?
           ORDER BY c.name""",
        (component_id,)
    ).fetchall()

    if parents:
        lines.append("  rendered by:")
        for p in parents:
            lines.append(f"    - {p['name']} (component#{p['parent_component_id']})")

    if len(lines) == 1:
        lines.append("  (no semantic data found for this component)")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# format_frontend_overview
# ──────────────────────────────────────────────────────────────

def format_frontend_overview(conn: sqlite3.Connection, file_id: int) -> str:
    """Combined semantic view for any frontend file.

    Dispatches to format_html_semantics or format_css_semantics based on
    file type, then appends per-component deep-dives.
    """
    file_info = _get_file(conn, file_id)
    if not file_info:
        return f"Error: File not found (id={file_id})"

    if _is_css(file_info):
        base = format_css_semantics(conn, file_id)
    else:
        base = format_html_semantics(conn, file_id)

    # Append component deep-dives
    components = conn.execute(
        "SELECT id FROM frontend_components WHERE file_id = ? ORDER BY id",
        (file_id,)
    ).fetchall()

    if components and len(components) > 1:
        sections = [base, "\n## Component Details"]
        for comp in components:
            sections.append("\n" + format_component_semantics(conn, comp["id"]))
        return "\n".join(sections)

    return base


# ──────────────────────────────────────────────────────────────
# Dispatch by file path (for integration with explore_code_structure)
# ──────────────────────────────────────────────────────────────

def format_file_semantics(conn: sqlite3.Connection, file_path: str) -> Optional[str]:
    """Format semantic output for a file by path.

    Returns None if the file is not a frontend file or not found.
    """
    file_info = _get_file_by_path(conn, file_path)
    if not file_info:
        return None

    if not _is_frontend_file(file_info):
        return None

    return format_frontend_overview(conn, file_info["id"])
