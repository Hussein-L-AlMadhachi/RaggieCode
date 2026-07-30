#!/usr/bin/env python3
"""
HTML parser using tree-sitter.
Parses HTML source and builds a document tree of elements.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional

from indexing.language_config import LANGUAGE_CONFIG
from indexing.node_utils import create_parser
from indexing.frontend.source_location import SourceLocation, node_to_location, extract_range


@dataclass
class ParsedAttribute:
    name: str
    value: Optional[str]
    location: SourceLocation


@dataclass
class ParsedElement:
    tag_name: str
    element_type: str  # 'element', 'script_element', 'style_element'
    location: SourceLocation
    start_tag_location: SourceLocation
    attributes: List[ParsedAttribute] = field(default_factory=list)
    children: List["ParsedElement"] = field(default_factory=list)
    element_id_attr: Optional[str] = None
    static_classes: List[str] = field(default_factory=list)
    attributes_dict: Dict[str, str] = field(default_factory=dict)
    raw_text: Optional[str] = None  # for script/style content
    has_end_tag: bool = True
    parent: Optional["ParsedElement"] = None
    depth: int = 0


@dataclass
class HTMLDocument:
    elements: List[ParsedElement] = field(default_factory=list)
    scripts: List[ParsedElement] = field(default_factory=list)
    styles: List[ParsedElement] = field(default_factory=list)
    errors: List[Dict] = field(default_factory=list)
    source_bytes: bytes = b""


# Tags that are always void (no end tag expected)
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}


_html_parser = None

def _get_parser():
    """Get or create the HTML parser (cached)."""
    global _html_parser
    if _html_parser is None:
        lang_module = LANGUAGE_CONFIG.get("html", {}).get("language_module")
        if lang_module is None:
            return None
        _html_parser = create_parser(lang_module)
    return _html_parser


def _extract_attributes(start_tag_node, source_bytes) -> List[ParsedAttribute]:
    """Extract attributes from a start_tag node."""
    attrs = []
    for i in range(start_tag_node.child_count):
        child = start_tag_node.child(i)
        if child.type == "attribute":
            name = None
            value = None
            for j in range(child.child_count):
                ac = child.child(j)
                if ac.type == "attribute_name":
                    name = extract_range(source_bytes, ac.start_byte, ac.end_byte)
                elif ac.type == "quoted_attribute_value":
                    raw = extract_range(source_bytes, ac.start_byte, ac.end_byte)
                    if len(raw) >= 2 and raw[0] in ('"', "'") and raw[-1] == raw[0]:
                        value = raw[1:-1]
                    else:
                        value = raw
                elif ac.type == "attribute_value":
                    value = extract_range(source_bytes, ac.start_byte, ac.end_byte)
            if name:
                attrs.append(ParsedAttribute(
                    name=name,
                    value=value,
                    location=node_to_location(child),
                ))
    return attrs


def _parse_element(node, source_bytes, parent=None, depth=0) -> Optional[ParsedElement]:
    """Parse a tree-sitter element node into a ParsedElement.

    Iterative implementation using explicit stack to avoid recursion.
    """
    if node.type not in ("element", "script_element", "style_element"):
        return None

    # Stack entries: (ts_node, parent_elem, depth, children_list)
    # Returns the parsed element for each stack entry.
    root_elem = [None]
    stack = [(node, parent, depth, None)]

    while stack:
        ts_node, parent_elem, d, children_list = stack.pop()

        start_tag = None
        end_tag = None
        raw_text = None
        child_ts_nodes = []

        for i in range(ts_node.child_count):
            child = ts_node.child(i)
            if child.type == "start_tag":
                start_tag = child
            elif child.type == "end_tag":
                end_tag = child
            elif child.type == "raw_text":
                raw_text = extract_range(source_bytes, child.start_byte, child.end_byte)
            elif child.type in ("element", "script_element", "style_element"):
                child_ts_nodes.append(child)

        if start_tag is None:
            continue

        tag_name = ""
        for i in range(start_tag.child_count):
            c = start_tag.child(i)
            if c.type == "tag_name":
                tag_name = extract_range(source_bytes, c.start_byte, c.end_byte)
                break

        parsed_attrs = _extract_attributes(start_tag, source_bytes)
        attrs_dict = {}
        element_id = None
        classes = []
        for attr in parsed_attrs:
            attrs_dict[attr.name] = attr.value if attr.value is not None else ""
            if attr.name == "id":
                element_id = attr.value
            elif attr.name == "class":
                if attr.value:
                    classes = attr.value.split()

        elem = ParsedElement(
            tag_name=tag_name,
            element_type=ts_node.type,
            location=node_to_location(ts_node),
            start_tag_location=node_to_location(start_tag),
            attributes=parsed_attrs,
            attributes_dict=attrs_dict,
            element_id_attr=element_id,
            static_classes=classes,
            raw_text=raw_text,
            has_end_tag=end_tag is not None,
            parent=parent_elem,
            depth=d,
        )

        if children_list is not None:
            # This was a child being processed — add it to parent's children
            children_list.append(elem)

        if root_elem[0] is None and ts_node == node:
            root_elem[0] = elem

        # Push child TS nodes onto the stack for processing
        # We need a children list to collect parsed children
        elem_children = []
        elem.children = elem_children  # Will be filled as children are processed

        for child_ts in reversed(child_ts_nodes):
            stack.append((child_ts, elem, d + 1, elem_children))

    return root_elem[0]


def _collect_errors(node, source_bytes, errors: list):
    """Collect parse errors from the tree (iterative)."""
    if not node.has_error:
        if node.type == "ERROR":
            text = extract_range(source_bytes, node.start_byte, node.end_byte)[:80]
            errors.append({
                "type": "parse_error",
                "location": node_to_location(node).to_dict(),
                "text": text,
            })
        return

    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "ERROR":
            text = extract_range(source_bytes, n.start_byte, n.end_byte)[:80]
            errors.append({
                "type": "parse_error",
                "location": node_to_location(n).to_dict(),
                "text": text,
            })
        if n.has_error:
            for i in range(n.child_count):
                stack.append(n.child(i))


def _collect_from_error(error_node, source_bytes, doc: HTMLDocument):
    """Iteratively collect elements, scripts, and styles from an ERROR node."""
    stack = [error_node]
    while stack:
        n = stack.pop()
        error_children = []
        for i in range(n.child_count):
            child = n.child(i)
            if child.type in ("element", "script_element", "style_element"):
                elem = _parse_element(child, source_bytes)
                if elem:
                    if elem.element_type == "script_element":
                        doc.scripts.append(elem)
                    elif elem.element_type == "style_element":
                        doc.styles.append(elem)
                    else:
                        doc.elements.append(elem)
            elif child.type == "ERROR":
                error_children.append(child)
        # Push error children in reverse so earlier ones are processed first
        for child in reversed(error_children):
            stack.append(child)


def _flatten_elements(elem: ParsedElement, result: list):
    """Flatten element tree into a list (depth-first, iterative)."""
    stack = [elem]
    while stack:
        e = stack.pop()
        result.append(e)
        # Push children in reverse so leftmost is processed first
        for i in range(len(e.children) - 1, -1, -1):
            stack.append(e.children[i])


def parse_html(source_bytes: bytes) -> HTMLDocument:
    """Parse HTML source bytes and return an HTMLDocument.

    Args:
        source_bytes: Raw HTML file content as bytes.

    Returns:
        HTMLDocument with parsed elements, scripts, styles, and errors.
    """
    parser = _get_parser()
    if parser is None:
        return HTMLDocument(source_bytes=source_bytes, errors=[{
            "type": "missing_parser",
            "message": "HTML tree-sitter grammar not available",
        }])

    tree = parser.parse(source_bytes)
    root = tree.root_node

    doc = HTMLDocument(source_bytes=source_bytes)

    # Collect parse errors
    if root.has_error:
        _collect_errors(root, source_bytes, doc.errors)

    # Walk top-level nodes (including ERROR nodes for malformed HTML recovery)
    for i in range(root.child_count):
        child = root.child(i)
        if child.type in ("element", "script_element", "style_element"):
            elem = _parse_element(child, source_bytes)
            if elem:
                if elem.element_type == "script_element":
                    doc.scripts.append(elem)
                elif elem.element_type == "style_element":
                    doc.styles.append(elem)
                else:
                    doc.elements.append(elem)
        elif child.type == "doctype":
            pass  # Skip doctype
        elif child.type == "ERROR":
            # Malformed HTML: recurse into ERROR node to find parseable elements
            _collect_from_error(child, source_bytes, doc)

    # Also collect nested scripts and styles from within elements
    all_elements = []
    for elem in doc.elements:
        _flatten_elements(elem, all_elements)

    for elem in all_elements:
        for child in elem.children:
            if child.element_type == "script_element" and child not in doc.scripts:
                doc.scripts.append(child)
            elif child.element_type == "style_element" and child not in doc.styles:
                doc.styles.append(child)

    return doc


def get_all_elements(doc: HTMLDocument) -> List[ParsedElement]:
    """Get all elements (including scripts and styles) as a flat list."""
    result = []
    for elem in doc.elements:
        _flatten_elements(elem, result)
    # Scripts and styles that are top-level (not nested in elements)
    for elem in doc.scripts:
        if elem.parent is None:
            result.append(elem)
    for elem in doc.styles:
        if elem.parent is None:
            result.append(elem)
    return result
