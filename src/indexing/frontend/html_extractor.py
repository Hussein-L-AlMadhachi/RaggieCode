#!/usr/bin/env python3
"""
HTML semantic extractor.
Extracts markup elements, scripts, styles, events, and selector matches from parsed HTML.
"""

import json
import re
from typing import Dict, List, Optional, Tuple

from indexing.frontend.html_parser import (
    HTMLDocument, ParsedElement, parse_html, get_all_elements, VOID_TAGS
)
from indexing.frontend.source_location import SourceLocation, node_to_location, extract_range


# Event handler attributes (on* attributes)
EVENT_ATTR_PATTERN = re.compile(r"^on([a-z]+)$", re.IGNORECASE)

# Simple CSS selector parsing for static matching
# Matches: .classname, #id, tagname
CLASS_SELECTOR_PATTERN = re.compile(r"\.([a-zA-Z_][\w-]*)")
ID_SELECTOR_PATTERN = re.compile(r"#([a-zA-Z_][\w-]*)")
TAG_SELECTOR_PATTERN = re.compile(r"^([a-zA-Z][\w-]*)$")


def extract_html_semantics(source_bytes: bytes, config=None) -> dict:
    """Extract all semantic entities from an HTML file.

    Args:
        source_bytes: Raw HTML file content as bytes.
        config: Optional FrontendConfig instance for extraction limits.

    Returns:
        dict with keys:
            - markup_elements: list of element dicts
            - frontend_events: list of event handler dicts
            - style_selectors: list of selector dicts (from <style> blocks)
            - style_custom_properties: list of custom property dicts
            - style_custom_property_usages: list of var() usage dicts
            - style_imports: list of stylesheet link dicts
            - style_selector_matches: list of selector→element match dicts
            - frontend_diagnostics: list of diagnostic dicts
            - inline_scripts: list of script dicts (for JS parsing)
            - inline_styles: list of style block dicts (for CSS parsing)
    """
    parse_scripts = config.parse_inline_scripts if config else True
    parse_styles = config.parse_inline_styles if config else True
    include_text = config.include_text_nodes if config else False
    doc = parse_html(source_bytes)

    result = {
        "markup_elements": [],
        "frontend_events": [],
        "style_selectors": [],
        "style_custom_properties": [],
        "style_custom_property_usages": [],
        "style_imports": [],
        "style_selector_matches": [],
        "frontend_diagnostics": [],
        "inline_scripts": [],
        "inline_styles": [],
    }

    # Collect all elements (flat list with depth info)
    all_elements = []
    _collect_all_elements(doc.elements, all_elements, parent_idx=None)

    # Filter out text nodes if config says so
    if not include_text:
        all_elements = [(e, p) for e, p in all_elements if e.element_type != "text"]

    # Assign indices and build markup_elements
    elem_index_map = {}  # id(ParsedElement) -> index in markup_elements list
    for i, (elem, parent_idx) in enumerate(all_elements):
        elem_index_map[id(elem)] = i
        result["markup_elements"].append(_element_to_dict(elem, i, parent_idx))

    # Extract events from all elements
    for i, (elem, parent_idx) in enumerate(all_elements):
        _extract_events_from_element(elem, i, result["frontend_events"])

    # Process <style> blocks — extract selectors and custom properties
    style_selectors_list = []
    for style_elem in doc.styles:
        selectors, custom_props, prop_usages = _parse_style_block(style_elem, source_bytes)
        for sel in selectors:
            sel_dict = {
                "selector_text": sel["text"],
                "normalized_selector": sel["text"],
                "selector_type": sel["type"],
                "source_range": sel["location"].to_dict(),
            }
            result["style_selectors"].append(sel_dict)
            style_selectors_list.append((len(result["style_selectors"]) - 1, sel))

        for cp in custom_props:
            result["style_custom_properties"].append(cp)

        for pu in prop_usages:
            result["style_custom_property_usages"].append(pu)

        # Record inline style block for potential CSS parsing
        if parse_styles:
            result["inline_styles"].append({
                "content": style_elem.raw_text or "",
                "location": style_elem.location.to_dict(),
            })

    # Process <script> elements
    if parse_scripts:
        for script_elem in doc.scripts:
            script_type = script_elem.attributes_dict.get("type", "")
            src = script_elem.attributes_dict.get("src")

            if src:
                # External script
                result["inline_scripts"].append({
                    "type": "external",
                    "src": src,
                    "script_type": script_type,
                    "location": script_elem.location.to_dict(),
                })
            elif script_type in ("", "text/javascript", "application/javascript", "module"):
                # Inline JS script
                result["inline_scripts"].append({
                    "type": "inline",
                    "content": script_elem.raw_text or "",
                    "script_type": script_type,
                    "location": script_elem.location.to_dict(),
                })
            elif script_type == "application/ld+json":
                # JSON-LD — skip for semantic extraction
                result["frontend_diagnostics"].append({
                    "diagnostic_type": "unsupported_script_type",
                    "severity": "unsupported",
                    "message": f"Script type '{script_type}' is not parsed for semantics",
                    "source_range": script_elem.location.to_dict(),
                })
            else:
                result["frontend_diagnostics"].append({
                    "diagnostic_type": "unsupported_script_type",
                    "severity": "unsupported",
                    "message": f"Script type '{script_type}' is not parsed for semantics",
                    "source_range": script_elem.location.to_dict(),
                })

    # Process <link rel="stylesheet"> as style imports
    for i, (elem, parent_idx) in enumerate(all_elements):
        if elem.tag_name == "link":
            rel = elem.attributes_dict.get("rel", "")
            if "stylesheet" in rel.lower():
                href = elem.attributes_dict.get("href", "")
                is_external = href.startswith(("http://", "https://", "//"))
                result["style_imports"].append({
                    "import_path": href,
                    "is_external": is_external,
                    "source_range": elem.location.to_dict(),
                })
                # Diagnose unresolved local stylesheet
                if not is_external and not href:
                    result["frontend_diagnostics"].append({
                        "diagnostic_type": "unresolved_stylesheet",
                        "severity": "unresolved",
                        "message": "Stylesheet link has empty href",
                        "source_range": elem.location.to_dict(),
                    })

    # Process inline styles (style="..." attributes) as custom property usages
    for i, (elem, parent_idx) in enumerate(all_elements):
        inline_style = elem.attributes_dict.get("style")
        if inline_style:
            usages = _extract_var_usages(inline_style, elem.location)
            for u in usages:
                u["element_index"] = i
                result["style_custom_property_usages"].append(u)

    # Compute selector→element matches for static selectors from <style> blocks
    for sel_idx, sel_info in style_selectors_list:
        matches = _compute_selector_matches(sel_info, all_elements)
        for match in matches:
            result["style_selector_matches"].append({
                "selector_index": sel_idx,
                "element_index": match["element_index"],
                "match_type": "static",
                "confidence": "high",
                "source_range": match["location"].to_dict(),
            })

    # Add diagnostics for parse errors
    for err in doc.errors:
        result["frontend_diagnostics"].append({
            "diagnostic_type": "malformed_html",
            "severity": "recoverable",
            "message": f"Parse error near: {err.get('text', '')[:50]}",
            "source_range": err.get("location"),
        })

    # Parser recovery: errors occurred but elements were still extracted
    if doc.errors and len(all_elements) > 0:
        result["frontend_diagnostics"].append({
            "diagnostic_type": "parser_recovery",
            "severity": "recoverable",
            "message": f"HTML parser recovered from {len(doc.errors)} error(s), extracted {len(all_elements)} element(s)",
        })

    # Add diagnostics for unclosed elements
    for i, (elem, parent_idx) in enumerate(all_elements):
        if not elem.has_end_tag and elem.tag_name not in VOID_TAGS and elem.element_type == "element":
            result["frontend_diagnostics"].append({
                "diagnostic_type": "unclosed_element",
                "severity": "recoverable",
                "message": f"Element <{elem.tag_name}> has no closing tag",
                "source_range": elem.location.to_dict(),
            })

    return result


def _collect_all_elements(elements: List[ParsedElement], result: list, parent_idx: Optional[int]):
    """Iteratively collect all elements as (element, parent_index) tuples."""
    # Stack entries: (element_list, parent_idx)
    stack = [(elements, parent_idx)]
    while stack:
        elem_list, p_idx = stack.pop()
        for elem in elem_list:
            idx = len(result)
            result.append((elem, p_idx))
            child_elements = [c for c in elem.children if c.element_type == "element"]
            if child_elements:
                stack.append((child_elements, idx))


def _element_to_dict(elem: ParsedElement, index: int, parent_index: Optional[int]) -> dict:
    """Convert a ParsedElement to a serializable dict for markup_elements."""
    attrs_dict = {}
    for attr in elem.attributes:
        attrs_dict[attr.name] = attr.value if attr.value is not None else ""

    return {
        "tag_name": elem.tag_name,
        "element_type": "native",
        "source_range": elem.location.to_dict(),
        "element_id_attr": elem.element_id_attr,
        "static_classes": elem.static_classes if elem.static_classes else None,
        "attributes": attrs_dict if attrs_dict else None,
        "parent_index": parent_index,
        "is_conditional": False,
        "is_repeated": False,
    }


def _extract_events_from_element(elem: ParsedElement, elem_index: int, events: list):
    """Extract inline event handlers from an element's attributes."""
    for attr in elem.attributes:
        match = EVENT_ATTR_PATTERN.match(attr.name)
        if match:
            event_name = match.group(1).lower()
            events.append({
                "element_index": elem_index,
                "event_name": event_name,
                "handler_type": "inline",
                "handler_expression": attr.value or "",
                "resolution_status": "unresolved",
                "source_range": attr.location.to_dict(),
            })


def _parse_style_block(style_elem: ParsedElement, source_bytes: bytes) -> Tuple[list, list, list]:
    """Parse a <style> block and extract selectors, custom properties, and var() usages.

    Returns:
        (selectors, custom_properties, custom_property_usages)
    """
    css_text = style_elem.raw_text or ""
    if not css_text.strip():
        return [], [], []

    selectors = []
    custom_properties = []
    property_usages = []

    # Simple CSS parsing: extract rule sets and custom property definitions
    # This is a basic parser — Phase 4 will add full CSS extraction
    _parse_css_rules(css_text, style_elem.location, selectors, custom_properties, property_usages)

    return selectors, custom_properties, property_usages


def _parse_css_rules(css_text: str, block_location: SourceLocation,
                     selectors: list, custom_properties: list, property_usages: list):
    """Parse CSS text for selectors, custom properties, and var() usages.

    This is a basic parser for <style> blocks. Full CSS extraction is Phase 4.
    """
    # Remove comments
    css_clean = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)

    # Find rule sets: selector { declarations }
    # Simple approach: find { and } pairs
    pos = 0
    while pos < len(css_clean):
        brace_start = css_clean.find("{", pos)
        if brace_start == -1:
            break
        brace_end = css_clean.find("}", brace_start)
        if brace_end == -1:
            break

        selector_text = css_clean[pos:brace_start].strip()
        declarations = css_clean[brace_start + 1:brace_end]

        if selector_text:
            # Split comma-separated selectors
            for sel in selector_text.split(","):
                sel = sel.strip()
                if not sel:
                    continue

                sel_type = _classify_selector(sel)
                # Compute location within the style block, accounting for newlines
                sel_offset = css_clean.find(sel, pos)
                if sel_offset >= 0:
                    # Count newlines before sel_offset to get line/column within CSS text
                    text_before = css_clean[:sel_offset]
                    css_line = text_before.count("\n")
                    # Column = distance from last newline to sel_offset
                    last_nl = text_before.rfind("\n")
                    css_col = sel_offset - (last_nl + 1) if last_nl >= 0 else sel_offset

                    # For the end, count newlines within the selector text itself
                    sel_text_newlines = sel.count("\n")
                    if sel_text_newlines > 0:
                        last_nl_in_sel = sel.rfind("\n")
                        end_col = len(sel) - (last_nl_in_sel + 1)
                    else:
                        end_col = css_col + len(sel)

                    sel_location = SourceLocation(
                        start_line=block_location.start_line + css_line,
                        start_column=css_col if css_line > 0 else block_location.start_column + css_col,
                        end_line=block_location.start_line + css_line + sel_text_newlines,
                        end_column=end_col if sel_text_newlines > 0 or css_line > 0 else block_location.start_column + end_col,
                    )
                else:
                    sel_location = SourceLocation(
                        start_line=block_location.start_line,
                        start_column=0,
                        end_line=block_location.start_line,
                        end_column=0,
                    )

                selectors.append({
                    "text": sel,
                    "type": sel_type,
                    "location": sel_location,
                })

                # Check for custom property definitions in declarations
                decl_block_start = brace_start + 1  # offset in css_clean
                for decl in declarations.split(";"):
                    decl = decl.strip()
                    if not decl:
                        continue
                    # Find this declaration's position within css_clean
                    decl_offset = css_clean.find(decl, decl_block_start)
                    if decl_offset >= 0:
                        text_before_decl = css_clean[:decl_offset]
                        decl_line = text_before_decl.count("\n")
                        last_nl_d = text_before_decl.rfind("\n")
                        decl_col = decl_offset - (last_nl_d + 1) if last_nl_d >= 0 else decl_offset
                        decl_location = SourceLocation(
                            start_line=block_location.start_line + decl_line,
                            start_column=decl_col if decl_line > 0 else block_location.start_column + decl_col,
                            end_line=block_location.start_line + decl_line,
                            end_column=(decl_col + len(decl)) if decl_line > 0 else block_location.start_column + decl_col + len(decl),
                        )
                        decl_block_start = decl_offset + len(decl)
                    else:
                        decl_location = sel_location

                    if decl.startswith("--"):
                        parts = decl.split(":", 1)
                        if len(parts) == 2:
                            name = parts[0].strip()
                            value = parts[1].strip()
                            custom_properties.append({
                                "name": name,
                                "value": value,
                                "scope_selector": sel,
                                "source_range": decl_location.to_dict(),
                            })

                    # Check for var() usages
                    var_usages = _extract_var_usages(decl, decl_location)
                    for vu in var_usages:
                        vu["selector_text"] = sel
                        property_usages.append(vu)

        pos = brace_end + 1


def _classify_selector(selector: str) -> str:
    """Classify a CSS selector into a type."""
    selector = selector.strip()
    if selector.startswith("#"):
        return "id"
    elif selector.startswith("."):
        return "class"
    elif selector.startswith(":"):
        return "pseudo"
    elif selector.startswith("["):
        return "attribute"
    elif selector.startswith("@"):
        return "at-rule"
    elif TAG_SELECTOR_PATTERN.match(selector):
        return "tag"
    elif "." in selector or "#" in selector or ":" in selector or "[" in selector:
        return "compound"
    else:
        return "unknown"


def _extract_var_usages(text: str, location: SourceLocation) -> list:
    """Extract var(--name) usages from CSS text."""
    usages = []
    var_pattern = re.compile(r"var\(\s*(--[\w-]+)\s*[^)]*\)")
    for match in var_pattern.finditer(text):
        usages.append({
            "property_name": match.group(1),
            "source_range": location.to_dict(),
        })
    return usages


def _compute_selector_matches(sel_info: dict, all_elements: list) -> list:
    """Compute which elements match a given CSS selector (static matching only).

    Handles: tag selectors, .class selectors, #id selectors, and compound selectors.
    """
    selector = sel_info["text"]
    sel_type = sel_info["type"]
    matches = []

    if sel_type == "tag":
        tag_name = selector.strip()
        for i, (elem, parent_idx) in enumerate(all_elements):
            if elem.tag_name.lower() == tag_name.lower():
                matches.append({
                    "element_index": i,
                    "location": elem.location,
                })

    elif sel_type == "class":
        class_names = CLASS_SELECTOR_PATTERN.findall(selector)
        for i, (elem, parent_idx) in enumerate(all_elements):
            if all(cn in elem.static_classes for cn in class_names):
                matches.append({
                    "element_index": i,
                    "location": elem.location,
                })

    elif sel_type == "id":
        id_name = ID_SELECTOR_PATTERN.findall(selector)
        if id_name:
            for i, (elem, parent_idx) in enumerate(all_elements):
                if elem.element_id_attr == id_name[0]:
                    matches.append({
                        "element_index": i,
                        "location": elem.location,
                    })

    elif sel_type == "compound":
        # Parse compound selector: e.g., "div.container#main"
        tag = None
        classes = CLASS_SELECTOR_PATTERN.findall(selector)
        ids = ID_SELECTOR_PATTERN.findall(selector)

        # Extract tag name if present
        compound_tag_match = re.match(r"^([a-zA-Z][\w-]*)", selector)
        if compound_tag_match:
            tag = compound_tag_match.group(1)

        for i, (elem, parent_idx) in enumerate(all_elements):
            if tag and elem.tag_name.lower() != tag.lower():
                continue
            if classes and not all(cn in elem.static_classes for cn in classes):
                continue
            if ids and elem.element_id_attr not in ids:
                continue
            matches.append({
                "element_index": i,
                "location": elem.location,
            })

    return matches
