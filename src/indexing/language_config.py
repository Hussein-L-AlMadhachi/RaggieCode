"""
Language configuration for code indexer.
Maps languages to their file extensions, tree-sitter grammars, and node types.
"""

# Language imports
try:
    from tree_sitter_python import language as python_language
except ImportError:
    python_language = None

try:
    from tree_sitter_go import language as go_language
except ImportError:
    go_language = None

try:
    from tree_sitter_language_pack import get_language as csharp_language_pack

    c_sharp_language = csharp_language_pack("csharp")
except ImportError:
    c_sharp_language = None

try:
    from tree_sitter_language_pack import get_language as javascript_language_pack

    javascript_language = javascript_language_pack("javascript")
except ImportError:
    javascript_language = None

try:
    from tree_sitter_language_pack import get_language as typescript_language_pack

    typescript_language = typescript_language_pack("typescript")
except ImportError:
    typescript_language = None

try:
    from tree_sitter_language_pack import get_language as tsx_language_pack

    tsx_language = tsx_language_pack("tsx")
except ImportError:
    tsx_language = None

try:
    from tree_sitter_rust import language as rust_language
except ImportError:
    rust_language = None

try:
    from tree_sitter_zig import language as zig_language
except ImportError:
    zig_language = None

try:
    from tree_sitter_elixir import language as elixir_language
except ImportError:
    elixir_language = None

try:
    from tree_sitter_cpp import language as cpp_language
except ImportError:
    cpp_language = None

try:
    from tree_sitter_c import language as c_language
except ImportError:
    c_language = None

try:
    from tree_sitter_php import language_php as php_language
except ImportError:
    php_language = None

try:
    from tree_sitter_language_pack import get_language as dart_language_pack

    dart_language = dart_language_pack("dart")
except ImportError:
    dart_language = None

try:
    from tree_sitter_language_pack import get_language as java_language_pack

    java_language = java_language_pack("java")
except ImportError:
    java_language = None

try:
    from tree_sitter_language_pack import get_language as kotlin_language_pack

    kotlin_language = kotlin_language_pack("kotlin")
except ImportError:
    kotlin_language = None


LANGUAGE_CONFIG = {
    "python": {
        "extensions": [".py"],
        "language_module": python_language,
        "node_types": {
            "function": ["function_definition"],
            "class": ["class_definition"],
            "assignment": ["assignment"],
            "type_alias": ["type_alias"],
        },
    },
    "go": {
        "extensions": [".go"],
        "language_module": go_language,
        "node_types": {
            "function": ["function_declaration", "method_declaration"],
            "class": None,
            "struct": ["type_declaration"],
            "interface": ["type_declaration"],
            "method": ["method_declaration"],
            "assignment": ["assignment_statement", "short_var_declaration"],
            "type_alias": ["type_declaration"],
        },
    },
    "csharp": {
        "extensions": [".cs"],
        "language_module": c_sharp_language,
        "node_types": {
            "function": ["method_declaration", "constructor_declaration"],
            "class": ["class_declaration", "record_declaration", "record_struct_declaration"],
            "assignment": ["assignment_expression"],
            "type_alias": None,
            "public_field": [
                "property_declaration",
                "event_declaration",
                "event_field_declaration",
            ],
            "interface": ["interface_declaration"],
            "struct": ["struct_declaration"],
            "enum": ["enum_declaration"],
        },
    },
    "javascript": {
        "extensions": [".js", ".jsx"],
        "language_module": javascript_language,
        "node_types": {
            "function": [
                "function_declaration",
                "generator_function_declaration",
                "method_definition",
            ],
            "class": ["class_declaration"],
            "assignment": ["assignment_expression", "lexical_declaration", "variable_declaration"],
            "type_alias": None,
        },
    },
    "typescript": {
        "extensions": [".ts"],
        "language_module": typescript_language,
        "node_types": {
            "function": ["function_declaration"],
            "class": ["class_declaration", "abstract_class_declaration"],
            "interface": ["interface_declaration"],
            "assignment": ["assignment_expression", "lexical_declaration", "variable_declaration"],
            "type_alias": ["type_alias_declaration"],
            "method": ["method_definition"],
            "public_field": ["public_field_definition"],
            "enum": ["enum_declaration"],
        },
    },
    "tsx": {
        "extensions": [".tsx"],
        "language_module": tsx_language,
        "node_types": {
            "function": ["function_declaration"],
            "class": ["class_declaration", "abstract_class_declaration"],
            "interface": ["interface_declaration"],
            "assignment": ["assignment_expression"],
            "type_alias": ["type_alias_declaration"],
            "method": ["method_definition"],
            "public_field": ["public_field_definition"],
            "enum": ["enum_declaration"],
        },
    },
    "rust": {
        "extensions": [".rs"],
        "language_module": rust_language,
        "node_types": {
            "function": ["function_item"],
            "class": None,
            "struct": ["struct_item"],
            "enum": ["enum_item"],
            "interface": ["trait_item"],
            "assignment": ["let_declaration"],
            "type_alias": ["type_item"],
        },
    },
    "zig": {
        "extensions": [".zig"],
        "language_module": zig_language,
        "node_types": {
            "function": ["FnProto"],
            "class": None,
            "assignment": ["assignment_statement"],
            "type_alias": None,
        },
    },
    "elixir": {
        "extensions": [".ex", ".exs"],
        "language_module": elixir_language,
        "node_types": {
            "function": ["anonymous_function"],
            "class": None,
            "assignment": ["match"],
            "type_alias": None,
        },
    },
    "cpp": {
        "extensions": [".cpp", ".cc", ".cxx", ".hpp", ".h", ".hxx"],
        "language_module": cpp_language,
        "node_types": {
            "function": ["function_definition"],
            "class": ["class_specifier", "struct_specifier"],
            "struct": ["struct_specifier"],
            "enum": ["enum_specifier"],
            "assignment": ["assignment_expression"],
            "type_alias": ["type_alias_declaration", "alias_declaration"],
        },
    },
    "c": {
        "extensions": [".c", ".h"],
        "language_module": c_language,
        "node_types": {
            "function": ["function_definition"],
            "class": None,
            "struct": ["struct_specifier"],
            "enum": ["enum_specifier"],
            "assignment": ["declaration"],
            "type_alias": ["type_definition"],
        },
    },
    "php": {
        "extensions": [".php"],
        "language_module": php_language,
        "node_types": {
            "function": ["function_definition", "method_declaration"],
            "class": ["class_declaration"],
            "interface": ["interface_declaration"],
            "assignment": ["assignment_expression"],
            "type_alias": None,
        },
    },
    "dart": {
        "extensions": [".dart"],
        "language_module": dart_language,
        "node_types": {
            "function": [
                "function_signature",
                "getter_signature",
                "setter_signature",
                "constructor_signature",
                "method_signature",
            ],
            "class": ["class_definition", "mixin_declaration", "extension_declaration"],
            "assignment": ["assignment_expression"],
            "type_alias": ["type_alias"],
        },
    },
    "java": {
        "extensions": [".java"],
        "language_module": java_language,
        "node_types": {
            "function": ["method_declaration", "constructor_declaration"],
            "class": ["class_declaration", "record_declaration", "annotation_type_declaration"],
            "interface": ["interface_declaration"],
            "enum": ["enum_declaration"],
            "assignment": ["assignment_expression"],
            "type_alias": None,
        },
    },
    "kotlin": {
        "extensions": [".kt", ".kts"],
        "language_module": kotlin_language,
        "node_types": {
            "function": ["function_declaration"],
            "class": ["class_declaration", "object_declaration"],
            "interface": ["interface_declaration"],
            "enum": ["enum_declaration"],
            "assignment": ["assignment_expression"],
            "type_alias": ["type_alias"],
        },
    },
}


def get_language_for_extension(file_extension):
    """Get language name for a given file extension."""
    file_ext = file_extension.lower()
    for lang, config in LANGUAGE_CONFIG.items():
        if file_ext in config["extensions"]:
            return lang
    return None


def get_extensions_for_languages(languages):
    """Get all file extensions for a list of languages."""
    extensions = set()
    for lang in languages:
        if lang in LANGUAGE_CONFIG:
            extensions.update(LANGUAGE_CONFIG[lang]["extensions"])
    return extensions


def is_language_available(language):
    """Check if a language's tree-sitter grammar is available."""
    if language not in LANGUAGE_CONFIG:
        return False
    return LANGUAGE_CONFIG[language]["language_module"] is not None


def get_available_languages():
    """Get list of languages with available grammars."""
    return [lang for lang in LANGUAGE_CONFIG.keys() if is_language_available(lang)]


def get_node_types(language):
    """Get node type mapping for a language."""
    if language in LANGUAGE_CONFIG:
        return LANGUAGE_CONFIG[language]["node_types"]
    return {}
