#!/usr/bin/env python3
"""
Vue single-file-component semantic extractor.
Extracts the SFC component, template markup, directives (v-if/v-for/v-on/
v-bind/v-model/v-slot), events, bindings, render relationships, scripts,
and styles from .vue files.
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


_vue_parser = None

# Vue built-in components that are not user components
VUE_BUILTIN_TAGS = {"component", "slot", "transition", "transition-group",
                    "keep-alive", "teleport", "suspense"}


def _get_parser():
    """Get or create the Vue parser (cached per process)."""
    global _vue_parser
    if _vue_parser is None:
        lang_module = LANGUAGE_CONFIG.get("vue", {}).get("language_module")
        if lang_module is not None:
            _vue_parser = create_parser(lang_module)
    return _vue_parser


def _parse_directive(dir_node, source_bytes) -> Tuple[str, Optional[str], Optional[str], Optional[str], List[str]]:
    """Parse a directive_attribute node.

    Returns:
        (kind, directive_name, argument, value, modifiers) where kind is
        'event' (@/v-on), 'binding' (:/v-bind), 'slot' (#/v-slot), or
        'named' (other v-* directives); directive_name is the v-* name for
        'named' directives; argument is the directive_value text (or
        '[expr]' for dynamic arguments); value is the attribute value.
    """
    kind = "named"
    directive_name = None
    argument = None
    value = None
    modifiers = []

    for i in range(dir_node.child_count):
        child = dir_node.child(i)
        if child.type == "@":
            kind = "event"
        elif child.type == ":":
            kind = "binding"
        elif child.type == "#":
            kind = "slot"
        elif child.type == "directive_name":
            directive_name = extract_range(source_bytes, child.start_byte, child.end_byte)
        elif child.type == "directive_value":
            argument = extract_range(source_bytes, child.start_byte, child.end_byte)
        elif child.type == "dynamic_directive_value":
            inner = find_child(child, "dynamic_directive_inner_value")
            if inner is not None:
                argument = "[" + extract_range(source_bytes, inner.start_byte, inner.end_byte) + "]"
        elif child.type == "directive_modifiers":
            for j in range(child.child_count):
                mod = child.child(j)
                if mod.type == "directive_modifier":
                    modifiers.append(extract_range(source_bytes, mod.start_byte, mod.end_byte))
        elif child.type in ("quoted_attribute_value", "attribute_value"):
            value = get_attribute_value(child, source_bytes)

    # Normalize longhand forms
    if directive_name == "v-on":
        kind = "event"
    elif directive_name == "v-bind":
        kind = "binding"
    elif directive_name == "v-slot":
        kind = "slot"

    return kind, directive_name, argument, value, modifiers


def _process_element(elem_node, source_bytes, parent_idx, imported_names,
                     elements, events, bindings, render_relationships):
    """Process a template element node and append to the output lists.

    Returns the new element's index (used as parent for children).
    """
    tag_node = find_child(elem_node, "start_tag", "self_closing_tag")
    if tag_node is None:
        return parent_idx

    tag_name = get_tag_name(tag_node, source_bytes)
    attributes = {}
    static_classes = []
    element_id = None
    is_conditional = False
    is_repeated = False
    conditional_expr = None
    repeated_expr = None
    pending_events = []
    pending_bindings = []

    for i in range(tag_node.child_count):
        child = tag_node.child(i)
        if child.type == "attribute":
            name_node = find_child(child, "attribute_name")
            if name_node is None:
                continue
            name = extract_range(source_bytes, name_node.start_byte, name_node.end_byte)
            value_node = find_child(child, "quoted_attribute_value", "attribute_value")
            value = get_attribute_value(value_node, source_bytes)
            attributes[name] = value if value is not None else ""
            if name == "class" and value:
                static_classes = value.split()
            elif name == "id":
                element_id = value
        elif child.type == "directive_attribute":
            kind, dname, argument, value, modifiers = _parse_directive(child, source_bytes)
            attr_loc = node_to_location(child)

            if kind == "event" and argument:
                handler_type, resolution = classify_handler(value)
                pending_events.append({
                    "event_name": argument,
                    "handler_type": handler_type,
                    "handler_expression": value or "",
                    "resolution_status": resolution,
                    "source_range": attr_loc.to_dict(),
                })
            elif kind == "binding":
                if argument:
                    pending_bindings.append({
                        "binding_name": argument,
                        "binding_type": "property",
                        "expression": value or "",
                        "resolution_status": classify_binding(value),
                        "source_range": attr_loc.to_dict(),
                    })
                else:
                    # v-bind without argument: object spread
                    pending_bindings.append({
                        "binding_name": None,
                        "binding_type": "spread",
                        "expression": value or "",
                        "resolution_status": classify_binding(value),
                        "source_range": attr_loc.to_dict(),
                    })
            elif kind == "slot":
                pending_bindings.append({
                    "binding_name": argument,
                    "binding_type": "slot",
                    "expression": value or "",
                    "resolution_status": "unresolved",
                    "source_range": attr_loc.to_dict(),
                })
            elif dname == "v-if":
                is_conditional = True
                conditional_expr = value
            elif dname == "v-else-if":
                is_conditional = True
                conditional_expr = value
            elif dname == "v-else":
                is_conditional = True
            elif dname == "v-show":
                is_conditional = True
                conditional_expr = value
            elif dname == "v-for":
                is_repeated = True
                repeated_expr = value
            elif dname == "v-model":
                pending_bindings.append({
                    "binding_name": argument or "modelValue",
                    "binding_type": "model",
                    "expression": value or "",
                    "resolution_status": classify_binding(value),
                    "source_range": attr_loc.to_dict(),
                })
            elif dname in ("v-html", "v-text"):
                pending_bindings.append({
                    "binding_name": dname,
                    "binding_type": "directive",
                    "expression": value or "",
                    "resolution_status": classify_binding(value),
                    "source_range": attr_loc.to_dict(),
                })

    element_type = "native"
    if tag_name not in VUE_BUILTIN_TAGS and is_component_tag(tag_name, imported_names):
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
        is_conditional=is_conditional,
        is_repeated=is_repeated,
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
            "render_type": ("repeated" if is_repeated
                            else "conditional" if is_conditional else "direct"),
            "element_index": idx,
            "controlling_expr": repeated_expr or conditional_expr,
        })

    return idx


def _walk_template(template_node, source_bytes, imported_names,
                   elements, events, bindings, render_relationships):
    """Walk the template element tree (iterative, explicit stack).

    Nested <template> elements (slot wrappers) are transparent: their
    children attach to the wrapper's parent.
    """
    stack = []
    for i in range(template_node.child_count - 1, -1, -1):
        child = template_node.child(i)
        if child.type in ("element", "template_element", "interpolation"):
            stack.append((child, None))

    while stack:
        node, parent_idx = stack.pop()

        if node.type == "template_element":
            # Transparent wrapper (slot templates): children keep parent
            for i in range(node.child_count - 1, -1, -1):
                child = node.child(i)
                if child.type in ("element", "template_element", "interpolation"):
                    stack.append((child, parent_idx))
        elif node.type == "interpolation":
            expr_node = find_child(node, "raw_text")
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
        else:  # element
            idx = _process_element(node, source_bytes, parent_idx, imported_names,
                                   elements, events, bindings, render_relationships)
            for i in range(node.child_count - 1, -1, -1):
                child = node.child(i)
                if child.type in ("element", "template_element", "interpolation"):
                    stack.append((child, idx))


def extract_vue_semantics(source_bytes: bytes, component_name: Optional[str] = None,
                          config=None) -> dict:
    """Extract all semantic entities from a .vue single-file component.

    Args:
        source_bytes: Raw .vue file content as bytes.
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
            "message": "Vue tree-sitter grammar not available",
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
            "message": "Vue SFC has syntax errors   partial extraction performed",
        })

    # Collect top-level SFC blocks
    template_nodes = []
    script_nodes = []
    style_blocks = []  # (raw_text, location, attrs)
    for i in range(root.child_count):
        child = root.child(i)
        if child.type == "template_element":
            template_nodes.append(child)
        elif child.type == "script_element":
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
    anchor = template_nodes[0] if template_nodes else (script_nodes[0] if script_nodes else root)
    result["frontend_components"].append({
        "name": component_name,
        "component_type": "sfc",
        "framework": "vue",
        "source_range": node_to_location(anchor).to_dict(),
        "is_exported": True,
        "is_default_export": True,
        "impl_function_name": None,
        "impl_class_name": None,
        "wrapper_name": None,
    })

    # Script blocks
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
            "is_setup": "setup" in attrs,
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

    if len(template_nodes) > 1:
        result["frontend_diagnostics"].append({
            "diagnostic_type": "multiple_templates",
            "severity": "recoverable",
            "message": f"SFC has {len(template_nodes)} top-level <template> blocks   only the first is indexed",
        })

    if template_nodes:
        _walk_template(template_nodes[0], source_bytes, imported_names,
                       elements, events, bindings, render_relationships)

    # Style blocks
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

        src = attrs.get("src")
        if src:
            result["style_imports"].append({
                "import_path": src,
                "is_external": src.startswith(("http://", "https://", "//")),
                "source_range": location.to_dict(),
            })
            continue

        if not raw_text.strip():
            continue

        selectors, custom_props, prop_usages = process_style_block(
            raw_text, location, "scoped" in attrs, source_bytes)
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
