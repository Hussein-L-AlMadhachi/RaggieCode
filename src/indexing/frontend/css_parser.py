#!/usr/bin/env python3
"""
CSS parser using tree-sitter.
Parses CSS source and builds a document of rule sets, at-rules, and declarations.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional

from indexing.language_config import LANGUAGE_CONFIG
from indexing.node_utils import create_parser
from indexing.frontend.source_location import SourceLocation, node_to_location, extract_range


@dataclass
class ParsedDeclaration:
    property_name: str
    value: str
    location: SourceLocation
    is_custom_property: bool = False


@dataclass
class ParsedSelector:
    text: str
    selector_type: str
    location: SourceLocation


@dataclass
class ParsedRuleSet:
    selectors: List[ParsedSelector] = field(default_factory=list)
    declarations: List[ParsedDeclaration] = field(default_factory=list)
    location: SourceLocation = None
    media_query: Optional[str] = None


@dataclass
class ParsedKeyframe:
    stop: str
    declarations: List[ParsedDeclaration] = field(default_factory=list)
    location: SourceLocation = None


@dataclass
class ParsedKeyframes:
    name: str
    keyframes: List[ParsedKeyframe] = field(default_factory=list)
    location: SourceLocation = None


@dataclass
class ParsedImport:
    import_path: str
    location: SourceLocation
    is_url: bool = False


@dataclass
class CSSDocument:
    rule_sets: List[ParsedRuleSet] = field(default_factory=list)
    keyframes: List[ParsedKeyframes] = field(default_factory=list)
    imports: List[ParsedImport] = field(default_factory=list)
    media_rules: List[ParsedRuleSet] = field(default_factory=list)
    errors: List[Dict] = field(default_factory=list)
    source_bytes: bytes = b""


_css_parser = None

def _get_parser():
    """Get or create the CSS parser (cached)."""
    global _css_parser
    if _css_parser is None:
        lang_module = LANGUAGE_CONFIG.get("css", {}).get("language_module")
        if lang_module is None:
            return None
        _css_parser = create_parser(lang_module)
    return _css_parser


def _classify_selector(selector_text: str) -> str:
    """Classify a CSS selector into a type."""
    s = selector_text.strip()
    if not s:
        return "unknown"
    # Check complex patterns first before simple prefix checks
    if ">" in s or "+" in s or "~" in s:
        return "combinator"
    if " " in s:
        return "descendant"
    if s.startswith("["):
        return "attribute"
    if s.startswith(":"):
        return "pseudo"
    if s.startswith("@"):
        return "at-rule"
    # Attribute selectors like a[href=...] — tag with attribute
    if "[" in s and s[0].isalpha():
        return "attribute"
    if "." in s and "#" in s:
        return "compound"
    if s.startswith("#"):
        return "id"
    if s.startswith("."):
        return "class"
    if "." in s or "#" in s or ":" in s:
        return "compound"
    if s and s[0].isalpha():
        return "tag"
    return "unknown"


def _extract_selectors(selectors_node, source_bytes) -> List[ParsedSelector]:
    """Extract selectors from a selectors node."""
    selectors = []
    if selectors_node is None:
        return selectors

    # The selectors node may contain comma-separated selectors
    # Each child is a selector node (class_selector, id_selector, etc.)
    # Comma tokens separate them
    current_text = ""
    current_start = None

    for i in range(selectors_node.child_count):
        child = selectors_node.child(i)
        child_text = extract_range(source_bytes, child.start_byte, child.end_byte)

        if child.type == ",":
            if current_text.strip():
                selectors.append(ParsedSelector(
                    text=current_text.strip(),
                    selector_type=_classify_selector(current_text),
                    location=SourceLocation(
                        start_line=0, start_column=0, end_line=0, end_column=0,
                        start_byte=current_start if current_start else 0,
                        end_byte=child.start_byte,
                    ),
                ))
            current_text = ""
            current_start = None
        else:
            if not current_text:
                current_start = child.start_byte
            current_text += child_text

    # Don't forget the last selector
    if current_text.strip():
        selectors.append(ParsedSelector(
            text=current_text.strip(),
            selector_type=_classify_selector(current_text),
            location=SourceLocation(
                start_line=0, start_column=0, end_line=0, end_column=0,
                start_byte=current_start if current_start else 0,
                end_byte=selectors_node.end_byte,
            ),
        ))

    # Fix up locations using the selectors node
    # Precompute line-start offsets once to avoid quadratic per-selector scanning
    line_starts = [0]
    for j in range(len(source_bytes)):
        if source_bytes[j] == 0x0A:
            line_starts.append(j + 1)

    import bisect
    for sel in selectors:
        if sel.location.start_byte is not None:
            # Find the actual text in the source to get proper line/col
            sel_text_bytes = sel.text.encode("utf-8")
            offset = source_bytes.find(sel_text_bytes, sel.location.start_byte)
            if offset >= 0:
                # Compute line/col from byte offset using precomputed line starts
                line_idx = bisect.bisect_right(line_starts, offset) - 1
                line = line_idx + 1
                col = offset - line_starts[line_idx]
                sel.location.start_line = line
                sel.location.start_column = col
                sel.location.end_line = line
                sel.location.end_column = col + len(sel_text_bytes)

    return selectors


def _extract_declarations(block_node, source_bytes) -> List[ParsedDeclaration]:
    """Extract declarations from a block node."""
    declarations = []
    if block_node is None:
        return declarations

    for i in range(block_node.child_count):
        child = block_node.child(i)
        if child.type == "declaration":
            prop_name = None
            value_parts = []
            for j in range(child.child_count):
                dc = child.child(j)
                if dc.type == "property_name":
                    prop_name = extract_range(source_bytes, dc.start_byte, dc.end_byte)
                elif dc.type in ("color_value", "plain_value", "integer_value", "float_value",
                                 "string_value", "unit", "identifier", "call_expression",
                                 "binary_expression", "grid_value", "flex_value"):
                    value_parts.append(extract_range(source_bytes, dc.start_byte, dc.end_byte))
                elif dc.type == ";":
                    pass

            if prop_name:
                value = " ".join(value_parts) if value_parts else ""
                is_custom = prop_name.startswith("--")
                declarations.append(ParsedDeclaration(
                    property_name=prop_name,
                    value=value,
                    location=node_to_location(child),
                    is_custom_property=is_custom,
                ))
        elif child.type == "last_declaration" or (child.type == "declaration" and not child.child_by_field_name("property_name")):
            # Handle declarations without trailing semicolon
            pass

    return declarations


def _parse_rule_set(node, source_bytes, media_query=None) -> ParsedRuleSet:
    """Parse a rule_set node."""
    rule = ParsedRuleSet(
        location=node_to_location(node),
        media_query=media_query,
    )

    for i in range(node.child_count):
        child = node.child(i)
        if child.type == "selectors":
            rule.selectors = _extract_selectors(child, source_bytes)
        elif child.type == "block":
            rule.declarations = _extract_declarations(child, source_bytes)

    return rule


def _parse_keyframes(node, source_bytes) -> ParsedKeyframes:
    """Parse a keyframes_statement node."""
    kf = ParsedKeyframes(location=node_to_location(node), name="")

    for i in range(node.child_count):
        child = node.child(i)
        if child.type == "keyframes_name":
            kf.name = extract_range(source_bytes, child.start_byte, child.end_byte)
        elif child.type == "keyframe_block_list":
            for j in range(child.child_count):
                kf_child = child.child(j)
                if kf_child.type == "keyframe_block":
                    stop = ""
                    block = None
                    for k in range(kf_child.child_count):
                        kc = kf_child.child(k)
                        if kc.type in ("integer_value", "from", "to"):
                            stop = extract_range(source_bytes, kc.start_byte, kc.end_byte)
                        elif kc.type == "block":
                            block = kc
                    decls = _extract_declarations(block, source_bytes) if block else []
                    kf.keyframes.append(ParsedKeyframe(
                        stop=stop,
                        declarations=decls,
                        location=node_to_location(kf_child),
                    ))

    return kf


def _parse_import(node, source_bytes) -> Optional[ParsedImport]:
    """Parse an import_statement node."""
    for i in range(node.child_count):
        child = node.child(i)
        if child.type == "call_expression":
            # @import url('path')
            for j in range(child.child_count):
                cc = child.child(j)
                if cc.type == "arguments":
                    for k in range(cc.child_count):
                        arg = cc.child(k)
                        if arg.type == "string_value":
                            path = extract_range(source_bytes, arg.start_byte, arg.end_byte)
                            path = path.strip("'\"")
                            return ParsedImport(
                                import_path=path,
                                location=node_to_location(node),
                                is_url=True,
                            )
        elif child.type == "string_value":
            # @import "path";
            path = extract_range(source_bytes, child.start_byte, child.end_byte)
            path = path.strip("'\"")
            return ParsedImport(
                import_path=path,
                location=node_to_location(node),
                is_url=False,
            )
    return None


def _parse_media(node, source_bytes) -> List[ParsedRuleSet]:
    """Parse a media_statement node, returning nested rule sets."""
    media_query = ""
    rules = []

    for i in range(node.child_count):
        child = node.child(i)
        if child.type == "feature_query":
            media_query = extract_range(source_bytes, child.start_byte, child.end_byte)
        elif child.type == "block":
            for j in range(child.child_count):
                bc = child.child(j)
                if bc.type == "rule_set":
                    rule = _parse_rule_set(bc, source_bytes, media_query=media_query)
                    rules.append(rule)

    return rules


def _collect_errors(node, source_bytes, errors: list):
    """Collect parse errors from the tree (iterative)."""
    if not node.has_error and node.type != "ERROR":
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


def parse_css(source_bytes: bytes) -> CSSDocument:
    """Parse CSS source bytes and return a CSSDocument.

    Args:
        source_bytes: Raw CSS file content as bytes.

    Returns:
        CSSDocument with parsed rule sets, keyframes, imports, and errors.
    """
    parser = _get_parser()
    if parser is None:
        return CSSDocument(source_bytes=source_bytes, errors=[{
            "type": "missing_parser",
            "message": "CSS tree-sitter grammar not available",
        }])

    tree = parser.parse(source_bytes)
    root = tree.root_node

    doc = CSSDocument(source_bytes=source_bytes)

    if root.has_error:
        _collect_errors(root, source_bytes, doc.errors)

    for i in range(root.child_count):
        child = root.child(i)
        if child.type == "rule_set":
            doc.rule_sets.append(_parse_rule_set(child, source_bytes))
        elif child.type == "keyframes_statement":
            doc.keyframes.append(_parse_keyframes(child, source_bytes))
        elif child.type == "import_statement":
            imp = _parse_import(child, source_bytes)
            if imp:
                doc.imports.append(imp)
        elif child.type == "media_statement":
            media_rules = _parse_media(child, source_bytes)
            doc.media_rules.extend(media_rules)
        elif child.type == "comment":
            pass
        elif child.type == "ERROR":
            # Try to find rule sets inside ERROR nodes for malformed CSS recovery
            for j in range(child.child_count):
                ec = child.child(j)
                if ec.type == "rule_set":
                    doc.rule_sets.append(_parse_rule_set(ec, source_bytes))

    return doc
