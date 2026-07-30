#!/usr/bin/env python3
"""
Safe editing of frontend semantic entities (Phase 11).

Provides validation and application of edits to frontend entities
(markup elements, CSS rules, custom properties, event handlers,
property bindings, JSX subtrees) using the source ranges stored
in the index.

Validation checks:
  1. File has not changed since indexing (content hash comparison)
  2. Source range is not ambiguous
  3. Entity does not share an unsafe range with unrelated syntax
  4. Entity was not only heuristically identified
  5. Parser recovery does not prevent trustworthy boundaries
"""

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple


# ──────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────

@dataclass
class EditValidation:
    """Result of validating an edit range."""
    safe: bool
    reason: Optional[str] = None
    file_path: Optional[str] = None
    source_range: Optional[Dict[str, int]] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "safe": self.safe,
            "reason": self.reason,
            "file_path": self.file_path,
            "source_range": self.source_range,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
        }


@dataclass
class EditResult:
    """Result of applying a frontend edit."""
    success: bool
    reason: Optional[str] = None
    file_path: Optional[str] = None
    old_source: Optional[str] = None
    new_source: Optional[str] = None
    diff: Optional[str] = None
    source_range: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "reason": self.reason,
            "file_path": self.file_path,
            "old_source": self.old_source,
            "new_source": self.new_source,
            "diff": self.diff,
            "source_range": self.source_range,
        }


# ──────────────────────────────────────────────────────────────
# Entity type → table mapping
# ──────────────────────────────────────────────────────────────

_ENTITY_TABLES = {
    "markup_element": "markup_elements",
    "css_rule": "style_selectors",
    "custom_property": "style_custom_properties",
    "event_binding": "frontend_events",
    "property_binding": "frontend_bindings",
    "jsx_subtree": "markup_elements",
}

# Entity types that use the markup_elements table but need special handling
_MARKUP_ENTITY_TYPES = {"markup_element", "jsx_subtree"}


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


def _compute_file_hash(file_path: str) -> Optional[str]:
    """Compute xxhash-like hash of file content for staleness check.

    Uses the same algorithm as the indexer (xxhash if available, else sha256 fallback).
    """
    try:
        import xxhash
        with open(file_path, "rb") as f:
            return xxhash.xxh64(f.read()).hexdigest()
    except ImportError:
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]


def _get_entity_row(conn, entity_type: str, entity_id: int) -> Optional[sqlite3.Row]:
    """Fetch the entity row from the appropriate table."""
    table = _ENTITY_TABLES.get(entity_type)
    if not table:
        return None

    row = conn.execute(
        f"SELECT * FROM {table} WHERE id = ?",
        (entity_id,)
    ).fetchone()
    return row


def _get_file_info(conn, file_path: str) -> Optional[Dict[str, Any]]:
    """Get file info from the index by path."""
    normalized = file_path[2:] if file_path.startswith("./") else file_path
    row = conn.execute(
        "SELECT id, path, absolute_path, language, content_hash, mtime FROM files WHERE path = ?",
        (normalized,)
    ).fetchone()
    if not row:
        # Fallback: match by filename
        filename = os.path.basename(normalized)
        row = conn.execute(
            "SELECT id, path, absolute_path, language, content_hash, mtime FROM files WHERE path LIKE ?",
            (f"%{filename}",)
        ).fetchone()
    return dict(row) if row else None


def _get_file_info_by_id(conn, file_id: int) -> Optional[Dict[str, Any]]:
    """Get file info from the index by ID."""
    row = conn.execute(
        "SELECT id, path, absolute_path, language, content_hash, mtime FROM files WHERE id = ?",
        (file_id,)
    ).fetchone()
    return dict(row) if row else None


def _resolve_file_path(file_info: Dict[str, Any]) -> Optional[str]:
    """Resolve the actual file path from file info."""
    abs_path = file_info.get("absolute_path", "")
    if abs_path and os.path.exists(abs_path):
        return abs_path

    # Fallback: try cwd / relative path
    rel_path = file_info.get("path", "")
    for base in [os.getcwd(), os.path.join(os.getcwd(), "src")]:
        candidate = os.path.join(base, rel_path)
        if os.path.exists(candidate):
            return candidate

    return None


def _read_source_at_range(file_path: str, source_range: Dict[str, int]) -> Optional[str]:
    """Read source text at a given line range from a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
        start = source_range.get("start_line", 1)
        end = source_range.get("end_line", start)
        if 1 <= start <= len(lines):
            return "\n".join(lines[start - 1:end])
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────────────────────
# validate_edit_range
# ──────────────────────────────────────────────────────────────

def validate_edit_range(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    file_path: str,
) -> EditValidation:
    """Validate that an edit to a frontend entity is safe.

    Checks:
      1. File has not changed since indexing (content hash)
      2. Source range is not ambiguous
      3. Entity does not share an unsafe range with unrelated syntax
      4. Entity was not only heuristically identified
      5. Parser recovery does not prevent trustworthy boundaries

    Args:
        conn: SQLite connection to the index database.
        entity_type: Type of entity ("markup_element", "css_rule", etc.)
        entity_id: ID of the entity in its table.
        file_path: Path to the file (project-relative or absolute).

    Returns:
        EditValidation with safe=True or safe=False + reason.
    """
    # 1. Fetch the entity
    entity = _get_entity_row(conn, entity_type, entity_id)
    if not entity:
        return EditValidation(
            safe=False,
            reason=f"Entity not found: {entity_type}#{entity_id}",
            entity_type=entity_type,
            entity_id=entity_id,
        )

    # 2. Get file info
    file_info = _get_file_info(conn, file_path)
    if not file_info:
        return EditValidation(
            safe=False,
            reason=f"File not found in index: {file_path}",
            file_path=file_path,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    # Resolve actual file path on disk
    actual_path = _resolve_file_path(file_info)
    if not actual_path or not os.path.exists(actual_path):
        return EditValidation(
            safe=False,
            reason=f"File does not exist on disk: {file_path}",
            file_path=file_path,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    # 3. Check file has not changed since indexing (content hash)
    current_hash = _compute_file_hash(actual_path)
    indexed_hash = file_info.get("content_hash")
    if indexed_hash and current_hash != indexed_hash:
        return EditValidation(
            safe=False,
            reason=(
                f"File has changed since indexing (indexed hash: {indexed_hash}, "
                f"current hash: {current_hash}). Re-index before editing."
            ),
            file_path=actual_path,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    # 4. Get source range
    source_range = _parse_json(entity["source_range"]) if "source_range" in entity.keys() else None
    if not source_range:
        return EditValidation(
            safe=False,
            reason=f"Entity has no source range recorded: {entity_type}#{entity_id}",
            file_path=actual_path,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    # 5. Check source range is not ambiguous
    start_line = source_range.get("start_line")
    end_line = source_range.get("end_line")
    if start_line is None or end_line is None:
        return EditValidation(
            safe=False,
            reason=f"Source range is missing line boundaries: {source_range}",
            file_path=actual_path,
            source_range=source_range,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    if end_line < start_line:
        return EditValidation(
            safe=False,
            reason=f"Source range is inverted (end < start): {source_range}",
            file_path=actual_path,
            source_range=source_range,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    # 6. Check entity was not only heuristically identified
    # For events and bindings, check resolution_status
    if entity_type == "event_binding" and "resolution_status" in entity.keys():
        status = entity["resolution_status"]
        if status == "heuristic":
            return EditValidation(
                safe=False,
                reason=f"Event binding was only heuristically identified (resolution_status='heuristic')",
                file_path=actual_path,
                source_range=source_range,
                entity_type=entity_type,
                entity_id=entity_id,
            )

    if entity_type == "property_binding" and "resolution_status" in entity.keys():
        status = entity["resolution_status"]
        if status == "heuristic":
            return EditValidation(
                safe=False,
                reason=f"Property binding was only heuristically identified (resolution_status='heuristic')",
                file_path=actual_path,
                source_range=source_range,
                entity_type=entity_type,
                entity_id=entity_id,
            )

    # For style_selector_matches, check match_type
    if entity_type == "css_rule" and "match_type" in entity.keys():
        match_type = entity["match_type"]
        if match_type == "heuristic":
            return EditValidation(
                safe=False,
                reason=f"CSS rule match was only heuristically identified (match_type='heuristic')",
                file_path=actual_path,
                source_range=source_range,
                entity_type=entity_type,
                entity_id=entity_id,
            )

    # 7. Check for parser recovery / diagnostics on this file
    file_id = file_info["id"]
    diagnostics = conn.execute(
        "SELECT severity, message, source_range FROM frontend_diagnostics WHERE file_id = ? AND severity = 'error'",
        (file_id,)
    ).fetchall()

    # Check if any error diagnostic overlaps with our entity's source range
    for diag in diagnostics:
        diag_range = _parse_json(diag["source_range"])
        if diag_range and _ranges_overlap(source_range, diag_range):
            return EditValidation(
                safe=False,
                reason=(
                    f"Parser recovery detected: file has error diagnostics overlapping "
                    f"this entity's source range. Message: {diag['message']}"
                ),
                file_path=actual_path,
                source_range=source_range,
                entity_type=entity_type,
                entity_id=entity_id,
            )

    # 8. Check entity does not share an unsafe range with unrelated syntax
    # For markup elements, check if the range is too broad (spans multiple elements)
    if entity_type in _MARKUP_ENTITY_TYPES:
        # Check if other markup elements share the same source range
        elem_file_id = entity["file_id"] if "file_id" in entity.keys() else None
        if elem_file_id:
            overlapping = conn.execute(
                """SELECT id, tag_name, element_type FROM markup_elements
                   WHERE file_id = ? AND id != ? AND source_range IS NOT NULL""",
                (elem_file_id, entity_id)
            ).fetchall()

            for other in overlapping:
                other_range = _parse_json(
                    conn.execute(
                        "SELECT source_range FROM markup_elements WHERE id = ?",
                        (other["id"],)
                    ).fetchone()["source_range"]
                )
                if other_range and _ranges_overlap(source_range, other_range):
                    # Overlap is expected for parent/child elements, but if the ranges
                    # are identical, that's ambiguous
                    if (source_range.get("start_line") == other_range.get("start_line") and
                            source_range.get("end_line") == other_range.get("end_line") and
                            source_range.get("start_column") == other_range.get("start_column") and
                            source_range.get("end_column") == other_range.get("end_column")):
                        return EditValidation(
                            safe=False,
                            reason=(
                                f"Source range is ambiguous: another markup element "
                                f"({other['tag_name']}#{other['id']}) has an identical range"
                            ),
                            file_path=actual_path,
                            source_range=source_range,
                            entity_type=entity_type,
                            entity_id=entity_id,
                        )

    # All checks passed
    return EditValidation(
        safe=True,
        file_path=actual_path,
        source_range=source_range,
        entity_type=entity_type,
        entity_id=entity_id,
    )


def _ranges_overlap(a: Dict[str, int], b: Dict[str, int]) -> bool:
    """Check if two source ranges overlap (line-based)."""
    a_start = a.get("start_line", 0)
    a_end = a.get("end_line", 0)
    b_start = b.get("start_line", 0)
    b_end = b.get("end_line", 0)
    return not (a_end < b_start or b_end < a_start)


# ──────────────────────────────────────────────────────────────
# apply_frontend_edit
# ──────────────────────────────────────────────────────────────

def apply_frontend_edit(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    new_source: str,
    file_path: str,
) -> EditResult:
    """Apply an edit to a frontend semantic entity.

    1. Validates the edit range (calls validate_edit_range)
    2. Reads current source text at the recorded range
    3. Replaces the source range with new text
    4. Verifies surrounding source is unchanged
    5. Returns diff + result

    Args:
        conn: SQLite connection to the index database.
        entity_type: Type of entity ("markup_element", "css_rule", etc.)
        entity_id: ID of the entity in its table.
        new_source: New source text to replace the entity's range with.
        file_path: Path to the file (project-relative or absolute).

    Returns:
        EditResult with success=True/False and details.
    """
    # 1. Validate
    validation = validate_edit_range(conn, entity_type, entity_id, file_path)
    if not validation.safe:
        return EditResult(
            success=False,
            reason=validation.reason,
            file_path=validation.file_path or file_path,
        )

    actual_path = validation.file_path
    source_range = validation.source_range

    # 2. Read the full file
    try:
        with open(actual_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return EditResult(
            success=False,
            reason=f"Failed to read file: {e}",
            file_path=actual_path,
        )

    lines = content.split("\n")
    start_line = source_range["start_line"]
    end_line = source_range["end_line"]

    # 3. Extract old source text
    old_lines = lines[start_line - 1:end_line]
    old_source = "\n".join(old_lines)

    # 4. Replace lines
    new_lines = new_source.split("\n")
    new_file_lines = lines[:start_line - 1] + new_lines + lines[end_line:]
    new_content = "\n".join(new_file_lines)

    # 5. Verify surrounding source is unchanged
    # Check lines before the edit
    before_old = lines[:start_line - 1]
    before_new = new_file_lines[:start_line - 1]
    if before_old != before_new:
        return EditResult(
            success=False,
            reason="Safety check failed: source before edit range was corrupted",
            file_path=actual_path,
            source_range=source_range,
        )

    # Check lines after the edit
    after_old = lines[end_line:]
    after_new = new_file_lines[start_line - 1 + len(new_lines):]
    if after_old != after_new:
        return EditResult(
            success=False,
            reason="Safety check failed: source after edit range was corrupted",
            file_path=actual_path,
            source_range=source_range,
        )

    # 6. Write the file (atomic-ish: write to temp then rename)
    try:
        tmp_path = actual_path + ".raggie_tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(tmp_path, actual_path)
    except Exception as e:
        # Clean up temp file if write failed
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return EditResult(
            success=False,
            reason=f"Failed to write file: {e}",
            file_path=actual_path,
            source_range=source_range,
        )

    # 7. Verify the file was written correctly
    try:
        with open(actual_path, "r", encoding="utf-8") as f:
            written = f.read()
        if written != new_content:
            return EditResult(
                success=False,
                reason="Write verification failed: file content does not match expected",
                file_path=actual_path,
                source_range=source_range,
            )
    except Exception as e:
        return EditResult(
            success=False,
            reason=f"Write verification failed: {e}",
            file_path=actual_path,
            source_range=source_range,
        )

    # 8. Build diff
    CONTEXT = 5
    ctx_start = max(0, start_line - 1 - CONTEXT)
    ctx_end = min(len(lines), end_line + CONTEXT)

    diff_lines = [
        f"@@ {actual_path}:{start_line}-{end_line} ({len(old_lines)} lines "
        f"-> {len(new_lines)} lines) @@",
    ]

    for i in range(ctx_start, start_line - 1):
        diff_lines.append(f"    {lines[i]}")

    for line in old_lines:
        diff_lines.append(f"  - {line}")

    for line in new_lines:
        diff_lines.append(f"  + {line}")

    for i in range(end_line, ctx_end):
        diff_lines.append(f"    {lines[i]}")

    diff_text = "\n".join(diff_lines)

    return EditResult(
        success=True,
        file_path=actual_path,
        old_source=old_source,
        new_source=new_source,
        diff=diff_text,
        source_range=source_range,
    )
