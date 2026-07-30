#!/usr/bin/env python3
"""
Data models for frontend semantic entities.
Dataclasses representing frontend entities stored in the SQLite index.
"""

import json
import sqlite3
from typing import List, Dict, Optional
from dataclasses import dataclass

from .models import Location


@dataclass
class FrontendComponent:
    """Recognized UI component (React function/arrow/class/forwardRef/memo)."""
    id: int
    file_id: int
    name: str
    framework: str = "react"
    source_range: Optional[Location] = None
    is_exported: bool = False
    impl_function_id: Optional[int] = None
    impl_class_id: Optional[int] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "FrontendComponent":
        sr = None
        if row["source_range"]:
            sr = Location.from_dict(json.loads(row["source_range"]))
        return cls(
            id=row["id"],
            file_id=row["file_id"],
            name=row["name"],
            framework=row["framework"],
            source_range=sr,
            is_exported=bool(row["is_exported"]),
            impl_function_id=row["impl_function_id"],
            impl_class_id=row["impl_class_id"],
        )


@dataclass
class MarkupElement:
    """Element in markup tree (HTML, JSX, fragment, template, expression, text)."""
    id: int
    file_id: int
    tag_name: str
    element_type: str
    component_id: Optional[int] = None
    parent_element_id: Optional[int] = None
    source_range: Optional[Location] = None
    element_id_attr: Optional[str] = None
    static_classes: Optional[List[str]] = None
    attributes: Optional[Dict] = None
    is_conditional: bool = False
    is_repeated: bool = False
    conditional_expr: Optional[str] = None
    repeated_expr: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "MarkupElement":
        sr = None
        if row["source_range"]:
            sr = Location.from_dict(json.loads(row["source_range"]))
        classes = None
        if row["static_classes"]:
            classes = json.loads(row["static_classes"])
        attrs = None
        if row["attributes"]:
            attrs = json.loads(row["attributes"])
        return cls(
            id=row["id"],
            file_id=row["file_id"],
            tag_name=row["tag_name"],
            element_type=row["element_type"],
            component_id=row["component_id"],
            parent_element_id=row["parent_element_id"],
            source_range=sr,
            element_id_attr=row["element_id_attr"],
            static_classes=classes,
            attributes=attrs,
            is_conditional=bool(row["is_conditional"]),
            is_repeated=bool(row["is_repeated"]),
            conditional_expr=row["conditional_expr"],
            repeated_expr=row["repeated_expr"],
        )


@dataclass
class StyleSelector:
    """CSS selector definition."""
    id: int
    file_id: int
    selector_text: str
    selector_type: str
    normalized_selector: Optional[str] = None
    source_range: Optional[Location] = None
    component_id: Optional[int] = None
    is_scoped: bool = False

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "StyleSelector":
        sr = None
        if row["source_range"]:
            sr = Location.from_dict(json.loads(row["source_range"]))
        return cls(
            id=row["id"],
            file_id=row["file_id"],
            selector_text=row["selector_text"],
            selector_type=row["selector_type"],
            normalized_selector=row["normalized_selector"],
            source_range=sr,
            component_id=row["component_id"],
            is_scoped=bool(row["is_scoped"]),
        )


@dataclass
class StyleCustomProperty:
    """CSS custom property definition (--name: value)."""
    id: int
    file_id: int
    name: str
    value: Optional[str] = None
    source_range: Optional[Location] = None
    scope_selector: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "StyleCustomProperty":
        sr = None
        if row["source_range"]:
            sr = Location.from_dict(json.loads(row["source_range"]))
        return cls(
            id=row["id"],
            file_id=row["file_id"],
            name=row["name"],
            value=row["value"],
            source_range=sr,
            scope_selector=row["scope_selector"],
        )


@dataclass
class StyleCustomPropertyUsage:
    """CSS custom property usage (var(--name))."""
    id: int
    file_id: int
    property_name: str
    source_range: Optional[Location] = None
    selector_id: Optional[int] = None
    resolved_property_id: Optional[int] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "StyleCustomPropertyUsage":
        sr = None
        if row["source_range"]:
            sr = Location.from_dict(json.loads(row["source_range"]))
        return cls(
            id=row["id"],
            file_id=row["file_id"],
            property_name=row["property_name"],
            source_range=sr,
            selector_id=row["selector_id"],
            resolved_property_id=row["resolved_property_id"],
        )


@dataclass
class StyleKeyframe:
    """Keyframe definition (@keyframes name)."""
    id: int
    file_id: int
    name: str
    source_range: Optional[Location] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "StyleKeyframe":
        sr = None
        if row["source_range"]:
            sr = Location.from_dict(json.loads(row["source_range"]))
        return cls(
            id=row["id"],
            file_id=row["file_id"],
            name=row["name"],
            source_range=sr,
        )


@dataclass
class StyleImport:
    """CSS/stylesheet import (@import, <link rel="stylesheet">, CSS module import)."""
    id: int
    file_id: int
    import_path: str
    is_external: bool = False
    resolved_file_id: Optional[int] = None
    source_range: Optional[Location] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "StyleImport":
        sr = None
        if row["source_range"]:
            sr = Location.from_dict(json.loads(row["source_range"]))
        return cls(
            id=row["id"],
            file_id=row["file_id"],
            import_path=row["import_path"],
            is_external=bool(row["is_external"]),
            resolved_file_id=row["resolved_file_id"],
            source_range=sr,
        )


@dataclass
class FrontendEvent:
    """Event handler binding (onclick, onClick, etc.)."""
    id: int
    file_id: int
    event_name: str
    handler_type: str
    element_id: Optional[int] = None
    handler_expression: Optional[str] = None
    handler_symbol_id: Optional[int] = None
    resolution_status: str = "unresolved"
    source_range: Optional[Location] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "FrontendEvent":
        sr = None
        if row["source_range"]:
            sr = Location.from_dict(json.loads(row["source_range"]))
        return cls(
            id=row["id"],
            file_id=row["file_id"],
            event_name=row["event_name"],
            handler_type=row["handler_type"],
            element_id=row["element_id"],
            handler_expression=row["handler_expression"],
            handler_symbol_id=row["handler_symbol_id"],
            resolution_status=row["resolution_status"],
            source_range=sr,
        )


@dataclass
class FrontendBinding:
    """Property/state binding (disabled={x}, className={cn(...)}, {title}, etc.)."""
    id: int
    file_id: int
    binding_type: str
    element_id: Optional[int] = None
    binding_name: Optional[str] = None
    binding_expression: Optional[str] = None
    resolution_status: str = "unresolved"
    source_range: Optional[Location] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "FrontendBinding":
        sr = None
        if row["source_range"]:
            sr = Location.from_dict(json.loads(row["source_range"]))
        return cls(
            id=row["id"],
            file_id=row["file_id"],
            binding_type=row["binding_type"],
            element_id=row["element_id"],
            binding_name=row["binding_name"],
            binding_expression=row["binding_expression"],
            resolution_status=row["resolution_status"],
            source_range=sr,
        )


@dataclass
class RenderRelationship:
    """Component render graph edge (parent renders child)."""
    id: int
    parent_component_id: int
    render_type: str
    child_component_id: Optional[int] = None
    child_component_name: Optional[str] = None
    child_element_id: Optional[int] = None
    controlling_expr: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "RenderRelationship":
        return cls(
            id=row["id"],
            parent_component_id=row["parent_component_id"],
            child_component_id=row["child_component_id"],
            child_component_name=row["child_component_name"],
            child_element_id=row["child_element_id"],
            render_type=row["render_type"],
            controlling_expr=row["controlling_expr"],
        )


@dataclass
class FrontendDiagnostic:
    """Extraction diagnostic for a frontend file."""
    id: int
    file_id: int
    diagnostic_type: str
    severity: str
    message: Optional[str] = None
    source_range: Optional[Location] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "FrontendDiagnostic":
        sr = None
        if row["source_range"]:
            sr = Location.from_dict(json.loads(row["source_range"]))
        return cls(
            id=row["id"],
            file_id=row["file_id"],
            diagnostic_type=row["diagnostic_type"],
            severity=row["severity"],
            message=row["message"],
            source_range=sr,
        )


@dataclass
class StyleSelectorMatch:
    """Pre-computed selector→element match for blast radius analysis."""
    id: int
    selector_id: int
    element_id: int
    match_type: str
    confidence: str = "high"
    source_range: Optional[Location] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "StyleSelectorMatch":
        sr = None
        if row["source_range"]:
            sr = Location.from_dict(json.loads(row["source_range"]))
        return cls(
            id=row["id"],
            selector_id=row["selector_id"],
            element_id=row["element_id"],
            match_type=row["match_type"],
            confidence=row["confidence"],
            source_range=sr,
        )
