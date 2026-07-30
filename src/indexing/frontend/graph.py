#!/usr/bin/env python3
"""
Frontend graph traversal (Phase 8).

Provides depth-limited, cycle-safe traversal of frontend semantic
relationships stored in the index database:

- traverse_render_graph: component → rendered children / parents
- traverse_markup_tree: element → child / parent elements
- traverse_style_graph: selector ↔ matching elements
- traverse_event_graph: element → event handlers → handler symbols
- traverse_binding_graph: element → bindings → referenced expressions
- traverse_component_to_code: component → implementation function/class → call tree
- traverse_full_frontend: combined traversal of all the above
"""

import json
import sqlite3
from collections import deque
from typing import Dict, List, Optional, Any, Set


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _get_component(conn, component_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT c.*, f.path as file_path FROM frontend_components c "
        "JOIN files f ON c.file_id = f.id WHERE c.id = ?",
        (component_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def _get_component_by_name(conn, name: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT c.*, f.path as file_path FROM frontend_components c "
        "JOIN files f ON c.file_id = f.id WHERE c.name = ? LIMIT 1",
        (name,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def _get_element(conn, element_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT m.*, f.path as file_path FROM markup_elements m "
        "JOIN files f ON m.file_id = f.id WHERE m.id = ?",
        (element_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def _get_selector(conn, selector_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT s.*, f.path as file_path FROM style_selectors s "
        "JOIN files f ON s.file_id = f.id WHERE s.id = ?",
        (selector_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


# ──────────────────────────────────────────────────────────────
# 1. Render graph traversal
# ──────────────────────────────────────────────────────────────

def traverse_render_graph(
    conn: sqlite3.Connection,
    component_id: int,
    direction: str = "children",
    max_depth: int = 10,
) -> Dict[str, Any]:
    """Traverse the component render graph.

    Args:
        conn: SQLite connection.
        component_id: ID of the starting frontend_components row.
        direction: "children" (component → rendered children) or
                   "parents" (component → rendering parents).
        max_depth: Maximum traversal depth.

    Returns:
        Dict with component info and a "nodes" list (BFS order, depth-limited,
        cycle-detected). Each node has: id, name, render_type, depth, cycle,
        file_path, children.
    """
    comp = _get_component(conn, component_id)
    if comp is None:
        return {"error": f"Component not found: id={component_id}"}

    root = {
        "id": component_id,
        "name": comp["name"],
        "render_type": "root",
        "source_range": json.loads(comp["source_range"]) if comp.get("source_range") else None,
        "depth": 0,
        "cycle": False,
        "file_path": comp["file_path"],
        "children": [],
    }

    nodes: Dict[int, Dict[str, Any]] = {component_id: root}
    queue: deque = deque()
    queue.append((component_id, root, 0, frozenset([component_id])))

    while queue:
        comp_id, parent_node, depth, ancestors = queue.popleft()
        if depth >= max_depth:
            continue

        if direction == "children":
            rows = conn.execute(
                """SELECT rr.child_component_id, rr.child_component_name,
                          rr.child_element_id, rr.render_type, rr.controlling_expr,
                          c.name as resolved_name, c.source_range as child_source_range, f.path as file_path
                   FROM render_relationships rr
                   LEFT JOIN frontend_components c ON rr.child_component_id = c.id
                   LEFT JOIN files f ON c.file_id = f.id
                   WHERE rr.parent_component_id = ?
                   ORDER BY rr.id""",
                (comp_id,)
            ).fetchall()
        else:  # parents
            rows = conn.execute(
                """SELECT rr.parent_component_id as child_component_id,
                          c.name as child_component_name,
                          NULL as child_element_id,
                          rr.render_type, rr.controlling_expr,
                          c.name as resolved_name, c.source_range as child_source_range, f.path as file_path
                   FROM render_relationships rr
                   JOIN frontend_components c ON rr.parent_component_id = c.id
                   JOIN files f ON c.file_id = f.id
                   WHERE rr.child_component_id = ?
                   ORDER BY rr.id""",
                (comp_id,)
            ).fetchall()

        for row in rows:
            child_id = row["child_component_id"]
            child_name = row["resolved_name"] or row["child_component_name"] or "unknown"
            render_type = row["render_type"]

            if child_id is None:
                # Unresolved reference — add as a leaf
                parent_node["children"].append({
                    "id": None,
                    "name": child_name,
                    "render_type": render_type,
                    "controlling_expr": row["controlling_expr"],
                    "source_range": None,
                    "depth": depth + 1,
                    "cycle": False,
                    "file_path": None,
                    "children": [],
                    "unresolved": True,
                })
                continue

            is_cycle = child_id in ancestors
            if child_id not in nodes:
                node = {
                    "id": child_id,
                    "name": child_name,
                    "render_type": render_type,
                    "controlling_expr": row["controlling_expr"],
                    "source_range": json.loads(row["child_source_range"]) if row["child_source_range"] else None,
                    "depth": depth + 1,
                    "cycle": is_cycle,
                    "file_path": row["file_path"],
                    "children": [],
                }
                nodes[child_id] = node
                parent_node["children"].append(node)
                if not is_cycle:
                    queue.append((child_id, node, depth + 1, ancestors | {child_id}))
            else:
                # Already visited — add as reference
                parent_node["children"].append({
                    "id": child_id,
                    "name": child_name,
                    "render_type": render_type,
                    "controlling_expr": row["controlling_expr"],
                    "source_range": json.loads(row["child_source_range"]) if row["child_source_range"] else None,
                    "depth": depth + 1,
                    "cycle": is_cycle,
                    "file_path": row["file_path"],
                    "children": [],
                    "already_visited": True,
                })

    return root


# ──────────────────────────────────────────────────────────────
# 2. Markup tree traversal
# ──────────────────────────────────────────────────────────────

def traverse_markup_tree(
    conn: sqlite3.Connection,
    element_id: int,
    direction: str = "children",
    max_depth: int = 10,
) -> Dict[str, Any]:
    """Traverse the markup element tree via parent_element_id.

    Args:
        conn: SQLite connection.
        element_id: ID of the starting markup_elements row.
        direction: "children" or "parents".
        max_depth: Maximum traversal depth.

    Returns:
        Dict with element info and nested "children" or "parents" list.
    """
    elem = _get_element(conn, element_id)
    if elem is None:
        return {"error": f"Element not found: id={element_id}"}

    root = {
        "id": element_id,
        "tag_name": elem["tag_name"],
        "element_type": elem["element_type"],
        "static_classes": json.loads(elem["static_classes"]) if elem.get("static_classes") else [],
        "element_id_attr": elem.get("element_id_attr"),
        "is_conditional": bool(elem["is_conditional"]) if elem.get("is_conditional") else False,
        "is_repeated": bool(elem["is_repeated"]) if elem.get("is_repeated") else False,
        "source_range": json.loads(elem["source_range"]) if elem.get("source_range") else None,
        "depth": 0,
        "cycle": False,
        "file_path": elem["file_path"],
        "children": [],
    }

    nodes: Dict[int, Dict[str, Any]] = {element_id: root}
    queue: deque = deque()
    queue.append((element_id, root, 0, frozenset([element_id])))

    while queue:
        eid, parent_node, depth, ancestors = queue.popleft()
        if depth >= max_depth:
            continue

        if direction == "children":
            rows = conn.execute(
                """SELECT m.id, m.tag_name, m.element_type, m.static_classes,
                          m.element_id_attr, m.is_conditional, m.is_repeated,
                          f.path as file_path
                   FROM markup_elements m
                   JOIN files f ON m.file_id = f.id
                   WHERE m.parent_element_id = ?
                   ORDER BY m.id""",
                (eid,)
            ).fetchall()
        else:  # parents
            rows = conn.execute(
                """SELECT m.id, m.tag_name, m.element_type, m.static_classes,
                          m.element_id_attr, m.is_conditional, m.is_repeated,
                          f.path as file_path
                   FROM markup_elements m
                   JOIN files f ON m.file_id = f.id
                   WHERE m.id = (SELECT parent_element_id FROM markup_elements WHERE id = ?)
                   LIMIT 1""",
                (eid,)
            ).fetchall()

        for row in rows:
            child_eid = row["id"]
            is_cycle = child_eid in ancestors

            if child_eid not in nodes:
                node = {
                    "id": child_eid,
                    "tag_name": row["tag_name"],
                    "element_type": row["element_type"],
                    "static_classes": json.loads(row["static_classes"]) if row["static_classes"] else [],
                    "element_id_attr": row["element_id_attr"],
                    "is_conditional": bool(row["is_conditional"]) if row["is_conditional"] else False,
                    "is_repeated": bool(row["is_repeated"]) if row["is_repeated"] else False,
                    "depth": depth + 1,
                    "cycle": is_cycle,
                    "file_path": row["file_path"],
                    "children": [],
                }
                nodes[child_eid] = node
                parent_node["children"].append(node)
                if not is_cycle:
                    queue.append((child_eid, node, depth + 1, ancestors | {child_eid}))
            else:
                parent_node["children"].append({
                    "id": child_eid,
                    "tag_name": row["tag_name"],
                    "element_type": row["element_type"],
                    "static_classes": json.loads(row["static_classes"]) if row["static_classes"] else [],
                    "element_id_attr": row["element_id_attr"],
                    "is_conditional": bool(row["is_conditional"]) if row["is_conditional"] else False,
                    "is_repeated": bool(row["is_repeated"]) if row["is_repeated"] else False,
                    "depth": depth + 1,
                    "cycle": is_cycle,
                    "file_path": row["file_path"],
                    "children": [],
                    "already_visited": True,
                })

    return root


# ──────────────────────────────────────────────────────────────
# 3. Style graph traversal
# ──────────────────────────────────────────────────────────────

def traverse_style_graph(
    conn: sqlite3.Connection,
    selector_id: int,
    direction: str = "using_elements",
    max_depth: int = 10,
) -> Dict[str, Any]:
    """Traverse the style selector ↔ element graph.

    Args:
        conn: SQLite connection.
        selector_id: ID of the starting style_selectors row.
        direction: "using_elements" (selector → matching elements) or
                   "to_definition" (element → candidate selectors).
        max_depth: Maximum traversal depth (usually 1-2 levels).

    Returns:
        Dict with selector/element info and matched entities.
    """
    if direction == "using_elements":
        sel = _get_selector(conn, selector_id)
        if sel is None:
            return {"error": f"Selector not found: id={selector_id}"}

        matches = conn.execute(
            """SELECT m.id, m.tag_name, m.element_type, m.static_classes,
                      m.element_id_attr, m.source_range, f.path as file_path,
                      sm.match_type, sm.confidence
               FROM style_selector_matches sm
               JOIN markup_elements m ON sm.element_id = m.id
               JOIN files f ON m.file_id = f.id
               WHERE sm.selector_id = ?
               ORDER BY m.id""",
            (selector_id,)
        ).fetchall()

        elements = []
        for row in matches:
            elements.append({
                "id": row["id"],
                "tag_name": row["tag_name"],
                "element_type": row["element_type"],
                "static_classes": json.loads(row["static_classes"]) if row["static_classes"] else [],
                "element_id_attr": row["element_id_attr"],
                "source_range": json.loads(row["source_range"]) if row["source_range"] else None,
                "file_path": row["file_path"],
                "match_type": row["match_type"],
                "confidence": row["confidence"],
            })

        return {
            "selector_id": selector_id,
            "selector_text": sel["selector_text"],
            "selector_type": sel["selector_type"],
            "file_path": sel["file_path"],
            "using_elements": elements,
        }

    else:  # to_definition — given an element, find candidate selectors
        # selector_id is actually element_id in this direction
        element_id = selector_id
        elem = _get_element(conn, element_id)
        if elem is None:
            return {"error": f"Element not found: id={element_id}"}

        matches = conn.execute(
            """SELECT s.id, s.selector_text, s.selector_type, s.normalized_selector,
                      s.is_scoped, f.path as file_path,
                      sm.match_type, sm.confidence
               FROM style_selector_matches sm
               JOIN style_selectors s ON sm.selector_id = s.id
               JOIN files f ON s.file_id = f.id
               WHERE sm.element_id = ?
               ORDER BY s.id""",
            (element_id,)
        ).fetchall()

        selectors = []
        for row in matches:
            selectors.append({
                "id": row["id"],
                "selector_text": row["selector_text"],
                "selector_type": row["selector_type"],
                "normalized_selector": row["normalized_selector"],
                "is_scoped": bool(row["is_scoped"]),
                "file_path": row["file_path"],
                "match_type": row["match_type"],
                "confidence": row["confidence"],
            })

        return {
            "element_id": element_id,
            "tag_name": elem["tag_name"],
            "static_classes": json.loads(elem["static_classes"]) if elem["static_classes"] else [],
            "source_range": json.loads(elem["source_range"]) if elem.get("source_range") else None,
            "file_path": elem["file_path"],
            "candidate_selectors": selectors,
        }


# ──────────────────────────────────────────────────────────────
# 4. Event graph traversal
# ──────────────────────────────────────────────────────────────

def traverse_event_graph(
    conn: sqlite3.Connection,
    element_id: int,
) -> Dict[str, Any]:
    """Traverse element → event handlers → handler symbols.

    Args:
        conn: SQLite connection.
        element_id: ID of the markup_elements row.

    Returns:
        Dict with element info and list of events with handler symbol details.
    """
    elem = _get_element(conn, element_id)
    if elem is None:
        return {"error": f"Element not found: id={element_id}"}

    events = conn.execute(
        """SELECT e.id, e.event_name, e.handler_type, e.handler_expression,
                  e.resolution_status, e.handler_symbol_id, e.source_range,
                  fn.name as handler_symbol_name,
                  fn.type as handler_symbol_type,
                  f.path as handler_symbol_file
           FROM frontend_events e
           LEFT JOIN functions fn ON e.handler_symbol_id = fn.id
           LEFT JOIN files f ON fn.file_id = f.id
           WHERE e.element_id = ?
           ORDER BY e.id""",
        (element_id,)
    ).fetchall()

    event_list = []
    for row in events:
        ev = {
            "id": row["id"],
            "event_name": row["event_name"],
            "handler_type": row["handler_type"],
            "handler_expression": row["handler_expression"],
            "resolution_status": row["resolution_status"],
            "source_range": json.loads(row["source_range"]) if row["source_range"] else None,
        }
        if row["handler_symbol_id"]:
            ev["handler_symbol"] = {
                "id": row["handler_symbol_id"],
                "name": row["handler_symbol_name"],
                "type": row["handler_symbol_type"],
                "file_path": row["handler_symbol_file"],
            }
        else:
            ev["handler_symbol"] = None
        event_list.append(ev)

    return {
        "element_id": element_id,
        "tag_name": elem["tag_name"],
        "source_range": json.loads(elem["source_range"]) if elem.get("source_range") else None,
        "file_path": elem["file_path"],
        "events": event_list,
    }


# ──────────────────────────────────────────────────────────────
# 5. Binding graph traversal
# ──────────────────────────────────────────────────────────────

def traverse_binding_graph(
    conn: sqlite3.Connection,
    element_id: int,
) -> Dict[str, Any]:
    """Traverse element → bindings → referenced state/expressions.

    Args:
        conn: SQLite connection.
        element_id: ID of the markup_elements row.

    Returns:
        Dict with element info and list of bindings.
    """
    elem = _get_element(conn, element_id)
    if elem is None:
        return {"error": f"Element not found: id={element_id}"}

    bindings = conn.execute(
        """SELECT b.id, b.binding_type, b.binding_name, b.binding_expression,
                  b.resolution_status, b.source_range
           FROM frontend_bindings b
           WHERE b.element_id = ?
           ORDER BY b.id""",
        (element_id,)
    ).fetchall()

    binding_list = []
    for row in bindings:
        binding_list.append({
            "id": row["id"],
            "binding_type": row["binding_type"],
            "binding_name": row["binding_name"],
            "binding_expression": row["binding_expression"],
            "resolution_status": row["resolution_status"],
            "source_range": json.loads(row["source_range"]) if row["source_range"] else None,
        })

    return {
        "element_id": element_id,
        "tag_name": elem["tag_name"],
        "source_range": json.loads(elem["source_range"]) if elem.get("source_range") else None,
        "file_path": elem["file_path"],
        "bindings": binding_list,
    }


# ──────────────────────────────────────────────────────────────
# 6. Component-to-code traversal
# ──────────────────────────────────────────────────────────────

def traverse_component_to_code(
    conn: sqlite3.Connection,
    component_id: int,
    max_depth: int = 5,
) -> Dict[str, Any]:
    """Link a frontend component to its executable implementation and call tree.

    Args:
        conn: SQLite connection.
        component_id: ID of the frontend_components row.
        max_depth: Maximum depth for the call tree traversal.

    Returns:
        Dict with component info, implementation function/class details,
        and a call tree (BFS, cycle-detected).
    """
    comp = _get_component(conn, component_id)
    if comp is None:
        return {"error": f"Component not found: id={component_id}"}

    result = {
        "component_id": component_id,
        "name": comp["name"],
        "file_path": comp["file_path"],
        "impl_function_id": comp["impl_function_id"],
        "impl_class_id": comp["impl_class_id"],
        "implementation": None,
        "call_tree": None,
    }

    # Resolve implementation function
    impl_func_id = comp["impl_function_id"]
    impl_class_id = comp["impl_class_id"]

    if impl_func_id:
        func_row = conn.execute(
            "SELECT fn.*, f.path as file_path FROM functions fn "
            "JOIN files f ON fn.file_id = f.id WHERE fn.id = ?",
            (impl_func_id,)
        ).fetchone()
        if func_row:
            result["implementation"] = {
                "type": "function",
                "id": func_row["id"],
                "name": func_row["name"],
                "kind": func_row["type"],
                "file_path": func_row["file_path"],
                "location": func_row["location"],
                "source_range": json.loads(func_row["location"]) if func_row["location"] else None,
            }

            # Build call tree from this function
            result["call_tree"] = _build_call_tree(conn, impl_func_id, max_depth)

    elif impl_class_id:
        cls_row = conn.execute(
            "SELECT c.*, f.path as file_path FROM classes c "
            "JOIN files f ON c.file_id = f.id WHERE c.id = ?",
            (impl_class_id,)
        ).fetchone()
        if cls_row:
            result["implementation"] = {
                "type": "class",
                "id": cls_row["id"],
                "name": cls_row["name"],
                "file_path": cls_row["file_path"],
                "location": cls_row["location"],
                "source_range": json.loads(cls_row["location"]) if cls_row["location"] else None,
            }
            # List methods of the class
            methods = conn.execute(
                "SELECT fn.id, fn.name, fn.type, fn.location FROM functions fn "
                "WHERE fn.parent_id = ? ORDER BY fn.id",
                (impl_class_id,)
            ).fetchall()
            result["call_tree"] = {
                "type": "class",
                "name": cls_row["name"],
                "methods": [
                    {
                        "id": m["id"],
                        "name": m["name"],
                        "type": m["type"],
                        "call_tree": _build_call_tree(conn, m["id"], max_depth),
                    }
                    for m in methods
                ],
            }

    return result


def _build_call_tree(
    conn: sqlite3.Connection,
    func_id: int,
    max_depth: int,
) -> Dict[str, Any]:
    """Build a BFS call tree from a function, with cycle detection."""
    root = {
        "id": f"f:{func_id}",
        "name": None,
        "depth": 0,
        "cycle": False,
        "callees": [],
    }

    # Get root function name
    func_row = conn.execute("SELECT name FROM functions WHERE id = ?", (func_id,)).fetchone()
    if func_row:
        root["name"] = func_row["name"]

    nodes: Dict[int, Dict[str, Any]] = {func_id: root}
    queue: deque = deque()
    queue.append((func_id, root, 0, frozenset([func_id])))

    while queue:
        fid, parent_node, depth, ancestors = queue.popleft()
        if depth >= max_depth:
            continue

        deps = conn.execute(
            """SELECT d.name, d.target_function_id, d.target_class_id, d.dependency_type
               FROM dependencies d
               WHERE d.source_function_id = ?
                 AND d.dependency_type IN ('function_call', 'method_call', 'class_reference')
               ORDER BY d.name""",
            (fid,)
        ).fetchall()

        seen = set()
        for dep in deps:
            callee_id = dep["target_function_id"]
            callee_name = dep["name"]
            dep_type = dep["dependency_type"]

            # For class_reference, use target_class_id if target_function_id is NULL
            if callee_id is None and dep["target_class_id"] is not None:
                # Look up the class as a node
                cls_id = dep["target_class_id"]
                key = (callee_name, cls_id, dep_type)
                if key in seen:
                    continue
                seen.add(key)

                cls_row = conn.execute(
                    "SELECT c.name, f.path as file_path FROM classes c "
                    "JOIN files f ON c.file_id = f.id WHERE c.id = ?",
                    (cls_id,)
                ).fetchone()
                node = {
                    "id": f"c:{cls_id}",
                    "name": cls_row["name"] if cls_row else callee_name,
                    "depth": depth + 1,
                    "cycle": cls_id in ancestors,
                    "file_path": cls_row["file_path"] if cls_row else None,
                    "callees": [],
                    "kind": "class",
                }
                # Class nodes don't have callees in this traversal
                parent_node["callees"].append(node)
                continue

            key = (callee_name, callee_id, dep_type)
            if key in seen:
                continue
            seen.add(key)

            if callee_id is None:
                parent_node["callees"].append({
                    "id": None,
                    "name": callee_name,
                    "depth": depth + 1,
                    "cycle": False,
                    "callees": [],
                    "unresolved": True,
                })
                continue

            is_cycle = callee_id in ancestors
            if callee_id not in nodes:
                callee_row = conn.execute(
                    "SELECT fn.name, f.path as file_path FROM functions fn "
                    "JOIN files f ON fn.file_id = f.id WHERE fn.id = ?",
                    (callee_id,)
                ).fetchone()
                node = {
                    "id": f"f:{callee_id}",
                    "name": callee_row["name"] if callee_row else callee_name,
                    "depth": depth + 1,
                    "cycle": is_cycle,
                    "file_path": callee_row["file_path"] if callee_row else None,
                    "callees": [],
                }
                nodes[callee_id] = node
                parent_node["callees"].append(node)
                if not is_cycle:
                    queue.append((callee_id, node, depth + 1, ancestors | {callee_id}))
            else:
                parent_node["callees"].append({
                    "id": f"f:{callee_id}",
                    "name": nodes[callee_id]["name"],
                    "depth": depth + 1,
                    "cycle": is_cycle,
                    "callees": [],
                    "already_visited": True,
                })

    return root


# ──────────────────────────────────────────────────────────────
# 7. Full frontend traversal
# ──────────────────────────────────────────────────────────────

def traverse_full_frontend(
    conn: sqlite3.Connection,
    component_id: int,
    max_depth: int = 10,
) -> Dict[str, Any]:
    """Combined traversal: render children + markup + events + bindings + styles.

    Args:
        conn: SQLite connection.
        component_id: ID of the starting frontend_components row.
        max_depth: Maximum traversal depth for render/markup trees.

    Returns:
        Dict combining render graph, markup trees, events, bindings, and
        style information for the component and its rendered children.
    """
    comp = _get_component(conn, component_id)
    if comp is None:
        return {"error": f"Component not found: id={component_id}"}

    # 1. Render graph (children)
    render_tree = traverse_render_graph(conn, component_id, "children", max_depth)

    # 2. Collect all markup elements for this component
    elements = conn.execute(
        """SELECT m.id, m.tag_name, m.element_type, m.parent_element_id,
                  m.static_classes, m.element_id_attr, m.is_conditional, m.is_repeated,
                  m.source_range, f.path as file_path
           FROM markup_elements m
           JOIN files f ON m.file_id = f.id
           WHERE m.component_id = ?
           ORDER BY m.id""",
        (component_id,)
    ).fetchall()

    markup_trees = []
    for elem in elements:
        # Only build trees for root elements (no parent)
        if elem["parent_element_id"] is None:
            tree = traverse_markup_tree(conn, elem["id"], "children", max_depth)
            markup_trees.append(tree)

    # 3. Events and bindings for each element
    element_details = []
    for elem in elements:
        eid = elem["id"]
        events = traverse_event_graph(conn, eid)
        bindings = traverse_binding_graph(conn, eid)
        element_details.append({
            "element_id": eid,
            "tag_name": elem["tag_name"],
            "element_type": elem["element_type"],
            "static_classes": json.loads(elem["static_classes"]) if elem["static_classes"] else [],
            "source_range": json.loads(elem["source_range"]) if elem["source_range"] else None,
            "events": events.get("events", []),
            "bindings": bindings.get("bindings", []),
        })

    # 4. Style selectors for this component
    selectors = conn.execute(
        """SELECT s.id, s.selector_text, s.selector_type, s.is_scoped,
                  f.path as file_path
           FROM style_selectors s
           JOIN files f ON s.file_id = f.id
           WHERE s.component_id = ?
           ORDER BY s.id""",
        (component_id,)
    ).fetchall()

    style_info = []
    for sel in selectors:
        style_info.append({
            "id": sel["id"],
            "selector_text": sel["selector_text"],
            "selector_type": sel["selector_type"],
            "is_scoped": bool(sel["is_scoped"]),
            "file_path": sel["file_path"],
        })

    # 5. Component-to-code link
    code_link = traverse_component_to_code(conn, component_id, max_depth=max_depth)

    return {
        "component": {
            "id": component_id,
            "name": comp["name"],
            "source_range": json.loads(comp["source_range"]) if comp.get("source_range") else None,
            "file_path": comp["file_path"],
        },
        "render_tree": render_tree,
        "markup_trees": markup_trees,
        "element_details": element_details,
        "styles": style_info,
        "implementation": code_link.get("implementation"),
        "call_tree": code_link.get("call_tree"),
    }
