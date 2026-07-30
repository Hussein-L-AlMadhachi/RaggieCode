#!/usr/bin/env python3
"""
JSX/TSX semantic extractor.
Extracts React component definitions, markup trees, events, bindings,
render relationships, and selector matches from JSX/TSX files.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from indexing.language_config import LANGUAGE_CONFIG
from indexing.node_utils import create_parser
from indexing.frontend.source_location import SourceLocation, node_to_location, extract_range


# Event handler attributes
EVENT_ATTR_PATTERN = re.compile(r"^on([A-Z][a-zA-Z]*)$")

# Known wrapper functions that wrap components
WRAPPER_FUNCTIONS = {"memo", "forwardRef", "connect", "withRouter", "observer"}

# Known non-component capitalized identifiers (built-in React APIs)
NON_COMPONENT_CAPS = {"React", "Fragment", "Suspense", "StrictMode", "Profiler",
                      "Children", "createElement", "cloneElement", "isValidElement",
                      "createRef", "createContext", "createFactory", "lazy", "Component",
                      "PureComponent"}


@dataclass
class JSXComponent:
    name: str
    component_type: str  # 'function', 'arrow', 'class', 'memo', 'forwardRef'
    location: SourceLocation
    is_exported: bool = False
    is_default_export: bool = False
    impl_function_name: Optional[str] = None
    impl_class_name: Optional[str] = None
    wrapper_name: Optional[str] = None  # e.g. 'memo', 'forwardRef'


@dataclass
class JSXMarkupElement:
    tag_name: str
    element_type: str  # 'native', 'custom_component', 'fragment', 'expression', 'text'
    location: SourceLocation
    component_index: Optional[int] = None  # which component this belongs to
    parent_index: Optional[int] = None
    element_id_attr: Optional[str] = None
    static_classes: List[str] = field(default_factory=list)
    attributes: Dict[str, str] = field(default_factory=dict)
    is_conditional: bool = False
    is_repeated: bool = False
    conditional_expr: Optional[str] = None
    repeated_expr: Optional[str] = None
    expression_text: Optional[str] = None  # for expression elements
    class_expression: Optional[str] = None  # for dynamic className expressions


@dataclass
class JSXEvent:
    component_index: int
    element_index: int
    event_name: str
    handler_type: str  # 'direct', 'inline', 'member'
    handler_expression: str
    resolution_status: str  # 'exact', 'inferred', 'unresolved'
    location: SourceLocation


@dataclass
class JSXBinding:
    component_index: int
    element_index: int
    binding_name: str
    binding_type: str  # 'property', 'ref', 'spread', 'style'
    expression: str
    resolution_status: str
    location: SourceLocation


@dataclass
class JSXRenderRelationship:
    parent_component_index: int
    child_component_name: str
    render_type: str  # 'direct', 'conditional', 'repeated'
    element_index: int


@dataclass
class JSXDocument:
    components: List[JSXComponent] = field(default_factory=list)
    markup_elements: List[JSXMarkupElement] = field(default_factory=list)
    events: List[JSXEvent] = field(default_factory=list)
    bindings: List[JSXBinding] = field(default_factory=list)
    render_relationships: List[JSXRenderRelationship] = field(default_factory=list)
    selector_matches: List[dict] = field(default_factory=list)
    diagnostics: List[dict] = field(default_factory=list)
    source_bytes: bytes = b""


_jsx_parsers = {}

def _get_parser(language):
    """Get or create a parser for the given language (cached per process)."""
    if language not in _jsx_parsers:
        lang_module = LANGUAGE_CONFIG.get(language, {}).get("language_module")
        if lang_module is None:
            _jsx_parsers[language] = None
        else:
            _jsx_parsers[language] = create_parser(lang_module)
    return _jsx_parsers[language]


def _has_jsx_nodes(root_node) -> bool:
    """Check if the AST contains any JSX nodes."""
    stack = [root_node]
    while stack:
        node = stack.pop()
        if node.type.startswith("jsx_"):
            return True
        for i in range(node.child_count):
            stack.append(node.child(i))
    return False


def _get_function_name(func_node, source_bytes) -> Optional[str]:
    """Extract the name from a function/arrow function node by looking at parent."""
    parent = func_node.parent
    if parent is None:
        return None

    # function_declaration has identifier child
    if func_node.type == "function_declaration":
        for i in range(func_node.child_count):
            c = func_node.child(i)
            if c.type in ("identifier", "type_identifier"):
                return extract_range(source_bytes, c.start_byte, c.end_byte)

    # class_declaration has type_identifier child
    if func_node.type == "class_declaration":
        for i in range(func_node.child_count):
            c = func_node.child(i)
            if c.type in ("identifier", "type_identifier"):
                return extract_range(source_bytes, c.start_byte, c.end_byte)

    # Arrow function or function expression — name is in parent variable_declarator
    if func_node.type in ("arrow_function", "function_expression", "function"):
        if parent.type == "variable_declarator":
            for i in range(parent.child_count):
                c = parent.child(i)
                if c.type in ("identifier", "type_identifier"):
                    return extract_range(source_bytes, c.start_byte, c.end_byte)
        # Named function expression: function Inner() { ... }
        if func_node.type == "function_expression":
            for i in range(func_node.child_count):
                c = func_node.child(i)
                if c.type == "identifier":
                    return extract_range(source_bytes, c.start_byte, c.end_byte)

    return None


def _is_exported(func_node) -> Tuple[bool, bool]:
    """Check if a function/component is exported (and default)."""
    parent = func_node.parent
    while parent:
        if parent.type == "export_statement":
            for i in range(parent.child_count):
                c = parent.child(i)
                if c.type == "default":
                    return (True, True)
            return (True, False)
        if parent.type == "lexical_declaration":
            grandparent = parent.parent
            if grandparent and grandparent.type == "export_statement":
                for i in range(grandparent.child_count):
                    c = grandparent.child(i)
                    if c.type == "default":
                        return (True, True)
                return (True, False)
        parent = parent.parent
    return (False, False)


def _function_returns_jsx(func_node, source_bytes) -> bool:
    """Check if a function/arrow function returns JSX."""
    # Look for return statements containing JSX, or arrow with direct JSX body
    stack = [func_node]
    while stack:
        node = stack.pop()
        if node.type == "return_statement":
            # Check if return contains JSX
            for i in range(node.child_count):
                c = node.child(i)
                if c.type.startswith("jsx_"):
                    return True
                # Check inside parenthesized_expression
                if c.type == "parenthesized_expression":
                    for j in range(c.child_count):
                        cc = c.child(j)
                        if cc.type.startswith("jsx_"):
                            return True
                        # Deeper nesting
                        stack2 = [cc]
                        while stack2:
                            n2 = stack2.pop()
                            if n2.type.startswith("jsx_"):
                                return True
                            for k in range(n2.child_count):
                                stack2.append(n2.child(k))
        # Arrow function with expression body (no statement_block)
        if node.type == "arrow_function" and node != func_node:
            pass  # Don't recurse into nested arrows
        for i in range(node.child_count):
            child = node.child(i)
            if child.type == "statement_block":
                # Look inside the block for returns
                for j in range(child.child_count):
                    stack.append(child.child(j))
            elif child.type.startswith("jsx_") and func_node.type == "arrow_function":
                # Arrow function with direct JSX return
                return True

    # Also check if arrow function body is directly JSX
    if func_node.type == "arrow_function":
        found_arrow = False
        for i in range(func_node.child_count):
            c = func_node.child(i)
            if c.type == "=>":
                found_arrow = True
                continue
            if found_arrow and c.type.startswith("jsx_"):
                return True
            if found_arrow and c.type == "parenthesized_expression":
                for j in range(c.child_count):
                    cc = c.child(j)
                    if cc.type.startswith("jsx_"):
                        return True

    return False


def _detect_wrapper(func_node, source_bytes) -> Optional[str]:
    """Detect if a function is wrapped in memo(), forwardRef(), etc."""
    parent = func_node.parent
    if parent and parent.type == "arguments":
        grandparent = parent.parent
        if grandparent and grandparent.type == "call_expression":
            for i in range(grandparent.child_count):
                c = grandparent.child(i)
                if c.type == "function_name" or c.type == "identifier":
                    name = extract_range(source_bytes, c.start_byte, c.end_byte)
                    if name in WRAPPER_FUNCTIONS:
                        return name
                if c.type == "member_expression":
                    name = extract_range(source_bytes, c.start_byte, c.end_byte)
                    parts = name.rsplit(".", 1)
                    if len(parts) == 2 and parts[1] in WRAPPER_FUNCTIONS:
                        return parts[1]
    return None


def _find_components(root_node, source_bytes) -> Tuple[List[JSXComponent], Dict[str, object]]:
    """Find all React component definitions in the AST.

    Returns (components, node_map) where node_map maps target_name -> AST node
    so callers can avoid re-traversing the tree per component.
    """
    components = []
    node_map = {}  # target_name -> AST node

    stack = [root_node]
    while stack:
        node = stack.pop()

        if node.type == "function_declaration":
            name = _get_function_name(node, source_bytes)
            if name and name[0].isupper() and name not in NON_COMPONENT_CAPS:
                if _function_returns_jsx(node, source_bytes):
                    is_exp, is_default = _is_exported(node)
                    components.append(JSXComponent(
                        name=name,
                        component_type="function",
                        location=node_to_location(node),
                        is_exported=is_exp,
                        is_default_export=is_default,
                        impl_function_name=name,
                    ))
                    node_map[name] = node

        elif node.type in ("arrow_function", "function_expression"):
            name = _get_function_name(node, source_bytes)
            if name and name[0].isupper() and name not in NON_COMPONENT_CAPS:
                if _function_returns_jsx(node, source_bytes):
                    wrapper = _detect_wrapper(node, source_bytes)
                    ctype = "arrow"
                    if wrapper:
                        ctype = wrapper
                    is_exp, is_default = _is_exported(node)
                    components.append(JSXComponent(
                        name=name,
                        component_type=ctype,
                        location=node_to_location(node),
                        is_exported=is_exp,
                        is_default_export=is_default,
                        impl_function_name=name,
                        wrapper_name=wrapper,
                    ))
                    node_map[name] = node

        # Class declarations (React.Component)
        elif node.type == "class_declaration":
            name = _get_function_name(node, source_bytes)
            if name and name[0].isupper():
                # Check if extends React.Component or similar
                has_react_base = False
                for i in range(node.child_count):
                    c = node.child(i)
                    if c.type in ("class_heritage", "extends_clause"):
                        text = extract_range(source_bytes, c.start_byte, c.end_byte)
                        if "Component" in text or "PureComponent" in text:
                            has_react_base = True
                        # Also check nested extends_clause inside class_heritage
                        for j in range(c.child_count):
                            cc = c.child(j)
                            if cc.type == "extends_clause":
                                text2 = extract_range(source_bytes, cc.start_byte, cc.end_byte)
                                if "Component" in text2 or "PureComponent" in text2:
                                    has_react_base = True
                if has_react_base:
                    is_exp, is_default = _is_exported(node)
                    components.append(JSXComponent(
                        name=name,
                        component_type="class",
                        location=node_to_location(node),
                        is_exported=is_exp,
                        is_default_export=is_default,
                        impl_class_name=name,
                    ))
                    node_map[name] = node

        for i in range(node.child_count):
            stack.append(node.child(i))

    return components, node_map


def _get_jsx_tag_name(opening_node, source_bytes) -> str:
    """Extract the tag name from a jsx_opening_element or jsx_self_closing_element."""
    for i in range(opening_node.child_count):
        c = opening_node.child(i)
        if c.type == "identifier":
            return extract_range(source_bytes, c.start_byte, c.end_byte)
        if c.type == "member_expression":
            return extract_range(source_bytes, c.start_byte, c.end_byte)
        if c.type == "namespace_function":
            return extract_range(source_bytes, c.start_byte, c.end_byte)
    return ""


def _is_custom_component(tag_name: str) -> bool:
    """Check if a tag name represents a custom component (capitalized)."""
    if not tag_name:
        return False
    # Member expressions like Card.Sub — check first part
    first_part = tag_name.split(".")[0]
    return first_part[0].isupper() if first_part else False


def _extract_jsx_attributes(opening_node, source_bytes) -> List[dict]:
    """Extract JSX attributes from an opening element node."""
    attrs = []
    for i in range(opening_node.child_count):
        c = opening_node.child(i)
        if c.type == "jsx_attribute":
            attr_name = None
            attr_value_node = None
            for j in range(c.child_count):
                cc = c.child(j)
                if cc.type == "property_identifier":
                    attr_name = extract_range(source_bytes, cc.start_byte, cc.end_byte)
                elif cc.type == "string":
                    raw = extract_range(source_bytes, cc.start_byte, cc.end_byte)
                    if len(raw) >= 2 and raw[0] in ('"', "'") and raw[-1] == raw[0]:
                        attr_value_node = ("string", raw[1:-1])
                elif cc.type == "jsx_expression":
                    # Expression attribute
                    expr_text = ""
                    for k in range(cc.child_count):
                        ec = cc.child(k)
                        if ec.type not in ("{", "}"):
                            expr_text += extract_range(source_bytes, ec.start_byte, ec.end_byte)
                    attr_value_node = ("expression", expr_text.strip())
            if attr_name:
                attrs.append({
                    "name": attr_name,
                    "value": attr_value_node,
                    "location": node_to_location(c),
                })

        # Spread attributes: {...props}
        if c.type == "jsx_expression":
            for j in range(c.child_count):
                cc = c.child(j)
                if cc.type == "spread_element":
                    attrs.append({
                        "name": "...spread",
                        "value": ("spread", extract_range(source_bytes, cc.start_byte, cc.end_byte)),
                        "location": node_to_location(c),
                    })

    return attrs


def _extract_class_names(attr_value, source_bytes) -> Tuple[List[str], str, str]:
    """Extract static class names from a className attribute value.

    Returns: (static_classes, resolution_status, expression_text)
    """
    if attr_value is None:
        return [], "unresolved", ""

    value_type, value_text = attr_value

    if value_type == "string":
        # Static string: "card primary"
        return value_text.split(), "exact", value_text

    if value_type == "expression":
        # Check for different expression types
        expr = value_text.strip()

        # CSS module reference: styles.className
        if "." in expr and not expr.startswith("(") and not expr.startswith("cn"):
            parts = expr.split(".")
            if len(parts) == 2 and parts[0].isidentifier():
                return [], "unresolved", expr  # CSS module — Phase 6 resolution

        # Ternary: cond ? 'a' : 'b' — dynamic, not static
        if "?" in expr and ":" in expr:
            return [], "unresolved", expr

        # Function call: cn('btn', loading && 'loading') — dynamic, not static
        if "(" in expr and ")" in expr:
            return [], "unresolved", expr

        # Template literal: `btn ${variant}`
        if expr.startswith("`"):
            static_parts = re.findall(r"([a-zA-Z][\w-]*)", expr)
            return static_parts, "unresolved", expr

        return [], "unresolved", expr

    return [], "unresolved", ""


def _process_jsx_element_node(node, source_bytes, component_index, parent_index,
                              markup_elements, events, bindings, render_relationships,
                              components, conditional, repeated, conditional_expr, repeated_expr):
    """Process a single jsx_element or jsx_self_closing_element node.

    Returns a list of child nodes to push onto the walk stack.
    """
    children_to_walk = []

    if node.type == "jsx_element":
        opening = None
        children_nodes = []

        for i in range(node.child_count):
            c = node.child(i)
            if c.type == "jsx_opening_element":
                opening = c
            elif c.type == "jsx_closing_element":
                pass
            else:
                children_nodes.append(c)

        if opening is None:
            return []

        tag_name = _get_jsx_tag_name(opening, source_bytes)
        is_custom = _is_custom_component(tag_name)
        elem_type = "custom_component" if is_custom else "native"

        if tag_name == "" and opening.child_count == 2:
            types = [opening.child(i).type for i in range(opening.child_count)]
            if "<" in types and ">" in types:
                elem_type = "fragment"
                tag_name = "Fragment"

        attrs = _extract_jsx_attributes(opening, source_bytes)

        element_id = None
        static_classes = []
        class_resolution = "exact"
        class_expr = ""
        class_expression = None
        attrs_dict = {}

        elem_index = len(markup_elements)

        for attr in attrs:
            attr_name = attr["name"]
            attr_value = attr["value"]

            if attr_name == "id" and attr_value and attr_value[0] == "string":
                element_id = attr_value[1]
                attrs_dict["id"] = attr_value[1]
            elif attr_name in ("className", "class"):
                classes, resolution, expr = _extract_class_names(attr_value, source_bytes)
                static_classes = classes
                class_resolution = resolution
                class_expr = expr
                class_expression = expr if resolution != "exact" else None
                if attr_value:
                    attrs_dict[attr_name] = attr_value[1] if attr_value[0] == "string" else expr
            elif attr_name == "style":
                if attr_value and attr_value[0] == "expression":
                    bindings.append(JSXBinding(
                        component_index=component_index,
                        element_index=elem_index,
                        binding_name="style",
                        binding_type="style",
                        expression=attr_value[1],
                        resolution_status="unresolved",
                        location=attr["location"],
                    ))
            elif attr_name == "ref":
                if attr_value:
                    bindings.append(JSXBinding(
                        component_index=component_index,
                        element_index=elem_index,
                        binding_name="ref",
                        binding_type="ref",
                        expression=attr_value[1] if attr_value[0] == "expression" else attr_value[1],
                        resolution_status="unresolved",
                        location=attr["location"],
                    ))
            elif attr_name == "...spread":
                bindings.append(JSXBinding(
                    component_index=component_index,
                    element_index=elem_index,
                    binding_name="...props",
                    binding_type="spread",
                    expression=attr_value[1] if attr_value else "",
                    resolution_status="unresolved",
                    location=attr["location"],
                ))
            else:
                event_match = EVENT_ATTR_PATTERN.match(attr_name)
                if event_match and attr_value:
                    event_name = event_match.group(1).lower()
                    handler_expr = attr_value[1] if attr_value[0] == "expression" else attr_value[1]

                    handler_type = "direct"
                    resolution = "exact"
                    if attr_value[0] == "expression":
                        expr = attr_value[1].strip()
                        if expr.startswith("()") or expr.startswith("("):
                            handler_type = "inline"
                            resolution = "inferred"
                        elif "." in expr and "(" not in expr:
                            handler_type = "member"
                            resolution = "inferred"
                        elif expr.isidentifier():
                            handler_type = "direct"
                            resolution = "exact"
                        else:
                            handler_type = "inline"
                            resolution = "inferred"

                    events.append(JSXEvent(
                        component_index=component_index,
                        element_index=elem_index,
                        event_name=event_name,
                        handler_type=handler_type,
                        handler_expression=handler_expr,
                        resolution_status=resolution,
                        location=attr["location"],
                    ))
                elif attr_value:
                    bindings.append(JSXBinding(
                        component_index=component_index,
                        element_index=elem_index,
                        binding_name=attr_name,
                        binding_type="property",
                        expression=attr_value[1] if attr_value[0] == "expression" else attr_value[1],
                        resolution_status="exact" if attr_value[0] == "string" else "unresolved",
                        location=attr["location"],
                    ))

            if attr_name not in ("id", "className", "class", "style", "ref", "...spread"):
                if attr_value:
                    attrs_dict[attr_name] = attr_value[1] if attr_value[0] == "string" else (attr_value[1] if attr_value[0] == "expression" else "")

        markup_elem = JSXMarkupElement(
            tag_name=tag_name,
            element_type=elem_type,
            location=node_to_location(node),
            component_index=component_index,
            parent_index=parent_index,
            element_id_attr=element_id,
            static_classes=static_classes,
            attributes=attrs_dict,
            is_conditional=conditional,
            is_repeated=repeated,
            conditional_expr=conditional_expr,
            repeated_expr=repeated_expr,
            class_expression=class_expression,
        )
        markup_elements.append(markup_elem)

        if is_custom:
            render_type = "conditional" if conditional else ("repeated" if repeated else "direct")
            render_relationships.append(JSXRenderRelationship(
                parent_component_index=component_index,
                child_component_name=tag_name,
                render_type=render_type,
                element_index=elem_index,
            ))

        for child in children_nodes:
            if child.type in ("jsx_element", "jsx_self_closing_element", "jsx_expression"):
                children_to_walk.append((child, elem_index, False, False, None, None))
            elif child.type == "jsx_text":
                text = extract_range(source_bytes, child.start_byte, child.end_byte).strip()
                if text:
                    markup_elements.append(JSXMarkupElement(
                        tag_name="#text",
                        element_type="text",
                        location=node_to_location(child),
                        component_index=component_index,
                        parent_index=elem_index,
                        expression_text=text,
                    ))

    elif node.type == "jsx_self_closing_element":
        tag_name = _get_jsx_tag_name(node, source_bytes)
        is_custom = _is_custom_component(tag_name)
        elem_type = "custom_component" if is_custom else "native"

        attrs = _extract_jsx_attributes(node, source_bytes)

        element_id = None
        static_classes = []
        class_expression = None
        attrs_dict = {}

        elem_index = len(markup_elements)

        for attr in attrs:
            attr_name = attr["name"]
            attr_value = attr["value"]

            if attr_name == "id" and attr_value and attr_value[0] == "string":
                element_id = attr_value[1]
                attrs_dict["id"] = attr_value[1]
            elif attr_name in ("className", "class"):
                classes, resolution, expr = _extract_class_names(attr_value, source_bytes)
                static_classes = classes
                class_expression = expr if resolution != "exact" else None
                if attr_value:
                    attrs_dict[attr_name] = attr_value[1] if attr_value[0] == "string" else expr
            elif attr_name == "style":
                if attr_value and attr_value[0] == "expression":
                    bindings.append(JSXBinding(
                        component_index=component_index,
                        element_index=elem_index,
                        binding_name="style",
                        binding_type="style",
                        expression=attr_value[1],
                        resolution_status="unresolved",
                        location=attr["location"],
                    ))
            elif attr_name == "ref":
                if attr_value:
                    bindings.append(JSXBinding(
                        component_index=component_index,
                        element_index=elem_index,
                        binding_name="ref",
                        binding_type="ref",
                        expression=attr_value[1] if attr_value[0] == "expression" else attr_value[1],
                        resolution_status="unresolved",
                        location=attr["location"],
                    ))
            elif attr_name == "...spread":
                bindings.append(JSXBinding(
                    component_index=component_index,
                    element_index=elem_index,
                    binding_name="...props",
                    binding_type="spread",
                    expression=attr_value[1] if attr_value else "",
                    resolution_status="unresolved",
                    location=attr["location"],
                ))
            else:
                event_match = EVENT_ATTR_PATTERN.match(attr_name)
                if event_match and attr_value:
                    event_name = event_match.group(1).lower()
                    handler_expr = attr_value[1] if attr_value[0] == "expression" else attr_value[1]
                    handler_type = "direct"
                    resolution = "exact"
                    if attr_value[0] == "expression":
                        expr = attr_value[1].strip()
                        if expr.startswith("()") or expr.startswith("("):
                            handler_type = "inline"
                            resolution = "inferred"
                        elif "." in expr and "(" not in expr:
                            handler_type = "member"
                            resolution = "inferred"
                        elif expr.isidentifier():
                            handler_type = "direct"
                            resolution = "exact"
                        else:
                            handler_type = "inline"
                            resolution = "inferred"

                    events.append(JSXEvent(
                        component_index=component_index,
                        element_index=elem_index,
                        event_name=event_name,
                        handler_type=handler_type,
                        handler_expression=handler_expr,
                        resolution_status=resolution,
                        location=attr["location"],
                    ))
                elif attr_value:
                    bindings.append(JSXBinding(
                        component_index=component_index,
                        element_index=elem_index,
                        binding_name=attr_name,
                        binding_type="property",
                        expression=attr_value[1] if attr_value[0] == "expression" else attr_value[1],
                        resolution_status="exact" if attr_value[0] == "string" else "unresolved",
                        location=attr["location"],
                    ))

            if attr_name not in ("id", "className", "class", "style", "ref", "...spread"):
                if attr_value:
                    attrs_dict[attr_name] = attr_value[1] if attr_value[0] == "string" else (attr_value[1] if attr_value[0] == "expression" else "")

        markup_elem = JSXMarkupElement(
            tag_name=tag_name,
            element_type=elem_type,
            location=node_to_location(node),
            component_index=component_index,
            parent_index=parent_index,
            element_id_attr=element_id,
            static_classes=static_classes,
            attributes=attrs_dict,
            is_conditional=conditional,
            is_repeated=repeated,
            conditional_expr=conditional_expr,
            repeated_expr=repeated_expr,
            class_expression=class_expression,
        )
        markup_elements.append(markup_elem)

        if is_custom:
            render_type = "conditional" if conditional else ("repeated" if repeated else "direct")
            render_relationships.append(JSXRenderRelationship(
                parent_component_index=component_index,
                child_component_name=tag_name,
                render_type=render_type,
                element_index=elem_index,
            ))

    return children_to_walk


def _process_jsx_expression_node(node, source_bytes, component_index, parent_index,
                                 markup_elements, events, bindings, render_relationships,
                                 components):
    """Process a jsx_expression node, detecting conditional/repeated rendering.

    Returns a list of child nodes to push onto the walk stack.
    """
    children_to_walk = []

    expr_node = None
    for i in range(node.child_count):
        c = node.child(i)
        if c.type not in ("{", "}"):
            expr_node = c
            break

    if expr_node is None:
        return []

    expr_text = extract_range(source_bytes, expr_node.start_byte, expr_node.end_byte)

    if expr_node.type == "binary_expression" and "&&" in expr_text:
        for i in range(expr_node.child_count):
            c = expr_node.child(i)
            if c.type.startswith("jsx_"):
                cond_expr = expr_text.split("&&")[0].strip()
                children_to_walk.append((c, parent_index, True, False, cond_expr, None))

    elif expr_node.type == "ternary_expression":
        cond_expr = None
        for i in range(expr_node.child_count):
            c = expr_node.child(i)
            if c.type == "?":
                cond_expr = extract_range(source_bytes, expr_node.start_byte, c.start_byte).strip()
            if c.type.startswith("jsx_"):
                children_to_walk.append((c, parent_index, True, False, cond_expr, None))

    elif expr_node.type == "call_expression":
        is_map = False
        for i in range(expr_node.child_count):
            c = expr_node.child(i)
            if c.type == "member_expression":
                member_text = extract_range(source_bytes, c.start_byte, c.end_byte)
                if ".map" in member_text:
                    is_map = True

        if is_map:
            for i in range(expr_node.child_count):
                c = expr_node.child(i)
                if c.type == "arguments":
                    for j in range(c.child_count):
                        arg = c.child(j)
                        stack = [arg]
                        while stack:
                            n = stack.pop()
                            if n.type.startswith("jsx_"):
                                children_to_walk.append((n, parent_index, False, True, None, expr_text))
                            for k in range(n.child_count):
                                stack.append(n.child(k))
        else:
            markup_elements.append(JSXMarkupElement(
                tag_name="#expression",
                element_type="expression",
                location=node_to_location(node),
                component_index=component_index,
                parent_index=parent_index,
                expression_text=expr_text,
            ))

    else:
        markup_elements.append(JSXMarkupElement(
            tag_name="#expression",
            element_type="expression",
            location=node_to_location(node),
            component_index=component_index,
            parent_index=parent_index,
            expression_text=expr_text,
        ))

    return children_to_walk


def _walk_jsx_elements(node, source_bytes, component_index, parent_index,
                       markup_elements, events, bindings, render_relationships,
                       components, conditional=False, repeated=False,
                       conditional_expr=None, repeated_expr=None):
    """Iteratively walk JSX nodes and build markup element list.

    Uses an explicit stack instead of recursion.
    """
    # Stack entries: (node, parent_idx, conditional, repeated, conditional_expr, repeated_expr)
    stack = [(node, parent_index, conditional, repeated, conditional_expr, repeated_expr)]

    while stack:
        entry = stack.pop()
        n, p_idx, cond, rep, cond_e, rep_e = entry

        if n.type in ("jsx_element", "jsx_self_closing_element"):
            children = _process_jsx_element_node(
                n, source_bytes, component_index, p_idx,
                markup_elements, events, bindings, render_relationships,
                components, cond, rep, cond_e, rep_e,
            )
            # Push children in reverse order so they're processed left-to-right
            for child in reversed(children):
                stack.append(child)

        elif n.type == "jsx_expression":
            children = _process_jsx_expression_node(
                n, source_bytes, component_index, p_idx,
                markup_elements, events, bindings, render_relationships,
                components,
            )
            for child in reversed(children):
                stack.append(child)


def _find_component_jsx(func_node, source_bytes) -> List:
    """Find all top-level JSX elements returned by a component function."""
    jsx_roots = []

    stack = [func_node]
    while stack:
        node = stack.pop()
        if node.type == "return_statement":
            for i in range(node.child_count):
                c = node.child(i)
                if c.type.startswith("jsx_"):
                    jsx_roots.append(c)
                elif c.type == "parenthesized_expression":
                    for j in range(c.child_count):
                        cc = c.child(j)
                        if cc.type.startswith("jsx_"):
                            jsx_roots.append(cc)
        # Arrow function direct JSX body
        if node.type == "arrow_function" and node == func_node:
            found_arrow = False
            for i in range(node.child_count):
                c = node.child(i)
                if c.type == "=>":
                    found_arrow = True
                    continue
                if found_arrow and c.type.startswith("jsx_"):
                    jsx_roots.append(c)
                if found_arrow and c.type == "parenthesized_expression":
                    for j in range(c.child_count):
                        cc = c.child(j)
                        if cc.type.startswith("jsx_"):
                            jsx_roots.append(cc)
        if node.type == "statement_block":
            for i in range(node.child_count):
                stack.append(node.child(i))
        elif node.type == "arrow_function" and node != func_node:
            pass  # Don't recurse into nested arrows
        else:
            for i in range(node.child_count):
                child = node.child(i)
                if child.type not in ("arrow_function",) or child == func_node:
                    stack.append(child)

    return jsx_roots


def extract_jsx_semantics(source_bytes: bytes, language: str = "tsx", config=None, tree=None) -> dict:
    """Extract all semantic entities from a JSX/TSX file.

    Args:
        source_bytes: Raw source file content as bytes.
        language: 'tsx' or 'javascript' (for .jsx files).
        config: Optional FrontendConfig instance for extraction limits.
        tree: Optional pre-parsed tree-sitter Tree. If provided, skips re-parsing.

    Returns:
        dict with keys:
            - frontend_components: list of component dicts
            - markup_elements: list of element dicts
            - frontend_events: list of event handler dicts
            - frontend_bindings: list of binding dicts
            - render_relationships: list of render relationship dicts
            - style_selector_matches: list of selector match dicts
            - frontend_diagnostics: list of diagnostic dicts
    """
    if tree is not None:
        root = tree.root_node
    else:
        parser = _get_parser(language)
        if parser is None:
            return {
                "frontend_components": [],
                "markup_elements": [],
                "frontend_events": [],
                "frontend_bindings": [],
                "render_relationships": [],
                "style_selector_matches": [],
                "frontend_diagnostics": [{
                    "diagnostic_type": "missing_parser",
                    "severity": "fatal",
                    "message": f"Parser for {language} not available",
                }],
            }
        tree = parser.parse(source_bytes)
        root = tree.root_node

    # Portal detection (works even without JSX nodes)
    source_text = source_bytes.decode("utf-8", errors="replace") if isinstance(source_bytes, bytes) else source_bytes
    portal_diags = []
    if "createPortal" in source_text:
        portal_diags.append({
            "diagnostic_type": "portal_detected",
            "severity": "unsupported",
            "message": "React portal detected — portal children may not be in the normal render tree",
        })

    # If no JSX nodes, return empty (with portal diagnostic if applicable)
    if not _has_jsx_nodes(root):
        diags = list(portal_diags)
        # Check for parse errors (truncated/incomplete files)
        if root.has_error:
            diags.append({
                "diagnostic_type": "parse_error",
                "severity": "recoverable",
                "message": "JSX/TSX file has syntax errors — partial or no extraction performed",
            })
        return {
            "frontend_components": [],
            "markup_elements": [],
            "frontend_events": [],
            "frontend_bindings": [],
            "render_relationships": [],
            "style_selector_matches": [],
            "frontend_diagnostics": diags,
        }

    doc = JSXDocument(source_bytes=source_bytes)

    # Find components and build a node map to avoid per-component root scans
    doc.components, component_node_map = _find_components(root, source_bytes)

    # For each component, find its JSX and extract markup
    for comp_idx, component in enumerate(doc.components):
        # Use the node map from _find_components to avoid re-traversing the AST
        target_name = component.impl_function_name or component.impl_class_name
        comp_node = component_node_map.get(target_name)
        if comp_node is None:
            comp_node = _find_component_node(root, component, source_bytes)
        if comp_node is None:
            continue

        jsx_roots = _find_component_jsx(comp_node, source_bytes)
        for jsx_root in jsx_roots:
            _walk_jsx_elements(
                jsx_root, source_bytes, comp_idx, None,
                doc.markup_elements, doc.events, doc.bindings,
                doc.render_relationships, doc.components,
            )

    # Compute selector matches for static className strings
    # (The global FrontendResolver also recomputes these, but the local computation
    # is needed for standalone extractor usage and is cheap for individual files.)
    for i, elem in enumerate(doc.markup_elements):
        if elem.static_classes and elem.element_type in ("native", "custom_component"):
            for cls in elem.static_classes:
                doc.selector_matches.append({
                    "element_index": i,
                    "selector_text": f".{cls}",
                    "match_type": "static",
                    "confidence": "high",
                    "source_range": elem.location.to_dict(),
                })

    # Build result dict
    result = {
        "frontend_components": [],
        "markup_elements": [],
        "frontend_events": [],
        "frontend_bindings": [],
        "render_relationships": [],
        "style_selector_matches": [],
        "frontend_diagnostics": [],
    }

    # Components
    for comp in doc.components:
        result["frontend_components"].append({
            "name": comp.name,
            "component_type": comp.component_type,
            "source_range": comp.location.to_dict(),
            "is_exported": comp.is_exported,
            "is_default_export": comp.is_default_export,
            "impl_function_name": comp.impl_function_name,
            "impl_class_name": comp.impl_class_name,
            "wrapper_name": comp.wrapper_name,
        })

    # Markup elements
    for elem in doc.markup_elements:
        result["markup_elements"].append({
            "tag_name": elem.tag_name,
            "element_type": elem.element_type,
            "source_range": elem.location.to_dict(),
            "component_index": elem.component_index,
            "parent_index": elem.parent_index,
            "element_id_attr": elem.element_id_attr,
            "static_classes": elem.static_classes if elem.static_classes else None,
            "attributes": elem.attributes if elem.attributes else None,
            "is_conditional": elem.is_conditional,
            "is_repeated": elem.is_repeated,
            "conditional_expr": elem.conditional_expr,
            "repeated_expr": elem.repeated_expr,
            "expression_text": elem.expression_text,
        })

    # Events
    for ev in doc.events:
        result["frontend_events"].append({
            "component_index": ev.component_index,
            "element_index": ev.element_index,
            "event_name": ev.event_name,
            "handler_type": ev.handler_type,
            "handler_expression": ev.handler_expression,
            "resolution_status": ev.resolution_status,
            "source_range": ev.location.to_dict(),
        })

    # Bindings
    for b in doc.bindings:
        result["frontend_bindings"].append({
            "component_index": b.component_index,
            "element_index": b.element_index,
            "binding_name": b.binding_name,
            "binding_type": b.binding_type,
            "expression": b.expression,
            "resolution_status": b.resolution_status,
            "source_range": b.location.to_dict(),
        })

    # Render relationships
    for rr in doc.render_relationships:
        result["render_relationships"].append({
            "parent_component_index": rr.parent_component_index,
            "child_component_name": rr.child_component_name,
            "render_type": rr.render_type,
            "element_index": rr.element_index,
        })

    # Selector matches
    result["style_selector_matches"] = doc.selector_matches

    # Diagnostics
    if root.has_error:
        result["frontend_diagnostics"].append({
            "diagnostic_type": "parse_error",
            "severity": "recoverable",
            "message": "JSX/TSX file contains parse errors",
        })

    # Unresolved render relationships (component referenced but not found in file)
    component_names = {c.name for c in doc.components}
    for rr in doc.render_relationships:
        if rr.child_component_name not in component_names:
            result["frontend_diagnostics"].append({
                "diagnostic_type": "unresolved_component",
                "severity": "unresolved",
                "message": f"Component '{rr.child_component_name}' is rendered but not defined in this file",
            })

    # Dynamic class expressions
    for elem in doc.markup_elements:
        if elem.class_expression and elem.element_type in ("native", "custom_component"):
            result["frontend_diagnostics"].append({
                "diagnostic_type": "dynamic_class_expression",
                "severity": "unresolved",
                "message": f"className expression '{elem.class_expression[:50]}' could not be statically resolved",
                "source_range": elem.location.to_dict(),
            })

    # Spread props
    for b in doc.bindings:
        if b.binding_type == "spread":
            result["frontend_diagnostics"].append({
                "diagnostic_type": "spread_props",
                "severity": "unsupported",
                "message": f"Spread props '{b.expression[:50]}' — individual props cannot be resolved",
                "source_range": b.location.to_dict(),
            })

    # Include portal diagnostic if detected
    result["frontend_diagnostics"].extend(portal_diags)

    return result


def _find_component_node(root_node, component: JSXComponent, source_bytes):
    """Find the AST node corresponding to a component."""
    target_name = component.impl_function_name or component.impl_class_name
    if target_name is None:
        return None

    stack = [root_node]
    while stack:
        node = stack.pop()

        if node.type == "function_declaration":
            for i in range(node.child_count):
                c = node.child(i)
                if c.type in ("identifier", "type_identifier"):
                    name = extract_range(source_bytes, c.start_byte, c.end_byte)
                    if name == target_name:
                        return node

        elif node.type in ("arrow_function", "function_expression"):
            parent = node.parent
            if parent and parent.type == "variable_declarator":
                for i in range(parent.child_count):
                    c = parent.child(i)
                    if c.type in ("identifier", "type_identifier"):
                        name = extract_range(source_bytes, c.start_byte, c.end_byte)
                        if name == target_name:
                            return node

        elif node.type == "class_declaration":
            for i in range(node.child_count):
                c = node.child(i)
                if c.type in ("identifier", "type_identifier"):
                    name = extract_range(source_bytes, c.start_byte, c.end_byte)
                    if name == target_name:
                        return node

        for i in range(node.child_count):
            stack.append(node.child(i))

    return None
