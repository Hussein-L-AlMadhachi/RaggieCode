#!/usr/bin/env python3
"""
Shared helpers for single-file-component (SFC) extractors (Vue, Svelte).

Both frameworks compile a single file containing template markup, <script>
blocks, and <style> blocks. This module provides the common data structures
and utilities: element representation, attribute helpers, import scanning,
style-block processing, and handler classification.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from indexing.frontend.source_location import SourceLocation, node_to_location, extract_range
from indexing.frontend.html_parser import ParsedElement
from indexing.frontend.html_extractor import _parse_style_block, _compute_selector_matches


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_$][\w$]*$")
MEMBER_EXPR_PATTERN = re.compile(r"^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)+$")

# Import statement scanning (regex-based; the script AST is parsed separately
# by parse_worker, this only feeds component-tag classification)
IMPORT_CLAUSE_PATTERN = re.compile(r"import\s+(?:type\s+)?([^'\"]+?)\s+from\s+['\"]")
DEFAULT_IMPORT_PATTERN = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*(?:,|$)")
NAMESPACE_IMPORT_PATTERN = re.compile(r"\*\s+as\s+([A-Za-z_$][\w$]*)")
NAMED_IMPORTS_PATTERN = re.compile(r"\{([^}]*)\}")

# CSS languages the simple style-block parser can handle
SUPPORTED_STYLE_LANGS = {"", "css", "postcss"}


@dataclass
class SFCElement:
    """A template element in an SFC.

    Duck-compatible with html_parser.ParsedElement for the attribute-based
    selector matching helpers (tag_name, static_classes, element_id_attr,
    location).
    """
    tag_name: str
    element_type: str  # 'native', 'custom_component', 'expression'
    location: SourceLocation
    parent_index: Optional[int] = None
    element_id_attr: Optional[str] = None
    static_classes: List[str] = field(default_factory=list)
    attributes: Dict[str, str] = field(default_factory=dict)
    is_conditional: bool = False
    is_repeated: bool = False
    conditional_expr: Optional[str] = None
    repeated_expr: Optional[str] = None
    expression_text: Optional[str] = None


def find_child(node, *types):
    """Return the first direct child of node matching any of the given types."""
    for i in range(node.child_count):
        child = node.child(i)
        if child.type in types:
            return child
    return None


def get_tag_name(tag_node, source_bytes: bytes) -> str:
    """Extract the tag name from a start_tag/self_closing_tag node."""
    name_node = find_child(tag_node, "tag_name")
    if name_node is not None:
        return extract_range(source_bytes, name_node.start_byte, name_node.end_byte)
    return ""


def get_attribute_value(value_node, source_bytes: bytes) -> Optional[str]:
    """Extract the string value from a quoted_attribute_value/attribute_value node."""
    if value_node is None:
        return None
    if value_node.type == "quoted_attribute_value":
        inner = find_child(value_node, "attribute_value")
        if inner is not None:
            return extract_range(source_bytes, inner.start_byte, inner.end_byte)
        return ""
    if value_node.type == "attribute_value":
        return extract_range(source_bytes, value_node.start_byte, value_node.end_byte)
    return None


def get_block_attributes(start_tag_node, source_bytes: bytes) -> Dict[str, Optional[str]]:
    """Extract plain attributes from a <script>/<style> start tag."""
    attrs = {}
    for i in range(start_tag_node.child_count):
        child = start_tag_node.child(i)
        if child.type != "attribute":
            continue
        name_node = find_child(child, "attribute_name")
        if name_node is None:
            continue
        name = extract_range(source_bytes, name_node.start_byte, name_node.end_byte)
        value_node = find_child(child, "quoted_attribute_value", "attribute_value")
        attrs[name] = get_attribute_value(value_node, source_bytes)
    return attrs


def script_parser_language(lang_attr: Optional[str]) -> Optional[str]:
    """Map a <script lang="..."> attribute to an indexer language name.

    Returns None for languages we cannot parse (the caller should emit a
    diagnostic instead of guessing).
    """
    lang = (lang_attr or "").strip().lower()
    if lang in ("", "js", "javascript", "jsx"):
        return "javascript"
    if lang in ("ts", "typescript"):
        return "typescript"
    if lang == "tsx":
        return "tsx"
    return None


def scan_imported_names(script_text: str) -> set:
    """Scan script source for local import binding names.

    Used to classify component tags in templates (e.g. <MyButton /> or
    kebab-case <my-button>) against the components the script imports.
    """
    names = set()
    for match in IMPORT_CLAUSE_PATTERN.finditer(script_text):
        clause = match.group(1)
        ns = NAMESPACE_IMPORT_PATTERN.search(clause)
        if ns:
            names.add(ns.group(1))
        named = NAMED_IMPORTS_PATTERN.search(clause)
        if named:
            for part in named.group(1).split(","):
                part = part.strip()
                if not part:
                    continue
                # handle "Original as Alias"
                alias = part.split(" as ")[-1].strip()
                if IDENTIFIER_PATTERN.match(alias):
                    names.add(alias)
        default = DEFAULT_IMPORT_PATTERN.match(clause)
        if default:
            names.add(default.group(1))
    return names


def kebab_to_pascal(name: str) -> str:
    """Convert kebab-case to PascalCase (my-button -> MyButton)."""
    return "".join(part.capitalize() for part in name.split("-") if part)


def is_component_tag(tag_name: str, imported_names: set) -> bool:
    """Classify whether a template tag refers to a custom component."""
    if not tag_name:
        return False
    if tag_name[0].isupper():
        return True
    if tag_name in imported_names:
        return True
    if "-" in tag_name and kebab_to_pascal(tag_name) in imported_names:
        return True
    return False


def classify_handler(expression: Optional[str]) -> Tuple[str, str]:
    """Classify an event handler expression.

    Returns:
        (handler_type, resolution_status) where handler_type is one of
        'direct' (plain identifier), 'member' (member expression), or
        'inline' (anything else), and resolution_status is 'inferred'
        for resolvable-looking references, else 'unresolved'.
    """
    expr = (expression or "").strip()
    if IDENTIFIER_PATTERN.match(expr):
        return "direct", "inferred"
    if MEMBER_EXPR_PATTERN.match(expr):
        return "member", "inferred"
    return "inline", "unresolved"


def classify_binding(expression: Optional[str]) -> str:
    """Resolution status for a binding expression."""
    expr = (expression or "").strip()
    if IDENTIFIER_PATTERN.match(expr) or MEMBER_EXPR_PATTERN.match(expr):
        return "inferred"
    return "unresolved"


def process_style_block(raw_text: str, location: SourceLocation, is_scoped: bool,
                        source_bytes: bytes) -> Tuple[list, list, list]:
    """Parse an SFC <style> block reusing the HTML style-block parser.

    Returns:
        (selector_dicts, custom_properties, custom_property_usages) where
        selector_dicts have keys selector_text/normalized_selector/
        selector_type/source_range/is_scoped plus a private '_match_info'
        entry carrying (text, type, location) for selector matching.
    """
    shim = ParsedElement(
        tag_name="style",
        element_type="style_element",
        location=location,
        start_tag_location=location,
        raw_text=raw_text,
    )
    selectors, custom_props, prop_usages = _parse_style_block(shim, source_bytes)

    selector_dicts = []
    for sel in selectors:
        selector_dicts.append({
            "selector_text": sel["text"],
            "normalized_selector": sel["text"],
            "selector_type": sel["type"],
            "source_range": sel["location"].to_dict(),
            "is_scoped": is_scoped,
            "_match_info": sel,
        })
    return selector_dicts, custom_props, prop_usages


def build_style_selector_matches(selector_dicts: list, elements: List[SFCElement]) -> list:
    """Compute static selector→element matches for style-block selectors.

    Args:
        selector_dicts: selector dicts as returned by process_style_block
            (their position in this list is the selector_index).
        elements: flat list of template elements.

    Returns:
        List of match dicts with selector_index/element_index/match_type/
        confidence/source_range.
    """
    all_elements = [(el, el.parent_index) for el in elements]
    matches = []
    for sel_idx, sel_dict in enumerate(selector_dicts):
        for match in _compute_selector_matches(sel_dict["_match_info"], all_elements):
            matches.append({
                "selector_index": sel_idx,
                "element_index": match["element_index"],
                "match_type": "static",
                "confidence": "high",
                "source_range": match["location"].to_dict(),
            })
    return matches


def empty_sfc_result() -> dict:
    """Result skeleton shared by the SFC extractors."""
    return {
        "frontend_components": [],
        "markup_elements": [],
        "frontend_events": [],
        "frontend_bindings": [],
        "render_relationships": [],
        "style_selectors": [],
        "style_custom_properties": [],
        "style_custom_property_usages": [],
        "style_imports": [],
        "style_selector_matches": [],
        "frontend_diagnostics": [],
        "inline_scripts": [],
        "inline_styles": [],
    }


def element_to_markup_dict(el: SFCElement, index: int, component_index: Optional[int]) -> dict:
    """Convert an SFCElement to the markup_elements dict shape."""
    return {
        "tag_name": el.tag_name,
        "element_type": el.element_type,
        "source_range": el.location.to_dict(),
        "component_index": component_index,
        "parent_index": el.parent_index,
        "element_id_attr": el.element_id_attr,
        "static_classes": el.static_classes if el.static_classes else None,
        "attributes": el.attributes if el.attributes else None,
        "is_conditional": el.is_conditional,
        "is_repeated": el.is_repeated,
        "conditional_expr": el.conditional_expr,
        "repeated_expr": el.repeated_expr,
        "expression_text": el.expression_text,
    }
