"""
Parallel file parsing worker for the code indexer.
Runs in separate processes to parallelize tree-sitter parsing.
"""

from pathlib import Path

from indexing.language_config import LANGUAGE_CONFIG, get_language_for_extension, get_node_types
from indexing.node_utils import (
    create_parser,
    extract_imports,
    extract_function_calls,
    extract_class_references,
    extract_variable_references,
    extract_node_text,
    get_node_location,
    count_branches,
    extract_go_type_kind,
)
from indexing.extractors import (
    extract_function_info,
    extract_class_info,
    extract_variable_info,
    extract_type_alias_info,
    extract_macro_info,
    extract_struct_info,
    extract_interface_info,
    extract_enum_info,
    extract_go_struct_info,
    extract_go_interface_info
)
from indexing.file_utils import read_file_content
import xxhash

# Global parser cache - initialized once per worker process
_parsers = {}

def _get_parser(language):
    """Get or create a parser for the given language (cached per worker)."""
    if language not in _parsers:
        lang_module = LANGUAGE_CONFIG[language]["language_module"]
        _parsers[language] = create_parser(lang_module) if lang_module else None
    return _parsers[language]


def parse_file(args):
    """Parse a single file and return extracted symbols as serializable data.
    
    Args:
        args: (file_path, root_dir) tuple
    
    Returns:
        dict with extracted symbols, or None if file should be skipped
    """
    file_path, root_dir = args
    file_path = Path(file_path)
    root_dir = Path(root_dir)
    
    try:
        ext = file_path.suffix
        language = get_language_for_extension(ext)
        if not language:
            return None
        
        parser = _get_parser(language)
        if parser is None:
            return None
        
        source_bytes = read_file_content(file_path)
        content_hash = xxhash.xxh64(source_bytes).hexdigest()
        file_mtime = file_path.stat().st_mtime
        
        tree = parser.parse(source_bytes)
        root_node = tree.root_node
        source_code = source_bytes.decode('utf-8', errors='ignore')
        
        # Extract imports
        imports = extract_imports(root_node, source_code, language, root_dir)
        
        # Extract symbols
        functions = []
        classes = []
        variables = []
        type_aliases = []
        structs = []
        interfaces = []
        enums = []
        namespaces = []
        dependencies = []
        
        _extract_symbols(
            root_node, source_code, language, file_path, root_dir,
            functions, classes, variables, type_aliases, structs, interfaces, enums, namespaces, dependencies
        )
        
        return {
            'file_path': str(file_path),
            'language': language,
            'content_hash': content_hash,
            'file_mtime': file_mtime,
            'imports': imports,
            'functions': functions,
            'classes': classes,
            'variables': variables,
            'type_aliases': type_aliases,
            'structs': structs,
            'interfaces': interfaces,
            'enums': enums,
            'namespaces': namespaces,
            'dependencies': dependencies,
        }
    except Exception as e:
        return {'error': str(e), 'file_path': str(file_path)}


def _extract_symbols(root_node, source_code, language, file_path, root_dir,
                     functions, classes, variables, type_aliases, structs, interfaces, enums, namespaces, dependencies):
    """Iteratively extract symbols from a tree-sitter AST using an explicit stack.
    Matches the logic of CodeIndexer._process_node exactly.
    Avoids recursion depth limits on deeply nested ASTs (e.g., Linux kernel C files).
    """
    node_types = get_node_types(language)
    if not node_types:
        return
    
    function_type = node_types.get("function")
    class_type = node_types.get("class")
    struct_type = node_types.get("struct")
    enum_type = node_types.get("enum")
    interface_type = node_types.get("interface")
    assignment_type = node_types.get("assignment")
    type_alias_type = node_types.get("type_alias")
    
    # C# 9 top-level statements: collect global_statement nodes into a pseudo-function
    if language == "csharp":
        global_stmts = [child for child in root_node.children if child.type == "global_statement"]
        if global_stmts:
            first = global_stmts[0]
            last = global_stmts[-1]
            pseudo_func = {
                "type": "function",
                "name": "top_level_statements",
                "location": {
                    "start_line": first.start_point[0] + 1,
                    "start_column": first.start_point[1],
                    "end_line": last.end_point[0] + 1,
                    "end_column": last.end_point[1],
                    "start_byte": first.start_byte,
                    "end_byte": last.end_byte,
                },
                "parameters": [],
                "return_type": None,
                "docstring": None,
                "branch_count": 0,
            }
            func_index = len(functions)
            functions.append(pseudo_func)
            # Extract deps from all global statements combined
            for gs in global_stmts:
                _extract_deps(gs, source_code, language, dependencies, func_index)
            # Extract top-level variable declarations
            for gs in global_stmts:
                for child in gs.children:
                    if child.type == "local_declaration_statement":
                        # C# local_declaration_statement: variable_declaration → variable_declarator → identifier
                        var_name = None
                        var_type = None
                        for vc in child.children:
                            if vc.type == "variable_declaration":
                                # Extract type from first child (implicit_type or type)
                                if vc.children:
                                    var_type = extract_node_text(vc.children[0], source_code)
                                for vd in vc.children:
                                    if vd.type == "variable_declarator":
                                        for vdc in vd.children:
                                            if vdc.type == "identifier":
                                                var_name = extract_node_text(vdc, source_code)
                                                break
                                        break
                                break
                        if var_name:
                            variables.append({
                                "type": "variable",
                                "name": var_name,
                                "location": get_node_location(child),
                                "field_type": var_type,
                            })

    # Stack entries: (node, in_function, current_class_id, current_namespace)
    stack = [(root_node, False, None, None)]
    
    while stack:
        node, in_function, current_class_id, current_namespace = stack.pop()
        
        # Skip global_statement nodes — already handled in C# top-level pre-pass
        if node.type == "global_statement":
            continue
        
        # C# namespace declaration: extract name and track as current namespace
        if language == "csharp" and node.type == "namespace_declaration":
            ns_name = None
            for child in node.children:
                if child.type in ("qualified_name", "identifier"):
                    ns_name = extract_node_text(child, source_code)
                    break
            if ns_name:
                # Build fully qualified namespace name
                if current_namespace:
                    full_ns = f"{current_namespace}.{ns_name}"
                else:
                    full_ns = ns_name
                namespaces.append({
                    "name": full_ns,
                    "location": get_node_location(node),
                })
                # Push children with the new namespace context
                children = list(node.children)
                for child in reversed(children):
                    stack.append((child, in_function, current_class_id, full_ns))
                continue
            # If we couldn't extract the name, still traverse children
            children = list(node.children)
            for child in reversed(children):
                stack.append((child, in_function, current_class_id, current_namespace))
            continue
        
        if function_type and node.type in function_type:
            func_info = extract_function_info(node, source_code, language, class_type)
            if func_info:
                if current_class_id is not None:
                    func_info['parent_class_id'] = current_class_id
                func_index = len(functions)
                functions.append(func_info)
                _extract_deps(node, source_code, language, dependencies, func_index)
            # Push children with in_function=True (reverse order for correct traversal)
            children = list(node.children)
            for child in reversed(children):
                stack.append((child, True, current_class_id, current_namespace))
            continue
        
        if class_type and node.type in class_type:
            # Kotlin: class_declaration is used for interfaces and enums too
            # Check for interface/enum keyword children to reclassify
            if language == "kotlin" and node.type == "class_declaration":
                is_interface = False
                is_enum = False
                for child in node.children:
                    if child.type == "interface":
                        is_interface = True
                        break
                    if child.type == "enum":
                        is_enum = True
                        break
                if is_interface:
                    iface_info = extract_interface_info(node, source_code, language)
                    if iface_info:
                        interfaces.append(iface_info)
                    continue
                if is_enum:
                    enum_info = extract_enum_info(node, source_code, language)
                    if enum_info:
                        enums.append(enum_info)
                    continue
            
            class_info = extract_class_info(node, source_code, language)
            if class_info:
                class_id = len(classes)
                class_info['_temp_id'] = class_id
                if current_namespace:
                    class_info['namespace'] = current_namespace
                classes.append(class_info)
                _process_class_body(node, source_code, language, class_id,
                                    functions, classes, variables, dependencies)
            continue
        
        if assignment_type and node.type in assignment_type:
            if not in_function:
                var_info = extract_variable_info(node, source_code, language)
                if var_info and var_info["type"] == "variable":
                    if current_class_id is not None:
                        var_info['parent_class_id'] = current_class_id
                    variables.append(var_info)
            continue
        
        # Rust global variables: const and static items
        if language == "rust" and node.type in ("const_item", "static_item"):
            if not in_function:
                var_info = extract_variable_info(node, source_code, language)
                if var_info and var_info["type"] == "variable":
                    variables.append(var_info)
            continue
        
        # Rust impl blocks: process methods inside impl_item as class methods
        if language == "rust" and node.type == "impl_item":
            # Extract the type name from the impl block
            type_node = node.child_by_field_name("type")
            impl_type_name = None
            if type_node:
                impl_type_name = extract_node_text(type_node, source_code)
            # Create a pseudo-class for the impl block so methods can reference it
            if impl_type_name:
                impl_id = len(classes)
                classes.append({
                    "type": "class",
                    "name": impl_type_name,
                    "location": get_node_location(node),
                    "base_classes": [],
                    "docstring": None,
                    "methods": [],
                    "nested_classes": [],
                    "variables": [],
                    "_temp_id": impl_id,
                })
                _process_class_body(node, source_code, language, impl_id,
                                    functions, classes, variables, dependencies)
            continue
        
        # Elixir: def/defp/defmacro/defmacrop are function definitions
        if language == "elixir" and node.type == "call":
            # Check if this is a def/defp/defmacro/defmacrop call
            func_name = None
            for child in node.children:
                if child.type == "identifier":
                    func_name = extract_node_text(child, source_code)
                    break
            if func_name in ("def", "defp", "defmacro", "defmacrop"):
                # Extract the function name from the first argument
                elixir_func_name = None
                for child in node.children:
                    if child.type == "arguments":
                        for arg in child.children:
                            if arg.type == "call":
                                # def foo(bar) -> the function name is the identifier inside the call
                                for grandchild in arg.children:
                                    if grandchild.type == "identifier":
                                        elixir_func_name = extract_node_text(grandchild, source_code)
                                        break
                            elif arg.type == "identifier":
                                elixir_func_name = extract_node_text(arg, source_code)
                                break
                            elif arg.type == "atom":
                                # def :foo -> atom function name
                                atom_text = extract_node_text(arg, source_code)
                                elixir_func_name = atom_text.lstrip(':')
                                break
                        break
                if elixir_func_name:
                    func_info = {
                        "type": "function" if func_name in ("def", "defmacro") else "function",
                        "name": elixir_func_name,
                        "location": get_node_location(node),
                        "parameters": [],
                        "return_type": None,
                        "docstring": None,
                        "branch_count": count_branches(node, language),
                    }
                    func_index = len(functions)
                    functions.append(func_info)
                    _extract_deps(node, source_code, language, dependencies, func_index)
                continue
            # defmodule creates a module (treated as a class)
            elif func_name == "defmodule":
                # Extract module name
                module_name = None
                for child in node.children:
                    if child.type == "arguments":
                        for arg in child.children:
                            if arg.type == "alias":
                                module_name = extract_node_text(arg, source_code)
                                break
                        break
                if module_name:
                    class_id = len(classes)
                    classes.append({
                        "type": "class",
                        "name": module_name,
                        "location": get_node_location(node),
                        "base_classes": [],
                        "docstring": None,
                        "methods": [],
                        "nested_classes": [],
                        "variables": [],
                        "_temp_id": class_id,
                    })
                    # Process the do block as class body
                    for child in node.children:
                        if child.type == "do_block":
                            for stmt in child.children:
                                if stmt.type == "stab_clause":
                                    # Process stab_clause children for inner def/defp
                                    stack.append((stmt, False, class_id, current_namespace))
                                else:
                                    stack.append((stmt, False, class_id, current_namespace))
                            break
                continue
            # defstruct creates a struct - name comes from enclosing module
            elif func_name == "defstruct":
                # defstruct doesn't take a name; use current_class_id to find the module name
                struct_name = None
                if current_class_id is not None and current_class_id < len(classes):
                    struct_name = classes[current_class_id].get("name")
                if not struct_name:
                    struct_name = "unknown"
                structs.append({
                    "type": "struct",
                    "name": struct_name,
                    "location": get_node_location(node),
                })
                continue
            # defprotocol creates an interface-like construct
            elif func_name == "defprotocol":
                proto_name = None
                for child in node.children:
                    if child.type == "arguments":
                        for arg in child.children:
                            if arg.type == "alias":
                                proto_name = extract_node_text(arg, source_code)
                                break
                        break
                if proto_name:
                    interfaces.append({
                        "type": "interface",
                        "name": proto_name,
                        "location": get_node_location(node),
                    })
                continue
            # defimpl creates an implementation
            elif func_name == "defimpl":
                impl_name = None
                for child in node.children:
                    if child.type == "arguments":
                        for arg in child.children:
                            if arg.type == "alias":
                                impl_name = extract_node_text(arg, source_code)
                                break
                        break
                if impl_name:
                    class_id = len(classes)
                    classes.append({
                        "type": "class",
                        "name": f"{impl_name}Impl",
                        "location": get_node_location(node),
                        "base_classes": [impl_name],
                        "docstring": None,
                        "methods": [],
                        "nested_classes": [],
                        "variables": [],
                        "_temp_id": class_id,
                    })
                    for child in node.children:
                        if child.type == "do_block":
                            for stmt in child.children:
                                stack.append((stmt, False, class_id, current_namespace))
                            break
                continue
        
        # Macro definitions: C preproc_def/preproc_function_def, Rust macro_definition
        if node.type in ("preproc_def", "preproc_function_def", "macro_definition"):
            macro_info = extract_macro_info(node, source_code, language)
            if macro_info:
                functions.append(macro_info)
            continue
        
        # Go: type_declaration covers structs, interfaces, and type aliases
        # Dispatch via extract_go_type_kind before generic branches to avoid conflicts
        if language == "go" and node.type == "type_declaration":
            kind = extract_go_type_kind(node, source_code)
            if kind == "struct":
                struct_info = extract_go_struct_info(node, source_code)
                if struct_info:
                    structs.append(struct_info)
            elif kind == "interface":
                iface_info = extract_go_interface_info(node, source_code)
                if iface_info:
                    interfaces.append(iface_info)
            else:
                alias_info = extract_type_alias_info(node, source_code, language)
                if alias_info:
                    type_aliases.append(alias_info)
            continue

        if struct_type and node.type in struct_type:
            struct_info = extract_struct_info(node, source_code, language)
            if struct_info:
                structs.append(struct_info)
                # C# and C++ structs have methods and properties like classes — process their bodies
                if language in ("csharp", "cpp"):
                    struct_id = len(classes)
                    struct_info['_temp_id'] = struct_id
                    # Also add to classes so methods can reference it as parent
                    classes.append({
                        "type": "class",
                        "name": struct_info["name"],
                        "location": struct_info["location"],
                        "base_classes": [],
                        "docstring": None,
                        "methods": [],
                        "nested_classes": [],
                        "variables": [],
                        "_temp_id": struct_id,
                        "namespace": current_namespace,
                    })
                    _process_class_body(node, source_code, language, struct_id,
                                        functions, classes, variables, dependencies)
            continue
        
        if interface_type and node.type in interface_type:
            iface_info = extract_interface_info(node, source_code, language)
            if iface_info:
                interfaces.append(iface_info)
                # C# interfaces have method declarations — process their bodies
                if language == "csharp":
                    iface_id = len(classes)
                    iface_info['_temp_id'] = iface_id
                    # Also add to classes so methods can reference it as parent
                    classes.append({
                        "type": "class",
                        "name": iface_info["name"],
                        "location": iface_info["location"],
                        "base_classes": [],
                        "docstring": None,
                        "methods": [],
                        "nested_classes": [],
                        "variables": [],
                        "_temp_id": iface_id,
                        "namespace": current_namespace,
                    })
                    _process_class_body(node, source_code, language, iface_id,
                                        functions, classes, variables, dependencies)
            continue
        
        if enum_type and node.type in enum_type:
            enum_info = extract_enum_info(node, source_code, language)
            if enum_info:
                enums.append(enum_info)
            continue
        
        if type_alias_type and node.type in type_alias_type:
            alias_info = extract_type_alias_info(node, source_code, language)
            if alias_info:
                type_aliases.append(alias_info)
            continue
        
        # Push children with same state (reverse order for correct traversal)
        children = list(node.children)
        for child in reversed(children):
            stack.append((child, in_function, current_class_id, current_namespace))


def _process_class_body(class_node, source_code, language, class_id,
                        functions, classes, variables, dependencies):
    """Process class body children to extract methods, nested classes, and attributes."""
    node_types = get_node_types(language)
    function_type = node_types.get("function")
    method_type = node_types.get("method")
    class_type = node_types.get("class")
    assignment_type = node_types.get("assignment")
    public_field_type = node_types.get("public_field")
    
    # Find the class body
    class_body = None
    for child in class_node.children:
        if child.type in ["class_body", "declaration_list", "block", "field_declaration_list", "class_body"]:
            class_body = child
            break
    
    if not class_body:
        return
    
    for child in class_body.children:
        if child.type in ["{", "}"]:
            continue
        
        if (function_type and child.type in function_type) or \
           (method_type and child.type in method_type):
            func_info = extract_function_info(child, source_code, language, class_type)
            if func_info:
                func_info['parent_class_id'] = class_id
                func_index = len(functions)
                functions.append(func_info)
                _extract_deps(child, source_code, language, dependencies, func_index)
        elif class_type and child.type in class_type:
            nested_class_info = extract_class_info(child, source_code, language)
            if nested_class_info:
                nested_id = len(classes)
                nested_class_info['_temp_id'] = nested_id
                classes.append(nested_class_info)
                _process_class_body(child, source_code, language, nested_id,
                                    functions, classes, variables, dependencies)
        elif assignment_type and child.type in assignment_type:
            var_info = extract_variable_info(child, source_code, language)
            if var_info and var_info["type"] == "attribute":
                var_info['parent_class_id'] = class_id
                variables.append(var_info)
        elif public_field_type and child.type in public_field_type:
            name_node = child.child_by_field_name("name")
            if not name_node:
                name_node = child.child_by_field_name("property_identifier")
            name = extract_node_text(name_node, source_code) if name_node else "unknown"
            type_node = child.child_by_field_name("type")
            type_annotation = extract_node_text(type_node, source_code) if type_node else None
            variables.append({
                "type": "variable",
                "name": name,
                "location": get_node_location(child),
                "field_type": type_annotation,
                "parent_class_id": class_id,
            })


def _extract_deps(node, source_code, language, dependencies, func_index=None):
    """Extract dependencies (function calls, class refs, variable refs) from a node.
    
    Args:
        func_index: Index of the containing function in the functions list,
                    used to later resolve source_function_id.
    """
    func_calls = extract_function_calls(node, source_code, language)
    class_refs = extract_class_references(node, source_code, language)
    var_refs = extract_variable_references(node, source_code, language)
    for call in func_calls:
        dep = {
            'type': call.get('dependency_type', 'function_call'),
            'name': call['name'],
            'location': call.get('location'),
        }
        if func_index is not None:
            dep['_func_index'] = func_index
        dependencies.append(dep)
    for ref in class_refs:
        dep = {
            'type': 'class_reference',
            'name': ref['name'],
            'location': ref.get('location'),
        }
        if func_index is not None:
            dep['_func_index'] = func_index
        dependencies.append(dep)
    for ref in var_refs:
        dep = {
            'type': 'variable_reference',
            'name': ref['name'],
            'location': ref.get('location'),
        }
        if func_index is not None:
            dep['_func_index'] = func_index
        dependencies.append(dep)
