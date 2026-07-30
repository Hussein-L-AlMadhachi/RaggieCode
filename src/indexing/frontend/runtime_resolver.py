#!/usr/bin/env python3
"""
Runtime element resolution (Phase 9).

Accepts metadata from a browser extension (or any source) and resolves it
to the best matching source semantic entity in the index.

Resolution strategies (tried in priority order):
  1. Exact source location (file + line + column)
  2. Exact source file + component name
  3. Component ancestry → walk render graph
  4. Element ID → markup_elements.element_id_attr
  5. Tag + class combination
  6. Attributes
  7. Text content
  8. DOM ancestry → walk markup tree
  9. Heuristic selector matching

All applicable strategies are run. Results are merged, deduplicated by
entity ID, and sorted by confidence score (highest first). Ambiguity is
never hidden — all plausible candidates are returned.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set, Tuple

from indexing.frontend.location_lookup import lookup_entity_at_location
from indexing.frontend.graph import (
    traverse_render_graph,
    traverse_markup_tree,
    traverse_event_graph,
    traverse_binding_graph,
    traverse_style_graph,
)
from indexing.frontend.css_selector_utils import selector_matches_element


# ──────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────

@dataclass
class ResolutionCandidate:
    """A single candidate from runtime resolution."""

    entity_type: str  # "markup_element" or "component"
    entity_id: int
    confidence: float
    strategies_matched: List[str] = field(default_factory=list)
    component: Optional[Dict[str, Any]] = None
    source_range: Optional[Dict[str, int]] = None
    file_path: Optional[str] = None
    tag_name: Optional[str] = None
    static_classes: List[str] = field(default_factory=list)
    element_id_attr: Optional[str] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    bindings: List[Dict[str, Any]] = field(default_factory=list)
    styles: List[Dict[str, Any]] = field(default_factory=list)
    rendering_parents: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "confidence": self.confidence,
            "strategies_matched": self.strategies_matched,
            "component": self.component,
            "source_range": self.source_range,
            "file_path": self.file_path,
            "tag_name": self.tag_name,
            "static_classes": self.static_classes,
            "element_id_attr": self.element_id_attr,
            "events": self.events,
            "bindings": self.bindings,
            "styles": self.styles,
            "rendering_parents": self.rendering_parents,
        }


@dataclass
class ResolutionResult:
    """Result of runtime element resolution."""

    candidates: List[ResolutionCandidate] = field(default_factory=list)
    ambiguity_explanation: Optional[str] = None
    best_confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "ambiguity_explanation": self.ambiguity_explanation,
            "best_confidence": self.best_confidence,
        }


# ──────────────────────────────────────────────────────────────
# Confidence scores per strategy
# ──────────────────────────────────────────────────────────────

_CONFIDENCE = {
    "exact_location": 1.0,
    "file_and_component": 0.9,
    "component_ancestry": 0.8,
    "element_id_unique": 0.85,
    "element_id_duplicate": 0.5,
    "tag_and_classes_full": 0.7,
    "tag_and_classes_partial": 0.5,
    "attributes": 0.6,
    "text_content": 0.5,
    "dom_ancestry_full": 0.65,
    "dom_ancestry_partial": 0.4,
    "selector_matching": 0.55,
}


def _combine_confidence(a: float, b: float) -> float:
    """Combine two confidence scores using probabilistic OR."""
    return 1.0 - (1.0 - a) * (1.0 - b)


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


def _element_row_to_candidate(
    row: sqlite3.Row,
    confidence: float,
    strategy: str,
) -> ResolutionCandidate:
    """Convert a markup_elements row to a ResolutionCandidate."""
    source_range = _parse_json(row["source_range"]) if "source_range" in row.keys() else None
    static_classes = _parse_json(row["static_classes"]) if "static_classes" in row.keys() else []
    if static_classes is None:
        static_classes = []

    comp = None
    if row["component_id"]:
        comp_row = row.keys() and None  # placeholder, enriched later
        comp = {"id": row["component_id"]}

    return ResolutionCandidate(
        entity_type="markup_element",
        entity_id=row["id"],
        confidence=confidence,
        strategies_matched=[strategy],
        component=comp,
        source_range=source_range,
        file_path=row["file_path"] if "file_path" in row.keys() else None,
        tag_name=row["tag_name"],
        static_classes=static_classes,
        element_id_attr=row["element_id_attr"] if "element_id_attr" in row.keys() else None,
    )


def _component_row_to_candidate(
    row: sqlite3.Row,
    confidence: float,
    strategy: str,
) -> ResolutionCandidate:
    """Convert a frontend_components row to a ResolutionCandidate."""
    source_range = _parse_json(row["source_range"]) if "source_range" in row.keys() else None

    return ResolutionCandidate(
        entity_type="component",
        entity_id=row["id"],
        confidence=confidence,
        strategies_matched=[strategy],
        component={"id": row["id"], "name": row["name"]},
        source_range=source_range,
        file_path=row["file_path"] if "file_path" in row.keys() else None,
        tag_name=None,
    )


# ──────────────────────────────────────────────────────────────
# Strategy 1: Exact source location
# ──────────────────────────────────────────────────────────────

def _try_exact_location(conn, meta: dict) -> List[ResolutionCandidate]:
    source_file = meta.get("source_file")
    source_line = meta.get("source_line")
    source_column = meta.get("source_column")

    if not source_file or source_line is None or source_column is None:
        return []

    matches = lookup_entity_at_location(
        conn, source_file, source_line, source_column, include_backend=False
    )

    candidates = []
    for m in matches:
        c = ResolutionCandidate(
            entity_type=m.entity_type,
            entity_id=m.entity_id,
            confidence=_CONFIDENCE["exact_location"],
            strategies_matched=["exact_location"],
            component={"id": m.extra.get("component_id")} if m.extra.get("component_id") else None,
            source_range=m.source_range,
            file_path=m.file_path,
            tag_name=m.extra.get("tag_name"),
            static_classes=_parse_json(m.extra.get("static_classes")) or [],
            element_id_attr=m.extra.get("element_id_attr"),
        )
        candidates.append(c)

    return candidates


# ──────────────────────────────────────────────────────────────
# Strategy 2: Source file + component name
# ──────────────────────────────────────────────────────────────

def _try_file_and_component(conn, meta: dict) -> List[ResolutionCandidate]:
    source_file = meta.get("source_file")
    component_name = meta.get("component_name")

    if not component_name:
        return []

    if source_file:
        row = conn.execute(
            """SELECT c.*, f.path as file_path
               FROM frontend_components c
               JOIN files f ON c.file_id = f.id
               WHERE c.name = ? AND f.path = ?
               LIMIT 1""",
            (component_name, source_file)
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT c.*, f.path as file_path
               FROM frontend_components c
               JOIN files f ON c.file_id = f.id
               WHERE c.name = ?
               LIMIT 1""",
            (component_name,)
        ).fetchone()

    if not row:
        return []

    return [_component_row_to_candidate(row, _CONFIDENCE["file_and_component"], "file_and_component")]


# ──────────────────────────────────────────────────────────────
# Strategy 3: Component ancestry → render graph
# ──────────────────────────────────────────────────────────────

def _try_component_ancestry(conn, meta: dict) -> List[ResolutionCandidate]:
    ancestry = meta.get("component_ancestry")
    if not ancestry or not isinstance(ancestry, list) or len(ancestry) < 2:
        return []

    # ancestry is a list of component names from root to leaf, e.g. ["App", "Card", "Button"]
    # We start from the root and walk the render graph to find the leaf
    root_name = ancestry[0]
    root_row = conn.execute(
        """SELECT c.id FROM frontend_components c WHERE c.name = ? LIMIT 1""",
        (root_name,)
    ).fetchone()
    if not root_row:
        return []

    # Walk render graph following ancestry names
    current_id = root_row["id"]
    for i in range(1, len(ancestry)):
        name = ancestry[i]
        children = conn.execute(
            """SELECT rr.child_component_id, c.name
               FROM render_relationships rr
               JOIN frontend_components c ON rr.child_component_id = c.id
               WHERE rr.parent_component_id = ? AND c.name = ?
               LIMIT 1""",
            (current_id, name)
        ).fetchone()
        if not children:
            # Ancestry doesn't match — try without name match (fuzzy)
            return []
        current_id = children["child_component_id"]

    # Found the leaf component
    row = conn.execute(
        """SELECT c.*, f.path as file_path
           FROM frontend_components c
           JOIN files f ON c.file_id = f.id
           WHERE c.id = ?""",
        (current_id,)
    ).fetchone()
    if not row:
        return []

    return [_component_row_to_candidate(row, _CONFIDENCE["component_ancestry"], "component_ancestry")]


# ──────────────────────────────────────────────────────────────
# Strategy 4: Element ID
# ──────────────────────────────────────────────────────────────

def _try_element_id(conn, meta: dict) -> List[ResolutionCandidate]:
    element_id_attr = meta.get("element_id")
    if not element_id_attr:
        return []

    rows = conn.execute(
        """SELECT m.*, f.path as file_path
           FROM markup_elements m
           JOIN files f ON m.file_id = f.id
           WHERE m.element_id_attr = ?
           ORDER BY m.id""",
        (element_id_attr,)
    ).fetchall()

    if not rows:
        return []

    if len(rows) == 1:
        return [_element_row_to_candidate(rows[0], _CONFIDENCE["element_id_unique"], "element_id_unique")]
    else:
        return [
            _element_row_to_candidate(r, _CONFIDENCE["element_id_duplicate"], "element_id_duplicate")
            for r in rows
        ]


# ──────────────────────────────────────────────────────────────
# Strategy 5: Tag + class combination
# ──────────────────────────────────────────────────────────────

def _try_tag_and_classes(conn, meta: dict) -> List[ResolutionCandidate]:
    dom_tag = meta.get("dom_tag")
    classes = meta.get("classes")

    if not dom_tag or not classes or not isinstance(classes, list):
        return []

    # Query elements matching the tag
    rows = conn.execute(
        """SELECT m.*, f.path as file_path
           FROM markup_elements m
           JOIN files f ON m.file_id = f.id
           WHERE m.tag_name = ?
           ORDER BY m.id""",
        (dom_tag,)
    ).fetchall()

    candidates = []
    target_class_set = set(classes)

    for row in rows:
        elem_classes = _parse_json(row["static_classes"]) or []
        elem_class_set = set(elem_classes)

        if target_class_set.issubset(elem_class_set):
            # All target classes present
            c = _element_row_to_candidate(row, _CONFIDENCE["tag_and_classes_full"], "tag_and_classes_full")
            candidates.append(c)
        elif elem_class_set & target_class_set:
            # Partial overlap
            overlap = len(elem_class_set & target_class_set)
            total = len(target_class_set)
            score = _CONFIDENCE["tag_and_classes_partial"] * (overlap / total) if total else 0
            c = _element_row_to_candidate(row, score, "tag_and_classes_partial")
            candidates.append(c)

    return candidates


# ──────────────────────────────────────────────────────────────
# Strategy 6: Attributes
# ──────────────────────────────────────────────────────────────

def _try_attributes(conn, meta: dict) -> List[ResolutionCandidate]:
    attributes = meta.get("attributes")
    dom_tag = meta.get("dom_tag")

    if not attributes or not isinstance(attributes, dict):
        return []

    # Build a query that searches for elements with matching attributes
    # attributes is a dict like {"data-testid": "submit", "role": "button"}
    # We use JSON extraction to match
    rows = conn.execute(
        """SELECT m.*, f.path as file_path
           FROM markup_elements m
           JOIN files f ON m.file_id = f.id
           WHERE m.attributes IS NOT NULL
           ORDER BY m.id"""
    ).fetchall()

    candidates = []
    for row in rows:
        elem_attrs = _parse_json(row["attributes"]) or {}
        if not isinstance(elem_attrs, dict):
            continue

        # Check how many attributes match
        matched = 0
        total = len(attributes)
        for k, v in attributes.items():
            if k in elem_attrs and str(elem_attrs[k]) == str(v):
                matched += 1

        if matched == 0:
            continue

        # If dom_tag is provided, also check tag
        if dom_tag and row["tag_name"] != dom_tag:
            continue

        score = _CONFIDENCE["attributes"] * (matched / total) if total else 0
        c = _element_row_to_candidate(row, score, "attributes")
        candidates.append(c)

    return candidates


# ──────────────────────────────────────────────────────────────
# Strategy 7: Text content
# ──────────────────────────────────────────────────────────────

def _try_text_content(conn, meta: dict, project_root: str = None) -> List[ResolutionCandidate]:
    text = meta.get("text")
    if not text:
        return []

    # Text nodes are stored as element_type='text' but the actual text content
    # is not stored in the DB — we need to read it from the source file using
    # the element's source_range.
    rows = conn.execute(
        """SELECT m.*, f.path as file_path
           FROM markup_elements m
           JOIN files f ON m.file_id = f.id
           WHERE m.element_type = 'text' OR m.element_type = '#text'
           ORDER BY m.id"""
    ).fetchall()

    candidates = []
    for row in rows:
        # Try to extract text from the source file using source_range
        elem_text = ""
        source_range = _parse_json(row["source_range"]) if "source_range" in row.keys() else None
        file_path = row["file_path"] if "file_path" in row.keys() else None

        if source_range and file_path:
            try:
                import os
                # file_path is project-relative; try resolving with project_root
                candidates_paths = [file_path]
                if project_root:
                    candidates_paths.append(os.path.join(project_root, file_path))
                resolved = None
                for p in candidates_paths:
                    if os.path.exists(p):
                        resolved = p
                        break
                if resolved:
                    with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                    start_line = source_range.get("start_line", 1) - 1
                    end_line = source_range.get("end_line", 1)
                    if 0 <= start_line < len(lines):
                        elem_text = "".join(lines[start_line:end_line]).strip()
            except Exception:
                pass

        # Also check attributes as a fallback
        if not elem_text:
            attrs = _parse_json(row["attributes"]) or {}
            if isinstance(attrs, dict):
                elem_text = attrs.get("text", "") or attrs.get("content", "")

        if not elem_text:
            continue

        # Check if the text matches (exact or contains)
        if text in elem_text or elem_text in text:
            # Get the parent element (the real element, not the text node)
            parent_id = row["parent_element_id"]
            if parent_id:
                parent_row = conn.execute(
                    """SELECT m.*, f.path as file_path
                       FROM markup_elements m
                       JOIN files f ON m.file_id = f.id
                       WHERE m.id = ?""",
                    (parent_id,)
                ).fetchone()
                if parent_row:
                    c = _element_row_to_candidate(parent_row, _CONFIDENCE["text_content"], "text_content")
                    candidates.append(c)
                    continue

        # Fallback: match on the text node itself
        c = _element_row_to_candidate(row, _CONFIDENCE["text_content"] * 0.8, "text_content")
        candidates.append(c)

    return candidates


# ──────────────────────────────────────────────────────────────
# Strategy 8: DOM ancestry → markup tree
# ──────────────────────────────────────────────────────────────

def _try_dom_ancestry(conn, meta: dict) -> List[ResolutionCandidate]:
    dom_ancestry = meta.get("dom_ancestry")
    if not dom_ancestry or not isinstance(dom_ancestry, list) or len(dom_ancestry) < 2:
        return []

    # dom_ancestry is a list of dicts: [{"tag": "body"}, {"tag": "div", "classes": ["container"]}, {"tag": "button", "classes": ["btn"]}]
    # The last element is the target element
    target = dom_ancestry[-1]
    target_tag = target.get("tag", "")
    target_classes = target.get("classes", [])

    # Find candidate elements matching the target's tag
    rows = conn.execute(
        """SELECT m.*, f.path as file_path
           FROM markup_elements m
           JOIN files f ON m.file_id = f.id
           WHERE m.tag_name = ?
           ORDER BY m.id""",
        (target_tag,)
    ).fetchall()

    candidates = []
    for row in rows:
        # Walk up the markup tree and check ancestry
        ancestry_match = _check_ancestry(conn, row["id"], dom_ancestry[:-1])
        if ancestry_match == "full":
            c = _element_row_to_candidate(row, _CONFIDENCE["dom_ancestry_full"], "dom_ancestry_full")
            candidates.append(c)
        elif ancestry_match == "partial":
            c = _element_row_to_candidate(row, _CONFIDENCE["dom_ancestry_partial"], "dom_ancestry_partial")
            candidates.append(c)

    return candidates


def _check_ancestry(conn, element_id: int, expected_ancestry: List[dict]) -> str:
    """Walk up the markup tree from element_id, checking against expected ancestry.

    Returns "full" if all ancestors match, "partial" if some match, "" if none.
    """
    if not expected_ancestry:
        return "full"

    current_id = element_id
    matched = 0
    expected_idx = len(expected_ancestry) - 1  # Start from the immediate parent

    while current_id and expected_idx >= 0:
        row = conn.execute(
            "SELECT parent_element_id, tag_name, static_classes FROM markup_elements WHERE id = ?",
            (current_id,)
        ).fetchone()
        if not row:
            break

        parent_id = row["parent_element_id"]
        if parent_id is None:
            break

        parent_row = conn.execute(
            "SELECT tag_name, static_classes FROM markup_elements WHERE id = ?",
            (parent_id,)
        ).fetchone()
        if not parent_row:
            break

        expected = expected_ancestry[expected_idx]
        expected_tag = expected.get("tag", "")

        if parent_row["tag_name"] == expected_tag:
            expected_classes = set(expected.get("classes", []))
            if expected_classes:
                parent_classes = set(_parse_json(parent_row["static_classes"]) or [])
                if expected_classes.issubset(parent_classes):
                    matched += 1
            else:
                matched += 1

        current_id = parent_id
        expected_idx -= 1

    if matched == len(expected_ancestry):
        return "full"
    elif matched > 0:
        return "partial"
    return ""


# ──────────────────────────────────────────────────────────────
# Strategy 9: Heuristic selector matching
# ──────────────────────────────────────────────────────────────

def _try_selector_matching(conn, meta: dict) -> List[ResolutionCandidate]:
    dom_tag = meta.get("dom_tag")
    classes = meta.get("classes", [])
    element_id_attr = meta.get("element_id")

    if not dom_tag and not classes and not element_id_attr:
        return []

    # First, check style_selector_matches for pre-computed matches
    # If we have classes, find selectors that match those classes
    rows = conn.execute(
        """SELECT m.*, f.path as file_path
           FROM markup_elements m
           JOIN files f ON m.file_id = f.id
           WHERE m.tag_name = ?
           ORDER BY m.id""",
        (dom_tag,)
    ).fetchall() if dom_tag else []

    candidates = []
    for row in rows:
        elem_classes = _parse_json(row["static_classes"]) or []
        elem_id = row["element_id_attr"]

        # Check if any selector in the index matches this element
        # First check pre-computed matches
        sm_rows = conn.execute(
            "SELECT selector_id FROM style_selector_matches WHERE element_id = ? LIMIT 1",
            (row["id"],)
        ).fetchall()

        if sm_rows:
            c = _element_row_to_candidate(row, _CONFIDENCE["selector_matching"], "selector_matching")
            candidates.append(c)
            continue

        # Fallback: runtime selector matching against all selectors
        all_selectors = conn.execute(
            "SELECT selector_text FROM style_selectors"
        ).fetchall()

        for sel_row in all_selectors:
            if selector_matches_element(sel_row["selector_text"], dom_tag, elem_classes, elem_id):
                c = _element_row_to_candidate(row, _CONFIDENCE["selector_matching"], "selector_matching")
                candidates.append(c)
                break

    return candidates


# ──────────────────────────────────────────────────────────────
# Enrichment
# ──────────────────────────────────────────────────────────────

def _enrich_candidate(conn, candidate: ResolutionCandidate) -> None:
    """Enrich a candidate with events, bindings, styles, and rendering parents."""
    if candidate.entity_type == "markup_element":
        eid = candidate.entity_id

        # Events
        events_result = traverse_event_graph(conn, eid)
        candidate.events = events_result.get("events", [])

        # Bindings
        bindings_result = traverse_binding_graph(conn, eid)
        candidate.bindings = bindings_result.get("bindings", [])

        # Styles (selectors matching this element)
        styles_result = traverse_style_graph(conn, eid, "to_definition")
        candidate.styles = styles_result.get("candidate_selectors", [])

        # Owning component
        if candidate.component and "id" in candidate.component:
            comp_id = candidate.component["id"]
            comp_row = conn.execute(
                """SELECT c.name, c.source_range, f.path as file_path
                   FROM frontend_components c
                   JOIN files f ON c.file_id = f.id
                   WHERE c.id = ?""",
                (comp_id,)
            ).fetchone()
            if comp_row:
                candidate.component = {
                    "id": comp_id,
                    "name": comp_row["name"],
                    "source_range": _parse_json(comp_row["source_range"]),
                    "file_path": comp_row["file_path"],
                }

                # Rendering parents
                parents_result = traverse_render_graph(conn, comp_id, "parents", max_depth=5)
                candidate.rendering_parents = parents_result.get("children", [])

    elif candidate.entity_type == "component":
        comp_id = candidate.entity_id

        # Rendering parents
        parents_result = traverse_render_graph(conn, comp_id, "parents", max_depth=5)
        candidate.rendering_parents = parents_result.get("children", [])

        # Enrich component info
        comp_row = conn.execute(
            """SELECT c.name, c.source_range, f.path as file_path
               FROM frontend_components c
               JOIN files f ON c.file_id = f.id
               WHERE c.id = ?""",
            (comp_id,)
        ).fetchone()
        if comp_row:
            candidate.component = {
                "id": comp_id,
                "name": comp_row["name"],
                "source_range": _parse_json(comp_row["source_range"]),
                "file_path": comp_row["file_path"],
            }


# ──────────────────────────────────────────────────────────────
# Merge and score
# ──────────────────────────────────────────────────────────────

def _merge_candidates(candidates: List[ResolutionCandidate]) -> List[ResolutionCandidate]:
    """Merge candidates that refer to the same entity.

    Combines confidence scores (probabilistic OR) and merges strategies_matched.
    """
    merged: Dict[Tuple[str, int], ResolutionCandidate] = {}

    for c in candidates:
        key = (c.entity_type, c.entity_id)
        if key in merged:
            existing = merged[key]
            existing.confidence = _combine_confidence(existing.confidence, c.confidence)
            for s in c.strategies_matched:
                if s not in existing.strategies_matched:
                    existing.strategies_matched.append(s)
            # Keep the higher-confidence fields
            if c.confidence > existing.confidence:
                existing.source_range = c.source_range or existing.source_range
                existing.file_path = c.file_path or existing.file_path
                existing.tag_name = c.tag_name or existing.tag_name
                existing.static_classes = c.static_classes or existing.static_classes
                existing.element_id_attr = c.element_id_attr or existing.element_id_attr
        else:
            merged[key] = c

    return list(merged.values())


def _build_ambiguity_explanation(candidates: List[ResolutionCandidate]) -> Optional[str]:
    """Build a human-readable explanation of ambiguity."""
    if len(candidates) <= 1:
        return None

    # Group by strategy
    strategies = set()
    for c in candidates:
        strategies.update(c.strategies_matched)

    descriptions = []
    for c in candidates[:5]:  # Top 5
        entity_desc = c.tag_name or c.entity_type
        if c.static_classes:
            entity_desc += "." + ".".join(c.static_classes[:3])
        if c.element_id_attr:
            entity_desc += f"#{c.element_id_attr}"
        strategies_str = ", ".join(c.strategies_matched)
        descriptions.append(
            f"{entity_desc} (id={c.entity_id}, confidence={c.confidence:.2f}, strategies: {strategies_str})"
        )

    summary = f"{len(candidates)} candidates found. " + "; ".join(descriptions)
    if len(candidates) > 5:
        summary += f" ... and {len(candidates) - 5} more"
    return summary


# ──────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────

def resolve_runtime_element(
    conn: sqlite3.Connection,
    metadata: Dict[str, Any],
    project_root: str = None,
) -> Dict[str, Any]:
    """Resolve browser/runtime element metadata to source semantic entities.

    Args:
        conn: SQLite connection to the index database.
        metadata: Dict with any combination of keys:
            - source_file (str): Project-relative file path
            - source_line (int): 1-indexed line number
            - source_column (int): 0-indexed column number
            - component_name (str): React/component name
            - component_ancestry (list[str]): Component names from root to leaf
            - dom_tag (str): HTML tag name
            - element_id (str): Element's id attribute value
            - classes (list[str]): CSS class names
            - attributes (dict): Element attributes
            - text (str): Text content
            - dom_ancestry (list[dict]): DOM tree from root to target,
              each dict has "tag" (str) and optionally "classes" (list[str])
        project_root: Optional path to the project root directory, for resolving
            project-relative file paths when reading source files.

    Returns:
        Dict with:
            - candidates: list of candidate dicts sorted by confidence (highest first)
            - ambiguity_explanation: str or None
            - best_confidence: float
    """
    all_candidates: List[ResolutionCandidate] = []

    # Run all applicable strategies
    strategies = [
        _try_exact_location,
        _try_file_and_component,
        _try_component_ancestry,
        _try_element_id,
        _try_tag_and_classes,
        _try_attributes,
        _try_text_content,
        _try_dom_ancestry,
        _try_selector_matching,
    ]

    for strategy_fn in strategies:
        try:
            if strategy_fn is _try_text_content:
                results = strategy_fn(conn, metadata, project_root)
            else:
                results = strategy_fn(conn, metadata)
            all_candidates.extend(results)
        except Exception:
            # A strategy failure should never prevent other strategies from running
            continue

    # Merge duplicates
    merged = _merge_candidates(all_candidates)

    # Enrich each candidate
    for c in merged:
        _enrich_candidate(conn, c)

    # Sort by confidence (highest first)
    merged.sort(key=lambda c: c.confidence, reverse=True)

    # Build result
    result = ResolutionResult(
        candidates=merged,
        ambiguity_explanation=_build_ambiguity_explanation(merged),
        best_confidence=merged[0].confidence if merged else 0.0,
    )

    return result.to_dict()
