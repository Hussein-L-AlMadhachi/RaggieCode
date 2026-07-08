"""
Node extraction functions for different language constructs.
"""

from indexing.node_utils import (
    get_node_location,
    extract_name,
    extract_node_text,
    extract_parameters,
    extract_return_type,
    is_method,
    extract_base_classes,
    extract_variable_name,
    extract_docstring,
    extract_field_text,
    extract_go_receiver,
    extract_go_type_name,
    count_branches
)


def extract_function_info(node, source_code, language, class_node_type):
    """Extract information about a function definition."""
    name = extract_name(node, source_code, language) or "unknown"
    params = extract_parameters(node, source_code, language)
    return_type = extract_return_type(node, source_code)
    method_flag = is_method(node, language, class_node_type)
    docstring = extract_docstring(node, source_code, language)
    
    # Count branches in function body
    branch_count = count_branches(node, language, source_code)
    
    # Handle Go method receivers
    receiver = None
    if language == "go":
        receiver = extract_go_receiver(node, source_code)
        if receiver:
            method_flag = True
    
    result = {
        "type": "method" if method_flag else "function",
        "name": name,
        "location": get_node_location(node),
        "parameters": params,
        "return_type": return_type,
        "docstring": docstring,
        "branch_count": branch_count
    }
    
    if receiver:
        result["receiver"] = receiver
    
    return result


def extract_class_info(node, source_code, language):
    """Extract information about a class definition."""
    name = extract_name(node, source_code, language) or "unknown"
    base_classes = extract_base_classes(node, source_code, language)
    docstring = extract_docstring(node, source_code, language)
    
    return {
        "type": "class",
        "name": name,
        "location": get_node_location(node),
        "base_classes": base_classes,
        "docstring": docstring,
        "methods": [],
        "nested_classes": [],
        "variables": []
    }


def extract_variable_info(node, source_code, language):
    """Extract information about a variable assignment."""
    name, is_attribute = extract_variable_name(node, source_code, language)
    
    if not name:
        return None
    
    if is_attribute:
        return {
            "type": "attribute",
            "name": name,
            "location": get_node_location(node)
        }
    
    return {
        "type": "variable",
        "name": name,
        "location": get_node_location(node)
    }


def extract_type_alias_info(node, source_code, language=None):
    """Extract information about type alias definitions."""
    name = extract_name(node, source_code, language) or "unknown"
    type_def = extract_field_text(node, "type", source_code)
    
    return {
        "type": "type_alias",
        "name": name,
        "location": get_node_location(node),
        "type_definition": type_def
    }


def extract_macro_info(node, source_code, language):
    """Extract information about a macro definition (C preproc_def, Rust macro_definition)."""
    name = extract_name(node, source_code, language) or "unknown"
    
    # Extract parameters for function-like macros (C preproc_function_def)
    params = []
    params_node = node.child_by_field_name("parameters")
    if params_node is None:
        # C preproc_function_def uses preproc_params
        for child in node.children:
            if child.type == "preproc_params":
                params_node = child
                break
    if params_node:
        for child in params_node.children:
            if child.type == "identifier":
                params.append({"name": extract_node_text(child, source_code), "type": None})
    
    return {
        "type": "macro",
        "name": name,
        "location": get_node_location(node),
        "parameters": params,
        "return_type": None,
        "docstring": None,
        "branch_count": 0,
    }


def extract_struct_info(node, source_code, language):
    """Extract information about a struct definition (C, C++, etc.)."""
    name = extract_name(node, source_code, language) or "unknown"
    return {
        "type": "struct",
        "name": name,
        "location": get_node_location(node),
    }


def extract_go_struct_info(node, source_code):
    """Extract information about a Go struct definition."""
    name = extract_go_type_name(node, source_code) or "unknown"
    
    return {
        "type": "struct",
        "name": name,
        "location": get_node_location(node),
        "methods": [],
        "fields": []
    }


def extract_interface_info(node, source_code, language):
    """Extract information about an interface/trait definition (Rust, etc.)."""
    name = extract_name(node, source_code, language) or "unknown"
    return {
        "type": "interface",
        "name": name,
        "location": get_node_location(node),
    }


def extract_go_interface_info(node, source_code):
    """Extract information about a Go interface definition."""
    name = extract_go_type_name(node, source_code) or "unknown"
    
    return {
        "type": "interface",
        "name": name,
        "location": get_node_location(node),
        "methods": []
    }


def extract_enum_info(node, source_code, language):
    """Extract information about an enum definition (Rust, etc.)."""
    name = extract_name(node, source_code, language) or "unknown"
    return {
        "type": "enum",
        "name": name,
        "location": get_node_location(node),
    }
