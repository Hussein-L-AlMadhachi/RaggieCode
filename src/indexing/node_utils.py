"""
Utility functions for working with tree-sitter nodes.
"""



def get_node_location(node):
    """Get start and end line/column for a node."""
    start_line, start_col = node.start_point
    end_line, end_col = node.end_point
    return {
        "start_line": start_line + 1,
        "start_column": start_col,
        "end_line": end_line + 1,
        "end_column": end_col,
        "start_byte": node.start_byte,
        "end_byte": node.end_byte
    }


def extract_node_text(node, source_code):
    """Extract the text content of a node from source code."""
    # tree-sitter uses byte offsets, but Python strings use character indices
    # For UTF-8 with multi-byte characters, we need to convert to bytes first
    source_bytes = source_code.encode('utf-8')
    return source_bytes[node.start_byte:node.end_byte].decode('utf-8')


def extract_field_text(node, field_name, source_code):
    """Extract text from a specific field of a node."""
    field_node = node.child_by_field_name(field_name)
    if field_node:
        return extract_node_text(field_node, source_code)
    return None


def extract_name(node, source_code, language=None):
    """Extract the name from a node (function, class, variable, etc.)."""
    # Try the standard "name" field first
    name = extract_field_text(node, "name", source_code)
    if name:
        return name
    
    # TypeScript/JavaScript specific: look for identifier children
    # For function declarations, the name is typically the first identifier
    # We need to be careful not to pick up identifiers from the function body
    if node.type == "function_declaration":
        # The name should be the first identifier child (before parameters)
        for child in node.children:
            # Kotlin uses simple_identifier
            if child.type in ["identifier", "simple_identifier"]:
                return extract_node_text(child, source_code)
            # Stop if we've gone past the name (parameters start)
            if child.type in ["formal_parameters", "function_value_parameters"]:
                break
    elif node.type == "method_declaration":
        if language == "go":
            # Go method: func (recv *Type) Name() - name is field_identifier
            for child in node.children:
                if child.type == "field_identifier":
                    return extract_node_text(child, source_code)
                if child.type == "identifier":
                    return extract_node_text(child, source_code)
        # C# method declaration - look for identifier
        for child in node.children:
            if child.type == "identifier":
                return extract_node_text(child, source_code)
            # Stop if we've gone past the name (parameters start)
            if child.type == "parameter_list":
                break
    elif node.type == "class_declaration":
        # For classes, look for type_identifier
        for child in node.children:
            if child.type == "type_identifier":
                return extract_node_text(child, source_code)
            if child.type == "class_heritage":
                break
    elif node.type in ("function_definition", "declaration") and language in ("cpp", "c"):
        # C++ function_definition: name is inside function_declarator or declarator
        for child in node.children:
            if child.type in ("function_declarator", "declarator", "reference_declarator", "pointer_declarator"):
                # Find the identifier or field_identifier inside the declarator
                stack = [child]
                while stack:
                    n = stack.pop()
                    if n.type in ("identifier", "field_identifier"):
                        return extract_node_text(n, source_code)
                    stack.extend(reversed(list(n.children)))
    elif node.type == "class_specifier" and language == "cpp":
        # C++ class_specifier: name is a type_identifier child
        for child in node.children:
            if child.type == "type_identifier":
                return extract_node_text(child, source_code)
    elif node.type == "type_declaration" and language == "go":
        return extract_go_type_name(node, source_code)
    elif node.type == "struct_specifier" and language in ("cpp", "c"):
        # C/C++ struct_specifier: name is a type_identifier child
        for child in node.children:
            if child.type == "type_identifier":
                return extract_node_text(child, source_code)
    elif node.type == "enum_specifier" and language in ("cpp", "c"):
        # C/C++ enum_specifier: name is a type_identifier child
        for child in node.children:
            if child.type == "type_identifier":
                return extract_node_text(child, source_code)
    elif node.type == "method_signature" and language == "dart":
        # Dart method_signature wraps function_signature/getter_signature/etc.
        # The name is inside the inner signature
        for child in node.children:
            if child.type in ("function_signature", "getter_signature", "setter_signature", "constructor_signature"):
                for grandchild in child.children:
                    if grandchild.type == "identifier":
                        return extract_node_text(grandchild, source_code)
    else:
        # For other node types, look for the first identifier
        # Kotlin uses simple_identifier
        for child in node.children:
            if child.type in ["identifier", "property_identifier", "type_identifier", "simple_identifier"]:
                return extract_node_text(child, source_code)
    
    return None


def extract_parameters(node, source_code, language):
    """Extract parameter names from a function node."""
    params = []
    params_node = node.child_by_field_name("parameters")
    
    # C# uses "parameter_list" as a child, not a field
    if not params_node and language == "csharp":
        for child in node.children:
            if child.type == "parameter_list":
                params_node = child
                break
    
    # Dart uses "formal_parameter_list" as a child
    if not params_node and language == "dart":
        for child in node.children:
            if child.type == "formal_parameter_list":
                params_node = child
                break
        # For method_signature, look inside the inner signature
        if not params_node:
            for child in node.children:
                if child.type in ("function_signature", "getter_signature", "setter_signature", "constructor_signature"):
                    for grandchild in child.children:
                        if grandchild.type == "formal_parameter_list":
                            params_node = grandchild
                            break
                    break
    
    if not params_node:
        return params
    
    # Language-specific parameter extraction
    if language == "python":
        for child in params_node.children:
            if child.type == "identifier":
                params.append(extract_node_text(child, source_code))
    elif language in ["go", "rust", "cpp", "php"]:
        for child in params_node.children:
            if child.type in ["identifier", "parameter"]:
                params.append(extract_node_text(child, source_code))
    elif language in ["javascript", "typescript", "tsx", "csharp"]:
        for child in params_node.children:
            if child.type == "identifier":
                params.append(extract_node_text(child, source_code))
    elif language in ["java", "kotlin", "dart"]:
        for child in params_node.children:
            if child.type in ["identifier", "simple_identifier", "formal_parameter"]:
                if child.type == "formal_parameter":
                    # Extract identifier from inside formal_parameter
                    for grandchild in child.children:
                        if grandchild.type in ["identifier", "simple_identifier"]:
                            params.append(extract_node_text(grandchild, source_code))
                            break
                else:
                    params.append(extract_node_text(child, source_code))
    elif language == "zig":
        for child in params_node.children:
            if child.type in ["identifier", "parameter"]:
                params.append(extract_node_text(child, source_code))
    elif language == "elixir":
        for child in params_node.children:
            if child.type in ["identifier", "atom"]:
                params.append(extract_node_text(child, source_code))
    
    return params


def extract_return_type(node, source_code):
    """Extract return type from a function node."""
    return extract_field_text(node, "return_type", source_code)


def is_method(node, language, class_node_type):
    """Check if a function node is a method (inside a class)."""
    if not node.parent:
        return False
    if not class_node_type:
        return False
    if isinstance(class_node_type, list):
        return node.parent.type in class_node_type
    return node.parent.type == class_node_type


def extract_base_classes(node, source_code, language):
    """Extract base class names from a class node."""
    base_classes = []
    
    if language == "python":
        arg_list = node.child_by_field_name("superclasses")
        if arg_list:
            for child in arg_list.children:
                if child.type in ["identifier", "attribute"]:
                    base_classes.append(extract_node_text(child, source_code))
    elif language in ["csharp", "cpp"]:
        # C# base_list has no field name, find by type
        base_list = None
        for child in node.children:
            if child.type == "base_list":
                base_list = child
                break
        if not base_list:
            base_list = node.child_by_field_name("bases")
        if base_list:
            for child in base_list.children:
                if child.type in ["identifier", "type_identifier"]:
                    base_classes.append(extract_node_text(child, source_code))
    elif language in ["javascript", "typescript", "tsx"]:
        # TypeScript/JavaScript uses class_heritage as a child, not a field
        heritage = None
        for child in node.children:
            if child.type == "class_heritage":
                heritage = child
                break
        
        if heritage:
            # Look for extends_clause or direct identifiers
            for child in heritage.children:
                if child.type == "extends_clause":
                    # Find the identifier inside extends_clause
                    for grandchild in child.children:
                        if grandchild.type in ["identifier", "type_identifier"]:
                            base_classes.append(extract_node_text(grandchild, source_code))
                elif child.type in ["identifier", "type_identifier"]:
                    base_classes.append(extract_node_text(child, source_code))
    elif language == "php":
        # PHP uses "extends" keyword
        base_class_node = node.child_by_field_name("base")
        if base_class_node:
            for child in base_class_node.children:
                if child.type in ["identifier", "name"]:
                    base_classes.append(extract_node_text(child, source_code))
    elif language == "java":
        # Java: extends superclass, implements interfaces
        superclass = node.child_by_field_name("superclass")
        if superclass:
            for child in superclass.children:
                if child.type in ["type_identifier", "identifier"]:
                    base_classes.append(extract_node_text(child, source_code))
        interfaces = node.child_by_field_name("super_interfaces")
        if interfaces:
            for child in interfaces.children:
                if child.type in ["type_identifier", "identifier"]:
                    base_classes.append(extract_node_text(child, source_code))
    elif language == "kotlin":
        # Kotlin: superclass and super_type_list
        for child in node.children:
            if child.type in ["superclass", "delegation_specifier"]:
                for grandchild in child.children:
                    if grandchild.type in ["type_identifier", "identifier", "user_type", "constructor_invocation"]:
                        base_classes.append(extract_node_text(grandchild, source_code))
    elif language == "dart":
        # Dart: extends and with (mixins), implements
        for child in node.children:
            if child.type in ["superclass", "with_clause", "implements_clause"]:
                for grandchild in child.children:
                    if grandchild.type in ["type_identifier", "identifier", "mixin_identifier"]:
                        base_classes.append(extract_node_text(grandchild, source_code))
    elif language == "rust":
        # Rust traits can have supertraits
        bounds = node.child_by_field_name("bounds")
        if bounds:
            for child in bounds.children:
                if child.type in ["type_identifier", "identifier", "scoped_identifier"]:
                    base_classes.append(extract_node_text(child, source_code))
    
    return base_classes


def extract_variable_name(node, source_code, language):
    """Extract variable name from an assignment node."""
    name = None
    
    if language == "python":
        left_node = node.child_by_field_name("left")
        if left_node:
            if left_node.type == "identifier":
                name = extract_node_text(left_node, source_code)
            elif left_node.type == "attribute":
                return extract_node_text(left_node, source_code), True  # Return as attribute
    elif language in ["go", "rust"]:
        name_node = node.child_by_field_name("name")
        if name_node:
            name = extract_node_text(name_node, source_code)
    elif language == "c":
        # C declaration: int x; int x = 5; static char *msg; int arr[1024];
        # Look for any declarator child (init_declarator, array_declarator, etc.)
        # and extract the identifier from within it.
        declarator_types = {"init_declarator", "array_declarator", "pointer_declarator",
                            "function_declarator", "parenthesized_declarator"}
        for child in node.children:
            if child.type in declarator_types:
                stack = [child]
                while stack:
                    n = stack.pop()
                    if n.type == "identifier":
                        name = extract_node_text(n, source_code)
                        break
                    stack.extend(reversed(list(n.children)))
                if name:
                    break
    elif language in ["javascript", "typescript", "tsx", "csharp", "cpp", "php"]:
        # Handle lexical_declaration / variable_declaration (const/let/var x = ...)
        if node.type in ("lexical_declaration", "variable_declaration"):
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        name = extract_node_text(name_node, source_code)
                        break
            return name, False
        left_node = node.child_by_field_name("left")
        if left_node:
            if left_node.type == "identifier":
                name = extract_node_text(left_node, source_code)
            elif left_node.type == "member_expression":
                return extract_node_text(left_node, source_code), True  # Return as attribute
    elif language in ["java", "dart"]:
        left_node = node.child_by_field_name("left")
        if left_node:
            if left_node.type in ["identifier", "simple_identifier"]:
                name = extract_node_text(left_node, source_code)
            elif left_node.type in ["member_expression", "field_access_expression", "navigation_expression"]:
                return extract_node_text(left_node, source_code), True
    elif language == "kotlin":
        # Kotlin assignment: directly_assignable_expression wraps simple_identifier
        for child in node.children:
            if child.type == "directly_assignable_expression":
                for grandchild in child.children:
                    if grandchild.type in ["simple_identifier", "identifier"]:
                        name = extract_node_text(grandchild, source_code)
                        break
                break
            elif child.type in ["simple_identifier", "identifier"]:
                name = extract_node_text(child, source_code)
                break
    elif language == "zig":
        # Zig variable_declaration: const/var identifier = value
        # The identifier is a direct child, not a 'left' field
        for child in node.children:
            if child.type == "identifier":
                name = extract_node_text(child, source_code)
                break
    elif language == "elixir":
        # Elixir: binary_operator with = is an assignment
        # Only treat as assignment if operator is "="
        op_node = node.child_by_field_name("operator")
        if op_node and extract_node_text(op_node, source_code) == "=":
            left_node = node.child_by_field_name("left")
            if left_node and left_node.type == "identifier":
                name = extract_node_text(left_node, source_code)
    
    return name, False


def extract_docstring(node, source_code, language):
    """Extract docstring from a node if present."""
    if language == "python":
        for child in node.children:
            if child.type == "block":
                for grandchild in child.children:
                    if grandchild.type == "expression_statement":
                        string_node = None
                        for gc in grandchild.children:
                            if gc.type == "string":
                                string_node = gc
                                break
                        if string_node:
                            docstring = extract_node_text(string_node, source_code)
                            if docstring.startswith('"""') or docstring.startswith("'''"):
                                return docstring[3:-3]
                            elif docstring.startswith('"') or docstring.startswith("'"):
                                return docstring[1:-1]
    # Other languages would need comment extraction logic
    return None


def extract_go_receiver(node, source_code):
    """Extract receiver information from a Go method declaration."""
    receiver_node = node.child_by_field_name("receiver")
    if receiver_node:
        return extract_node_text(receiver_node, source_code)
    return None


def extract_go_type_name(node, source_code):
    """Extract type name from a Go type_declaration node (struct or interface)."""
    # Go type_declaration has a "name" field for the type identifier
    name_node = node.child_by_field_name("name")
    if name_node:
        return extract_node_text(name_node, source_code)
    
    # Look inside type_spec for the type_identifier
    for child in node.children:
        if child.type == "type_spec":
            for grandchild in child.children:
                if grandchild.type == "type_identifier":
                    return extract_node_text(grandchild, source_code)
        if child.type == "type_identifier":
            return extract_node_text(child, source_code)
    
    return None


def extract_go_type_kind(node, source_code):
    """Determine if a Go type_declaration is a struct, interface, or type alias."""
    # Look for type_spec child which contains the actual type info
    type_spec = None
    for child in node.children:
        if child.type == "type_spec":
            type_spec = child
            break
    
    if not type_spec:
        # Fallback: try field name
        type_spec = node.child_by_field_name("type")
    
    if not type_spec:
        return "type_alias"
    
    # Check the type body to determine kind
    for child in type_spec.children:
        if child.type == "struct_type":
            return "struct"
        elif child.type == "interface_type":
            return "interface"
    
    return "type_alias"


def count_branches(node, language, source_code=None):
    """Count the number of conditional branches in a function body (iterative)."""
    branch_count = 0
    
    branch_types = {
        'python': ['if_statement', 'for_statement', 'while_statement', 'match_statement', 'try_statement'],
        'go': ['if_statement', 'for_statement', 'for_range_clause', 'switch_statement', 'select_statement'],
        'javascript': ['if_statement', 'for_statement', 'for_in_statement', 'for_of_statement', 'while_statement', 'switch_statement', 'try_statement', 'do_statement'],
        'typescript': ['if_statement', 'for_statement', 'for_in_statement', 'for_of_statement', 'while_statement', 'switch_statement', 'try_statement'],
        'tsx': ['if_statement', 'for_statement', 'for_in_statement', 'for_of_statement', 'while_statement', 'switch_statement', 'try_statement'],
        'csharp': ['if_statement', 'for_statement', 'foreach_statement', 'while_statement', 'switch_statement', 'try_statement'],
        'rust': ['if_expression', 'for_expression', 'while_expression', 'loop_expression', 'match_expression', 'if_let_expression', 'while_let_expression'],
        'cpp': ['if_statement', 'for_statement', 'range_based_for_statement', 'while_statement', 'switch_statement', 'try_statement', 'do_statement'],
        'zig': ['if_statement', 'for_statement', 'while_statement', 'switch_statement'],
        'elixir': ['call'],
        'php': ['if_statement', 'for_statement', 'foreach_statement', 'while_statement', 'switch_statement', 'try_statement', 'match_expression'],
        'dart': ['if_statement', 'for_statement', 'while_statement', 'switch_statement', 'try_statement'],
        'java': ['if_statement', 'for_statement', 'enhanced_for_statement', 'while_statement', 'switch_statement', 'try_statement', 'try_with_resources_statement', 'do_statement'],
        'kotlin': ['if_expression', 'for_statement', 'while_statement', 'do_while_statement', 'when_expression', 'try_expression']
    }
    
    lang_branch_types = branch_types.get(language, ['if_statement', 'for_statement', 'while_statement', 'switch_statement'])
    
    elixir_branch_keywords = {'if', 'case', 'cond', 'try', 'receive', 'for', 'with', 'unless'}
    
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in lang_branch_types:
            if language == 'elixir' and n.type == 'call':
                first_ident = None
                for child in n.children:
                    if child.type == 'identifier':
                        first_ident = extract_node_text(child, source_code)
                        break
                if first_ident in elixir_branch_keywords:
                    branch_count += 1
            else:
                branch_count += 1
        stack.extend(reversed(list(n.children)))
    
    return branch_count


def extract_imports(node, source_code, language, root_dir=None):
    """Extract import statements from a file (iterative)."""
    imports = []
    
    import_types = {
        'python': ['import_statement', 'import_from_statement'],
        'go': ['import_declaration'],
        'javascript': ['import_statement', 'import_declaration'],
        'typescript': ['import_statement', 'import_declaration'],
        'tsx': ['import_statement', 'import_declaration'],
        'csharp': ['using_directive', 'global_using_directive'],
        'rust': ['use_declaration', 'extern_crate_declaration'],
        'cpp': ['include_directive', 'preproc_include'],
        'c': ['include_directive', 'preproc_include'],
        'zig': ['builtin_function'],
        'elixir': ['alias'],
        'php': ['include_expression', 'include_once_expression', 'require_expression', 'require_once_expression', 'namespace_use_declaration'],
        'dart': ['import_or_export'],
        'java': ['import_declaration'],
        'kotlin': ['import_header']
    }
    
    lang_import_types = import_types.get(language, ['import_statement'])
    
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in lang_import_types:
            # Zig: only @import builtin_function calls are imports
            if language == "zig" and n.type == "builtin_function":
                text = extract_node_text(n, source_code)
                if not text.startswith("@import"):
                    stack.extend(reversed(list(n.children)))
                    continue
            # Go: import_declaration may contain import_spec_list with multiple import_spec
            if language == "go" and n.type == "import_declaration":
                specs = []
                for child in n.children:
                    if child.type == "import_spec_list":
                        for spec in child.children:
                            if spec.type == "import_spec":
                                specs.append(spec)
                if specs:
                    for spec in specs:
                        import_text = extract_node_text(spec, source_code)
                        is_external = True
                        if root_dir:
                            is_external = _is_external_import(import_text, language, root_dir)
                        imports.append({
                            'name': import_text,
                            'location': get_node_location(spec),
                            'is_external': is_external
                        })
                    continue
            import_text = extract_node_text(n, source_code)
            is_external = True
            if root_dir:
                is_external = _is_external_import(import_text, language, root_dir)
            imports.append({
                'name': import_text,
                'location': get_node_location(n),
                'is_external': is_external
            })
        stack.extend(reversed(list(n.children)))
    
    return imports


def _is_external_import(import_text, language, root_dir):
    """Determine if an import is external (not part of the codebase)."""
    from pathlib import Path
    
    root_path = Path(root_dir)
    
    if language == 'python':
        # Extract the base module name from the import
        # e.g., "import os.path" -> "os", "from myapp.models import User" -> "myapp"
        if import_text.startswith('from '):
            # "from myapp.models import User"
            parts = import_text.split()
            if len(parts) >= 2:
                module_name = parts[1].split('.')[0]
            else:
                return True
        else:
            # "import os" or "import os.path"
            parts = import_text.split()
            if len(parts) >= 2:
                module_name = parts[1].split('.')[0]
            else:
                return True
        
        # Check if this module exists in the codebase
        module_path = root_path / module_name
        if module_path.exists() and (module_path.is_dir() or module_path.with_suffix('.py').exists()):
            return False  # Internal
        
        # Also check for __init__.py
        init_path = module_path / '__init__.py'
        if init_path.exists():
            return False  # Internal
    
    elif language == 'go':
        # Go imports are usually full paths like "github.com/user/repo/module"
        # Check if it's a relative import or local package
        if import_text.startswith('"'):
            import_path = import_text.strip('"')
        else:
            import_path = import_text
        
        # Relative imports are internal
        if import_path.startswith('.'):
            return False
        
        # Check if it matches a directory in the codebase
        module_name = import_path.split('/')[-1]
        if (root_path / module_name).exists():
            return False
    
    elif language in ['javascript', 'typescript', 'tsx']:
        # Extract the module path from the import statement
        # e.g. import { foo } from "./local"; -> ./local
        import_path = None
        if 'from ' in import_text:
            # import { x } from "path"
            parts = import_text.split('from ')
            if len(parts) >= 2:
                path_part = parts[-1].strip().rstrip(';').strip()
                import_path = path_part.strip('"\'`')
        elif import_text.startswith('import '):
            # import "path" or import "path";
            path_part = import_text[len('import '):].strip().rstrip(';').strip()
            import_path = path_part.strip('"\'`')
        
        if import_path:
            if import_path.startswith('./') or import_path.startswith('../'):
                return False
            if not import_path.startswith('.') and not import_path.startswith('@'):
                module_path = root_path / import_path
                if module_path.exists() or (root_path / f"{import_path}.js").exists() or (root_path / f"{import_path}.ts").exists() or (root_path / f"{import_path}.tsx").exists():
                    return False
    
    elif language == 'rust':
        # Rust uses crate:: for internal, external packages are just names
        if 'crate::' in import_text or import_text.startswith('super::') or import_text.startswith('self::'):
            return False
    
    elif language in ['cpp', 'c']:
        # #include "local.h" is internal, #include <system.h> is external
        if import_text.startswith('#include "'):
            return False  # Local include
    
    elif language == 'csharp':
        # using System; is external, using MyProject.Models; is internal
        if import_text.startswith('using '):
            namespace = import_text[6:].strip().rstrip(';')
            # Check if it's a standard .NET namespace
            standard_namespaces = ['System', 'Microsoft', 'Newtonsoft', 'Serilog']
            if any(namespace.startswith(std) for std in standard_namespaces):
                return True
            # Check if it matches a directory in the codebase
            if (root_path / namespace.replace('.', '/')).exists():
                return False
    
    elif language == 'php':
        # PHP: include/require with relative paths are internal
        if import_text.startswith(('include ', 'include_once ', 'require ', 'require_once ')):
            # Extract the path
            parts = import_text.split()
            if len(parts) >= 2:
                path = parts[1].strip('"\'();')
                # Relative paths are internal
                if path.startswith('./') or path.startswith('../'):
                    return False
                # Check if it exists in the codebase
                if (root_path / path).exists():
                    return False
        elif import_text.startswith('use '):
            # use statements for namespaces
            namespace = import_text[4:].strip().rstrip(';')
            # Check if it's a standard PHP namespace
            standard_namespaces = ['PHP', 'Symfony', 'Laravel', 'Doctrine']
            if any(namespace.startswith(std) for std in standard_namespaces):
                return True
            # Check if it matches a directory in the codebase
            if (root_path / namespace.replace('\\', '/')).exists():
                return False
    
    elif language == 'dart':
        # Dart: package: imports are external, relative imports are internal
        if import_text.startswith('import '):
            # Extract the URI
            if "'" in import_text:
                uri = import_text.split("'")[1]
            elif '"' in import_text:
                uri = import_text.split('"')[1]
            else:
                return True
            if uri.startswith('dart:') or uri.startswith('package:'):
                return True
            if uri.startswith('./') or uri.startswith('../') or uri.startswith('/'):
                return False
            # Check if it exists in the codebase
            if (root_path / uri).exists():
                return False
    
    elif language == 'java':
        # Java: import com.example.* is internal if com/example exists
        if import_text.startswith('import '):
            parts = import_text.split()
            if len(parts) >= 2:
                import_path = parts[1].rstrip(';').replace('.', '/')
                if (root_path / import_path).exists() or (root_path / (import_path + '.java')).exists():
                    return False
    
    elif language == 'kotlin':
        # Kotlin: import is internal if the path exists in the codebase
        if import_text.startswith('import '):
            parts = import_text.split()
            if len(parts) >= 2:
                import_path = parts[1].replace('.', '/')
                if (root_path / import_path).exists() or (root_path / (import_path + '.kt')).exists():
                    return False
    
    elif language == 'zig':
        # Zig: @import("file.zig") is internal if the file exists
        if '@import' in import_text:
            if '"' in import_text:
                path = import_text.split('"')[1]
            elif "'" in import_text:
                path = import_text.split("'")[1]
            else:
                return True
            if path.startswith('std') or path.startswith('builtin') or path.startswith('root'):
                return True
            if (root_path / path).exists():
                return False
    
    elif language == 'elixir':
        # Elixir: alias MyApp.Foo is internal if lib/my_app/foo.ex exists
        # The import text is just the module path (e.g. "Plug.Conn")
        module_name = import_text.strip().rstrip('.')
        if module_name:
            import re
            s1 = re.sub('([a-z0-9])([A-Z])', r'\1_\2', module_name)
            s2 = re.sub('([A-Z]+)([A-Z][a-z])', r'\1_\2', s1)
            snake = s2.lower()
            base_path = root_path / 'lib' / snake.replace('.', '/')
            if base_path.exists() or base_path.with_suffix('.ex').exists():
                return False
    
    return True  # Default to external


def extract_function_calls(node, source_code, language):
    """Extract function calls from a node (iterative to avoid recursion limits).
    
    Handles various call patterns:
    - Direct calls: func()
    - Method calls: obj.method(), self.method()
    - Chained calls: obj.method().another()
    - Attribute calls: module.func()
    - Class instantiations: ClassName() (captured as function_call for dependency tracking)
    """
    calls = []
    
    call_types = {
        'python': ['call'],
        'go': ['call_expression'],
        'javascript': ['call_expression'],
        'typescript': ['call_expression'],
        'tsx': ['call_expression'],
        'csharp': ['invocation_expression'],
        'rust': ['call_expression'],
        'cpp': ['call_expression'],
        'c': ['call_expression'],
        'zig': ['call_expression'],
        'elixir': ['call'],
        'php': ['function_call_expression'],
        'dart': ['expression_statement'],
        'java': ['method_invocation', 'object_creation_expression'],
        'kotlin': ['call_expression']
    }
    
    lang_call_types = call_types.get(language, ['call_expression'])
    
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in lang_call_types:
            func_name = None
            dep_type = 'function_call'
            
            # Dart: expression_statement with identifier + selector(arguments)
            if language == 'dart' and n.type == 'expression_statement':
                has_args = False
                method_name = None
                first_ident = None
                for child in n.children:
                    if child.type == 'identifier' and first_ident is None:
                        first_ident = extract_node_text(child, source_code)
                    elif child.type == 'selector':
                        for sel_child in child.children:
                            if sel_child.type == 'argument_part':
                                for arg_child in sel_child.children:
                                    if arg_child.type == 'arguments':
                                        has_args = True
                                        break
                            elif sel_child.type == 'unconditional_assignable_selector':
                                for us_child in sel_child.children:
                                    if us_child.type == 'identifier':
                                        method_name = extract_node_text(us_child, source_code)
                if has_args:
                    if method_name:
                        func_name = method_name
                        dep_type = 'method_call'
                    elif first_ident:
                        func_name = first_ident
                        dep_type = 'function_call'
                if func_name:
                    calls.append({
                        'name': func_name,
                        'location': get_node_location(n),
                        'dependency_type': dep_type
                    })
                continue
            
            # Try to extract the function name from the call expression
            for child in n.children:
                # Direct identifier: func() or ClassName()
                if child.type in ['identifier', 'simple_identifier']:
                    func_name = extract_node_text(child, source_code)
                    dep_type = 'function_call'
                    break
                # Attribute access: obj.method or module.func
                elif child.type in ['attribute', 'member_expression', 'field_expression', 'member_access_expression', 'field_access_expression', 'navigation_expression']:
                    func_name = extract_node_text(child, source_code)
                    dep_type = 'method_call'
                    break
                # Selector expression (Go): obj.method()
                elif child.type == 'selector_expression':
                    func_name = extract_node_text(child, source_code)
                    dep_type = 'method_call'
                    break
                # Chained calls: obj.method().another()
                elif child.type == 'call':
                    # This is a nested call, extract from the inner call
                    for grandchild in child.children:
                        if grandchild.type in ['identifier', 'simple_identifier', 'attribute', 'member_expression', 'field_access_expression', 'navigation_expression']:
                            func_name = extract_node_text(grandchild, source_code)
                            dep_type = 'method_call' if grandchild.type not in ['identifier', 'simple_identifier'] else 'function_call'
                            break
                    if func_name:
                        break
            
            if func_name:
                calls.append({
                    'name': func_name,
                    'location': get_node_location(n),
                    'dependency_type': dep_type
                })
        stack.extend(reversed(list(n.children)))
    
    return calls


def extract_class_references(node, source_code, language):
    """Extract class references (instantiations, type annotations, etc.) from a node (iterative)."""
    references = []
    
    stack = [node]
    while stack:
        n = stack.pop()
        
        if language == 'python':
            if n.type == 'call':
                for child in n.children:
                    if child.type == 'identifier':
                        name = extract_node_text(child, source_code)
                        if name and name[0].isupper():
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
                        break
            elif n.type == 'type':
                for child in n.children:
                    if child.type == 'identifier' or child.type == 'type':
                        name = extract_node_text(child, source_code)
                        if name and name[0].isupper():
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
        
        elif language in ['javascript', 'typescript', 'tsx']:
            if n.type == 'new_expression':
                for child in n.children:
                    if child.type in ['identifier', 'member_expression']:
                        name = extract_node_text(child, source_code)
                        if name:
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
                        break
            elif n.type == 'type_annotation':
                for child in n.children:
                    if child.type in ['identifier', 'type_identifier']:
                        name = extract_node_text(child, source_code)
                        if name and name[0].isupper():
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
        
        elif language == 'csharp':
            if n.type == 'object_creation_expression':
                for child in n.children:
                    if child.type == 'identifier':
                        name = extract_node_text(child, source_code)
                        if name:
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
                        break
        
        elif language == 'go':
            if n.type == 'composite_literal':
                for child in n.children:
                    if child.type == 'identifier' or child.type == 'selector_expression':
                        name = extract_node_text(child, source_code)
                        if name and name[0].isupper():
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
                        break
        
        elif language == 'rust':
            if n.type == 'call_expression':
                for child in n.children:
                    if child.type == 'identifier' or child.type == 'scoped_identifier':
                        name = extract_node_text(child, source_code)
                        if name and name[0].isupper():
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
                        break
        
        elif language == 'php':
            if n.type == 'new_expression':
                for child in n.children:
                    if child.type in ['identifier', 'name']:
                        name = extract_node_text(child, source_code)
                        if name and name[0].isupper():
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
                        break
        
        elif language == 'cpp':
            if n.type == 'new_expression':
                for child in n.children:
                    if child.type in ['identifier', 'type_identifier', 'qualified_identifier']:
                        name = extract_node_text(child, source_code)
                        if name:
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
                        break
            elif n.type == 'class_specifier':
                pass  # Skip class definitions themselves
        
        elif language == 'c':
            if n.type == 'call_expression':
                for child in n.children:
                    if child.type == 'identifier':
                        name = extract_node_text(child, source_code)
                        if name and name[0].isupper():
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
                        break
        
        elif language == 'dart':
            if n.type in ('constructor_invocation', 'const_object_expression'):
                for child in n.children:
                    if child.type in ['identifier', 'type_identifier']:
                        name = extract_node_text(child, source_code)
                        if name and name[0].isupper():
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
                        break
            elif n.type == 'type_annotation':
                for child in n.children:
                    if child.type in ['identifier', 'type_identifier']:
                        name = extract_node_text(child, source_code)
                        if name and name[0].isupper():
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
        
        elif language == 'java':
            if n.type == 'object_creation_expression':
                for child in n.children:
                    if child.type in ['type_identifier', 'identifier']:
                        name = extract_node_text(child, source_code)
                        if name:
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
                        break
        
        elif language == 'kotlin':
            if n.type == 'constructor_invocation' or n.type == 'call_expression':
                for child in n.children:
                    if child.type in ['type_identifier', 'identifier', 'simple_identifier', 'user_type']:
                        name = extract_node_text(child, source_code)
                        if name and name[0].isupper():
                            references.append({
                                'name': name,
                                'location': get_node_location(child),
                                'dependency_type': 'class_reference'
                            })
                        break
        
        stack.extend(reversed(list(n.children)))
    
    return references


def extract_variable_references(node, source_code, language):
    """Extract variable references from a node (iterative to avoid recursion limits)."""
    references = []
    
    skip_types = {'function_definition', 'class_definition', 'function_declaration',
                  'class_declaration', 'method_declaration', 'parameter', 'assignment',
                  'variable_declaration',
                  'function_signature', 'method_signature', 'constructor_declaration',
                  'function_item', 'struct_item', 'enum_item', 'trait_item'}
    
    stack = [node]
    while stack:
        n = stack.pop()
        
        if n.type in skip_types:
            continue
        
        if n.type in ['identifier', 'simple_identifier']:
            name = extract_node_text(n, source_code)
            if name and (name[0].islower() or name[0] == '_'):
                references.append({
                    'name': name,
                    'location': get_node_location(n),
                    'dependency_type': 'variable_reference'
                })
        
        stack.extend(reversed(list(n.children)))
    
    return references


def create_parser(language_module):
    """Create a tree-sitter parser for a language."""
    from tree_sitter import Language, Parser
    
    # Already a Language object (e.g., from tree-sitter-language-pack)
    if isinstance(language_module, Language):
        return Parser(language_module)
    
    # Callable that returns the language pointer
    if callable(language_module):
        lang_obj = language_module()
        
        # New API: PyCapsule — wrap in Language() then pass to Parser
        if isinstance(lang_obj, int):
            # Old-style int pointer — try tree_sitter_language_pack to avoid deprecation
            # This shouldn't normally happen if language_config uses the right modules
            return Parser(Language(lang_obj))
        
        # PyCapsule (tree-sitter >= 0.22) or Language object
        if isinstance(lang_obj, Language):
            return Parser(lang_obj)
        
        # PyCapsule — wrap in Language()
        return Parser(Language(lang_obj))
    
    # Fallback: treat as raw pointer
    return Parser(Language(language_module))
