#!/usr/bin/env python3
"""
Svelte single-file-component semantic extractor.
Extracts the SFC component, template markup, block structure ({#if}/{#each}/
{#await}/{#key}), event handlers (on:), bindings (bind:/class:/expression
attributes), render relationships, scripts, and scoped styles from
.svelte files.

Note: the else-branch of an {#each} block (the empty-state markup) inherits
the block's is_repeated flag   a known, deliberate simplification.
"""

from typing import Dict, List, Optional, Tuple

from indexing.language_config import LANGUAGE_CONFIG
from indexing.node_utils import create_parser
from indexing.frontend.source_location import node_to_location, extract_range
from indexing.frontend.sfc_common import (
    SFCElement,
    SUPPORTED_STYLE_LANGS,
    build_style_selector_matches,
    classify_binding,
    classify_handler,
    element_to_markup_dict,
    empty_sfc_result,
    find_child,
    get_attribute_value,
    get_block_attributes,
    get_tag_name,
    is_component_tag,
    process_style_block,
    scan_imported_names,
    script_parser_language,
)


_svelte_parser = None

# Transparent block containers: children inherit the enclosing block's state
_TRANSPARENT_BLOCKS = {"else_statement", "then_statement", "catch_statement"}

# Template-level expression nodes recorded as 'expression' markup elements
_EXPRESSION_NODES = {"expression", "html_expr", "render_expr", "debug_expr"}

# Nodes that carry no markup semantics and are skipped during the walk
_SKIP_NODES = {"text", "comment", "const_expr", "start_tag", "end_tag",
               "self_closing_tag", "attribute"}


def _get_parser():
    """Get or create the Svelte parser (cached per process)."""
    global _svelte_parser
    if _svelte_parser is None:
        lang_module = LANGUAGE_CONFIG.get("svelte", {}).get("language_module")
        if lang_module is not None:
            _svelte_parser = create_parser(lang_module)
    return _svelte_parser


def _statement_start(stmt_node, source_bytes) -> Tuple[Optional[str], Optional[str]]:
    """Extract (keyword, expression) from a block's start expression.

    e.g. for {#each items as item} returns ('each', 'items as item').
    """
    start = find_child(stmt_node, *[t for t in (
        "if_start_expr", "each_start_expr", "await_start_expr", "key_start_expr",
        "snippet_start_expr")])
    if start is None:
        return None, None
    kw_node = find_child(start, "special_block_keyword")
    keyword = None
    if kw_node is not None:
        keyword = extract_range(source_bytes, kw_node.start_byte, kw_node.end_byte)
    inner = extract_range(source_bytes, start.start_byte, start.end_byte).strip()
    if inner.startswith("{"):
        inner = inner[1:]
    if inner.endswith("}"):
        inner = inner[:-1]
    inner = inner.strip()
    if keyword and inner.startswith("#" + keyword):
        inner = inner[len(keyword) + 1:].strip()
    return keyword, inner


def _process_attribute(attr_node, source_bytes, attributes, pending_events,
                       pending_bindings):
    """Process a Svelte element attribute.

    Handles static attributes, expression attributes (name={expr}),
    shorthand attributes ({name}), and prefixed directives
    (on:/bind:/class:/use:/transition:/in:/out:/animate:).

    Returns:
        (static_classes, element_id) extracted from static class/id attrs.
    """
    static_classes = []
    element_id = None
    attr_loc = node_to_location(attr_node)

    name_node = find_child(attr_node, "attribute_name")
    name = None
    shorthand = False
    if name_node is not None:
        expr_inner = find_child(name_node, "raw_text_expr")
        if expr_inner is not None:
            # Shorthand attribute: {value}
            name = extract_range(source_bytes, expr_inner.start_byte, expr_inner.end_byte).strip()
            shorthand = True
        else:
            name = extract_range(source_bytes, name_node.start_byte, name_node.end_byte)

    # Expression value: name={expr}
    expr_value = None
    expr_node = find_child(attr_node, "expr_attribute_value")
    if expr_node is not None:
        raw_expr = find_child(expr_node, "expression")
        if raw_expr is not None:
            inner = find_child(raw_expr, "raw_text_expr")
            if inner is not None:
                expr_value = extract_range(source_bytes, inner.start_byte, inner.end_byte).strip()
    static_value = get_attribute_value(
        find_child(attr_node, "quoted_attribute_value"), source_bytes)

    if shorthand:
        pending_bindings.append({
            "binding_name": name,
            "binding_type": "property",
            "expression": name or "",
            "resolution_status": "inferred",
            "source_range": attr_loc.to_dict(),
        })
        return static_classes, element_id

    if not name:
        return static_classes, element_id

    # Strip event modifiers: on:click|preventDefault
    base_name = name.split("|", 1)[0]

    if ":" in base_name:
        prefix, argument = base_name.split(":", 1)
        if prefix == "on":
            handler_type, resolution = classify_handler(expr_value)
            pending_events.append({
                "event_name": argument,
                "handler_type": handler_type,
                "handler_expression": expr_value or "",
                "resolution_status": resolution,
                "source_range": attr_loc.to_dict(),
            })
        elif prefix == "bind":
            pending_bindings.append({
                "binding_name": argument,
                "binding_type": "two_way",
                # bind:value shorthand binds the variable of the same name
                "expression": expr_value if expr_value is not None else argument,
                "resolution_status": "inferred",
                "source_range": attr_loc.to_dict(),
            })
        elif prefix == "class":
            pending_bindings.append({
                "binding_name": argument,
                "binding_type": "class",
                "expression": expr_value or "",
                "resolution_status": classify_binding(expr_value),
                "source_range": attr_loc.to_dict(),
            })
        elif prefix in ("use", "transition", "in", "out", "animate"):
            pending_bindings.append({
                "binding_name": argument,
                "binding_type": {"use": "action", "animate": "animation"}.get(prefix, "transition"),
                "expression": expr_value or "",
                "resolution_status": classify_binding(expr_value),
                "source_range": attr_loc.to_dict(),
            })
        else:
            pending_bindings.append({
                "binding_name": base_name,
                "binding_type": "property",
                "expression": expr_value or "",
                "resolution_status": classify_binding(expr_value),
                "source_range": attr_loc.to_dict(),
            })
        return static_classes, element_id

    if expr_value is not None:
        pending_bindings.append({
            "binding_name": name,
            "binding_type": "property",
            "expression": expr_value,
            "resolution_status": classify_binding(expr_value),
            "source_range": attr_loc.to_dict(),
        })
        return static_classes, element_id

    # Plain static attribute
    value = static_value if static_value is not None else ""
    attributes[name] = value
    if name == "class" and value:
        static_classes = value.split()
    elif name == "id":
        element_id = value
    return static_classes, element_id


def _process_element(elem_node, source_bytes, parent_idx, state, imported_names,
                     elements, events, bindings, render_relationships):
    """Process a template element node. Returns the new element's index."""
    conditional, conditional_expr, repeated, repeated_expr = state

    tag_node = find_child(elem_node, "start_tag", "self_closing_tag")
    if tag_node is None:
        return parent_idx

    tag_name = get_tag_name(tag_node, source_bytes)
    attributes = {}
    static_classes = []
    element_id = None
    pending_events = []
    pending_bindings = []

    for i in range(tag_node.child_count):
        child = tag_node.child(i)
        if child.type != "attribute":
            continue
        classes, el_id = _process_attribute(child, source_bytes, attributes,
                                            pending_events, pending_bindings)
        if classes:
            static_classes = classes
        if el_id is not None:
            element_id = el_id

    element_type = "native"
    if not tag_name.startswith("svelte:") and is_component_tag(tag_name, imported_names):
        element_type = "custom_component"

    idx = len(elements)
    elements.append(SFCElement(
        tag_name=tag_name,
        element_type=element_type,
        location=node_to_location(elem_node),
        parent_index=parent_idx,
        element_id_attr=element_id,
        static_classes=static_classes,
        attributes=attributes,
        is_conditional=conditional,
        is_repeated=repeated,
        conditional_expr=conditional_expr,
        repeated_expr=repeated_expr,
    ))

    for ev in pending_events:
        ev["element_index"] = idx
        events.append(ev)
    for b in pending_bindings:
        b["element_index"] = idx
        bindings.append(b)

    if element_type == "custom_component":
        render_relationships.append({
            "parent_component_index": 0,
            "child_component_name": tag_name,
            "render_type": ("repeated" if repeated
                            else "conditional" if conditional else "direct"),
            "element_index": idx,
            "controlling_expr": repeated_expr or conditional_expr,
        })

    return idx


def _is_block_statement(node) -> bool:
    return node.type.endswith("_statement") and node.type not in _TRANSPARENT_BLOCKS


def _push_children(node, stack, parent_idx, state):
    """Push a container's children onto the walk stack with the given state.

    Block start/end expressions ({#if ...}, {/if}) are not markup and
    are skipped.
    """
    for i in range(node.child_count - 1, -1, -1):
        child = node.child(i)
        if child.type.endswith("_start_expr") or child.type.endswith("_end_expr"):
            continue
        if child.type in _SKIP_NODES:
            continue
        stack.append((child, parent_idx, state))


def _walk_template(root, source_bytes, imported_names,
                   elements, events, bindings, render_relationships):
    """Walk the Svelte template (iterative, explicit stack).

    Block statements propagate conditional/repeated state to the elements
    they contain; else/then/catch branches inherit the block's state.
    """
    default_state = (False, None, False, None)
    stack = []
    for i in range(root.child_count - 1, -1, -1):
        child = root.child(i)
        if child.type in ("element",) or child.type in _EXPRESSION_NODES \
                or child.type in _TRANSPARENT_BLOCKS or _is_block_statement(child):
            stack.append((child, None, default_state))

    while stack:
        node, parent_idx, state = stack.pop()

        if node.type in _EXPRESSION_NODES:
            expr_node = find_child(node, "raw_text_expr")
            expr_text = ""
            if expr_node is not None:
                expr_text = extract_range(source_bytes, expr_node.start_byte, expr_node.end_byte).strip()
            elements.append(SFCElement(
                tag_name="",
                element_type="expression",
                location=node_to_location(node),
                parent_index=parent_idx,
                expression_text=expr_text,
            ))
        elif node.type in _TRANSPARENT_BLOCKS:
            _push_children(node, stack, parent_idx, state)
        elif _is_block_statement(node):
            keyword, inner = _statement_start(node, source_bytes)
            conditional, conditional_expr, repeated, repeated_expr = state
            if keyword == "each":
                repeated, repeated_expr = True, inner
            elif keyword in ("if", "await", "key"):
                conditional, conditional_expr = True, inner
            _push_children(node, stack, parent_idx,
                           (conditional, conditional_expr, repeated, repeated_expr))
        elif node.type == "element":
            idx = _process_element(node, source_bytes, parent_idx, state, imported_names,
                                   elements, events, bindings, render_relationships)
            _push_children(node, stack, idx, state)


def extract_svelte_semantics(source_bytes: bytes, component_name: Optional[str] = None,
                             config=None) -> dict:
    """Extract all semantic entities from a .svelte single-file component.

    Args:
        source_bytes: Raw .svelte file content as bytes.
        component_name: Name for the SFC component (usually the file stem).
        config: Optional FrontendConfig instance for extraction limits.

    Returns:
        dict with frontend_components, markup_elements, frontend_events,
        frontend_bindings, render_relationships, style_* keys,
        frontend_diagnostics, inline_scripts, and inline_styles.
    """
    result = empty_sfc_result()
    parser = _get_parser()
    if parser is None:
        result["frontend_diagnostics"].append({
            "diagnostic_type": "missing_parser",
            "severity": "fatal",
            "message": "Svelte tree-sitter grammar not available",
        })
        return result

    parse_scripts = config.parse_inline_scripts if config else True
    parse_styles = config.parse_inline_styles if config else True
    component_name = component_name or "AnonymousComponent"

    tree = parser.parse(source_bytes)
    root = tree.root_node

    if root.has_error:
        result["frontend_diagnostics"].append({
            "diagnostic_type": "parse_error",
            "severity": "recoverable",
            "message": "Svelte component has syntax errors   partial extraction performed",
        })

    # Collect script/style blocks
    script_nodes = []
    style_blocks = []  # (raw_text, location, attrs)
    for i in range(root.child_count):
        child = root.child(i)
        if child.type == "script_element":
            script_nodes.append(child)
        elif child.type == "style_element":
            start_tag = find_child(child, "start_tag")
            attrs = get_block_attributes(start_tag, source_bytes) if start_tag else {}
            raw_node = find_child(child, "raw_text")
            raw_text = ""
            if raw_node is not None:
                raw_text = extract_range(source_bytes, raw_node.start_byte, raw_node.end_byte)
            style_blocks.append((raw_text, node_to_location(child), attrs))

    # Component entry: the SFC file itself is the component
    anchor = script_nodes[0] if script_nodes else root
    result["frontend_components"].append({
        "name": component_name,
        "component_type": "sfc",
        "framework": "svelte",
        "source_range": node_to_location(anchor).to_dict(),
        "is_exported": True,
        "is_default_export": True,
        "impl_function_name": None,
        "impl_class_name": None,
        "wrapper_name": None,
    })

    # Script blocks (instance and module scripts)
    script_texts = []
    for script_node in script_nodes:
        start_tag = find_child(script_node, "start_tag")
        attrs = get_block_attributes(start_tag, source_bytes) if start_tag else {}
        raw_node = find_child(script_node, "raw_text")
        content = ""
        if raw_node is not None:
            content = extract_range(source_bytes, raw_node.start_byte, raw_node.end_byte)
        src = attrs.get("src")

        if src:
            result["inline_scripts"].append({
                "type": "external",
                "src": src,
                "script_type": "",
                "location": node_to_location(script_node).to_dict(),
            })
            continue

        script_texts.append(content)
        if not parse_scripts:
            continue

        script_language = script_parser_language(attrs.get("lang"))
        if script_language is None:
            result["frontend_diagnostics"].append({
                "diagnostic_type": "unsupported_script_lang",
                "severity": "unsupported",
                "message": f"Script lang '{attrs.get('lang')}' is not parsed for semantics",
                "source_range": node_to_location(script_node).to_dict(),
            })
            continue

        result["inline_scripts"].append({
            "type": "inline",
            "content": content,
            "script_type": "",
            "script_language": script_language,
            "is_module": attrs.get("context") == "module" or "module" in attrs,
            "location": node_to_location(script_node).to_dict(),
        })

    imported_names = set()
    for text in script_texts:
        imported_names.update(scan_imported_names(text))

    # Template walk
    elements: List[SFCElement] = []
    events: List[dict] = []
    bindings: List[dict] = []
    render_relationships: List[dict] = []

    _walk_template(root, source_bytes, imported_names,
                   elements, events, bindings, render_relationships)

    # Style blocks (Svelte styles are component-scoped by default)
    for raw_text, location, attrs in style_blocks:
        style_lang = (attrs.get("lang") or "").strip().lower()
        if style_lang not in SUPPORTED_STYLE_LANGS:
            result["frontend_diagnostics"].append({
                "diagnostic_type": "unsupported_style_lang",
                "severity": "unsupported",
                "message": f"Style lang '{style_lang}' is not parsed for semantics",
                "source_range": location.to_dict(),
            })
            continue

        if not raw_text.strip():
            continue

        selectors, custom_props, prop_usages = process_style_block(
            raw_text, location, True, source_bytes)
        result["style_selectors"].extend(selectors)
        result["style_custom_properties"].extend(custom_props)
        result["style_custom_property_usages"].extend(prop_usages)

        if parse_styles:
            result["inline_styles"].append({
                "content": raw_text,
                "location": location.to_dict(),
            })

    # Selector → element matches (uses _match_info carried on selector dicts)
    result["style_selector_matches"] = build_style_selector_matches(
        result["style_selectors"], elements)
    for sel in result["style_selectors"]:
        sel.pop("_match_info", None)

    # Serialize markup elements
    component_index = 0 if result["frontend_components"] else None
    result["markup_elements"] = [
        element_to_markup_dict(el, i, component_index) for i, el in enumerate(elements)
    ]
    result["frontend_events"] = events
    result["frontend_bindings"] = bindings
    result["render_relationships"] = render_relationships

    return result
