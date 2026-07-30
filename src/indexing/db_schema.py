"""
SQLite database schema for code index.
"""

SCHEMA_SQL = """
-- Files table
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    absolute_path TEXT NOT NULL,
    language TEXT NOT NULL,
    content_hash TEXT,
    mtime REAL
);

-- Functions table (includes both functions and methods)
CREATE TABLE IF NOT EXISTS functions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    parent_id INTEGER,  -- For methods, points to class_id
    parent_type TEXT,  -- 'class' or NULL
    name TEXT NOT NULL,
    type TEXT NOT NULL,  -- 'function' or 'method'
    location TEXT,
    parameters TEXT,  -- JSON array
    return_type TEXT,
    docstring TEXT,
    description TEXT,  -- AI-generated or user-provided description
    receiver TEXT,  -- For Go methods
    branch_count INTEGER DEFAULT 0,  -- Number of conditional branches
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- Classes table
CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    parent_id INTEGER,  -- For nested classes
    name TEXT NOT NULL,
    location TEXT,
    base_classes TEXT,  -- JSON array
    docstring TEXT,
    description TEXT,  -- AI-generated or user-provided description
    namespace TEXT,  -- Containing namespace (C#, etc.)
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- Variables table (includes both top-level variables and class attributes)
CREATE TABLE IF NOT EXISTS variables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    parent_id INTEGER,  -- For class attributes, points to class_id
    parent_type TEXT,  -- 'class' or NULL
    name TEXT NOT NULL,
    type TEXT NOT NULL,  -- 'variable' or 'attribute'
    location TEXT,
    field_type TEXT,  -- For TypeScript public fields
    description TEXT,  -- AI-generated or user-provided description
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- Type aliases table
CREATE TABLE IF NOT EXISTS type_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    location TEXT,
    type_definition TEXT,
    description TEXT,  -- AI-generated or user-provided description
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- Structs table (Go, Rust, C, etc.)
CREATE TABLE IF NOT EXISTS structs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    location TEXT,
    description TEXT,  -- AI-generated or user-provided description
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- Interfaces table (Go, Rust, TypeScript, etc.)
CREATE TABLE IF NOT EXISTS interfaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    location TEXT,
    description TEXT,  -- AI-generated or user-provided description
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- Enums table (Rust, etc.)
CREATE TABLE IF NOT EXISTS enums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    location TEXT,
    description TEXT,  -- AI-generated or user-provided description
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- Namespaces table (C#, etc.)
CREATE TABLE IF NOT EXISTS namespaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    location TEXT,
    description TEXT,  -- AI-generated or user-provided description
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- Temporary symbols table (unresolved dependencies waiting for definition)
-- symbol_type values: 'function_call', 'method_call', 'class_reference', 'variable_reference',
--   plus frontend types: 'component_reference', 'custom_property_reference', 'css_module_class_reference'
CREATE TABLE IF NOT EXISTS temp_symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    symbol_type TEXT NOT NULL,
    file_id INTEGER,
    UNIQUE(name, symbol_type),
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- Dependencies table (tracks imports and all types of references with precise locations)
CREATE TABLE IF NOT EXISTS dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    dependency_type TEXT NOT NULL,  -- 'import', 'function_call', 'class_reference', 'variable_reference', 'method_call', 'module_reference'
    name TEXT NOT NULL,  -- Imported module, called function, referenced class/variable/method name
    source_function_id INTEGER,  -- Which function made the reference/call
    target_function_id INTEGER,  -- For method_call/function_call: the function being called
    target_class_id INTEGER,  -- For method_call: the class containing the method
    temp_symbol_id INTEGER,  -- For unresolved dependencies: points to temp_symbols
    location TEXT,  -- JSON: {start_line, start_column, end_line, end_column, start_byte, end_byte}
    is_external INTEGER DEFAULT 0,  -- 1 for external dependencies, 0 for internal
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (source_function_id) REFERENCES functions(id) ON DELETE SET NULL,
    FOREIGN KEY (target_function_id) REFERENCES functions(id) ON DELETE SET NULL,
    FOREIGN KEY (target_class_id) REFERENCES classes(id) ON DELETE SET NULL,
    FOREIGN KEY (temp_symbol_id) REFERENCES temp_symbols(id) ON DELETE SET NULL
);

-- Indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_functions_file_id ON functions(file_id);
CREATE INDEX IF NOT EXISTS idx_functions_parent_id ON functions(parent_id);
CREATE INDEX IF NOT EXISTS idx_functions_name ON functions(name);
CREATE INDEX IF NOT EXISTS idx_classes_file_id ON classes(file_id);
CREATE INDEX IF NOT EXISTS idx_classes_parent_id ON classes(parent_id);
CREATE INDEX IF NOT EXISTS idx_classes_name ON classes(name);
CREATE INDEX IF NOT EXISTS idx_variables_file_id ON variables(file_id);
CREATE INDEX IF NOT EXISTS idx_variables_parent_id ON variables(parent_id);
CREATE INDEX IF NOT EXISTS idx_variables_name ON variables(name);
CREATE INDEX IF NOT EXISTS idx_type_aliases_file_id ON type_aliases(file_id);
CREATE INDEX IF NOT EXISTS idx_type_aliases_name ON type_aliases(name);
CREATE INDEX IF NOT EXISTS idx_structs_file_id ON structs(file_id);
CREATE INDEX IF NOT EXISTS idx_structs_name ON structs(name);
CREATE INDEX IF NOT EXISTS idx_interfaces_file_id ON interfaces(file_id);
CREATE INDEX IF NOT EXISTS idx_interfaces_name ON interfaces(name);
CREATE INDEX IF NOT EXISTS idx_enums_file_id ON enums(file_id);
CREATE INDEX IF NOT EXISTS idx_enums_name ON enums(name);
CREATE INDEX IF NOT EXISTS idx_namespaces_file_id ON namespaces(file_id);
CREATE INDEX IF NOT EXISTS idx_namespaces_name ON namespaces(name);
CREATE INDEX IF NOT EXISTS idx_dependencies_file_id ON dependencies(file_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_source_function_id ON dependencies(source_function_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_target_function_id ON dependencies(target_function_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_target_class_id ON dependencies(target_class_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_temp_symbol_id ON dependencies(temp_symbol_id);
CREATE INDEX IF NOT EXISTS idx_temp_symbols_name_type ON temp_symbols(name, symbol_type);
CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);

-- ═══════════════════════════════════════════════════════════════
-- Frontend semantic tables (Phase 1 — Requirements §4, §5, §12)
-- ═══════════════════════════════════════════════════════════════

-- Recognized UI components (React function/arrow/class/forwardRef/memo)
CREATE TABLE IF NOT EXISTS frontend_components (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    framework TEXT NOT NULL DEFAULT 'react',
    source_range TEXT,
    is_exported INTEGER DEFAULT 0,
    impl_function_id INTEGER,
    impl_class_id INTEGER,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (impl_function_id) REFERENCES functions(id) ON DELETE SET NULL,
    FOREIGN KEY (impl_class_id) REFERENCES classes(id) ON DELETE SET NULL
);

-- Elements in markup tree (HTML elements, JSX elements, fragments, templates, expressions)
CREATE TABLE IF NOT EXISTS markup_elements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    component_id INTEGER,
    parent_element_id INTEGER,
    tag_name TEXT NOT NULL,
    element_type TEXT NOT NULL,
    source_range TEXT,
    element_id_attr TEXT,
    static_classes TEXT,
    attributes TEXT,
    is_conditional INTEGER DEFAULT 0,
    is_repeated INTEGER DEFAULT 0,
    conditional_expr TEXT,
    repeated_expr TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (component_id) REFERENCES frontend_components(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_element_id) REFERENCES markup_elements(id) ON DELETE CASCADE
);

-- CSS selector definitions
CREATE TABLE IF NOT EXISTS style_selectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    selector_text TEXT NOT NULL,
    normalized_selector TEXT,
    selector_type TEXT NOT NULL,
    source_range TEXT,
    component_id INTEGER,
    is_scoped INTEGER DEFAULT 0,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (component_id) REFERENCES frontend_components(id) ON DELETE SET NULL
);

-- CSS custom property definitions (--name: value)
CREATE TABLE IF NOT EXISTS style_custom_properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    value TEXT,
    source_range TEXT,
    scope_selector TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- CSS custom property usages (var(--name))
CREATE TABLE IF NOT EXISTS style_custom_property_usages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    property_name TEXT NOT NULL,
    source_range TEXT,
    selector_id INTEGER,
    resolved_property_id INTEGER,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (selector_id) REFERENCES style_selectors(id) ON DELETE SET NULL,
    FOREIGN KEY (resolved_property_id) REFERENCES style_custom_properties(id) ON DELETE SET NULL
);

-- Keyframe definitions (@keyframes name)
CREATE TABLE IF NOT EXISTS style_keyframes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    source_range TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- CSS/stylesheet imports (@import, <link rel="stylesheet">, CSS module imports)
CREATE TABLE IF NOT EXISTS style_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    import_path TEXT NOT NULL,
    is_external INTEGER DEFAULT 0,
    resolved_file_id INTEGER,
    source_range TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (resolved_file_id) REFERENCES files(id) ON DELETE SET NULL
);

-- Event handler bindings (onclick, onClick, etc.)
CREATE TABLE IF NOT EXISTS frontend_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    element_id INTEGER,
    event_name TEXT NOT NULL,
    handler_type TEXT NOT NULL,
    handler_expression TEXT,
    handler_symbol_id INTEGER,
    resolution_status TEXT NOT NULL DEFAULT 'unresolved',
    source_range TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (element_id) REFERENCES markup_elements(id) ON DELETE CASCADE,
    FOREIGN KEY (handler_symbol_id) REFERENCES functions(id) ON DELETE SET NULL
);

-- Property/state bindings (disabled={x}, className={cn(...)}, {title}, etc.)
CREATE TABLE IF NOT EXISTS frontend_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    element_id INTEGER,
    binding_type TEXT NOT NULL,
    binding_name TEXT,
    binding_expression TEXT,
    resolution_status TEXT NOT NULL DEFAULT 'unresolved',
    source_range TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (element_id) REFERENCES markup_elements(id) ON DELETE CASCADE
);

-- Component render graph (parent component renders child component or native element)
CREATE TABLE IF NOT EXISTS render_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_component_id INTEGER NOT NULL,
    child_component_id INTEGER,
    child_component_name TEXT,  -- name of referenced component (for cross-file resolution)
    child_element_id INTEGER,
    render_type TEXT NOT NULL,
    controlling_expr TEXT,
    FOREIGN KEY (parent_component_id) REFERENCES frontend_components(id) ON DELETE CASCADE,
    FOREIGN KEY (child_component_id) REFERENCES frontend_components(id) ON DELETE SET NULL,
    FOREIGN KEY (child_element_id) REFERENCES markup_elements(id) ON DELETE SET NULL
);

-- Extraction diagnostics for frontend files
CREATE TABLE IF NOT EXISTS frontend_diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    diagnostic_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT,
    source_range TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

-- Pre-computed selector→element matches for blast radius analysis
CREATE TABLE IF NOT EXISTS style_selector_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    selector_id INTEGER NOT NULL,
    element_id INTEGER NOT NULL,
    match_type TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'high',
    source_range TEXT,
    FOREIGN KEY (selector_id) REFERENCES style_selectors(id) ON DELETE CASCADE,
    FOREIGN KEY (element_id) REFERENCES markup_elements(id) ON DELETE CASCADE
);

-- Indexes for frontend tables
CREATE INDEX IF NOT EXISTS idx_frontend_components_file_id ON frontend_components(file_id);
CREATE INDEX IF NOT EXISTS idx_frontend_components_name ON frontend_components(name);
CREATE INDEX IF NOT EXISTS idx_frontend_components_impl_function_id ON frontend_components(impl_function_id);
CREATE INDEX IF NOT EXISTS idx_frontend_components_impl_class_id ON frontend_components(impl_class_id);
CREATE INDEX IF NOT EXISTS idx_markup_elements_file_id ON markup_elements(file_id);
CREATE INDEX IF NOT EXISTS idx_markup_elements_component_id ON markup_elements(component_id);
CREATE INDEX IF NOT EXISTS idx_markup_elements_parent_element_id ON markup_elements(parent_element_id);
CREATE INDEX IF NOT EXISTS idx_markup_elements_tag_name ON markup_elements(tag_name);
CREATE INDEX IF NOT EXISTS idx_style_selectors_file_id ON style_selectors(file_id);
CREATE INDEX IF NOT EXISTS idx_style_selectors_selector_type ON style_selectors(selector_type);
CREATE INDEX IF NOT EXISTS idx_style_selectors_component_id ON style_selectors(component_id);
CREATE INDEX IF NOT EXISTS idx_style_custom_properties_file_id ON style_custom_properties(file_id);
CREATE INDEX IF NOT EXISTS idx_style_custom_properties_name ON style_custom_properties(name);
CREATE INDEX IF NOT EXISTS idx_style_custom_property_usages_file_id ON style_custom_property_usages(file_id);
CREATE INDEX IF NOT EXISTS idx_style_custom_property_usages_selector_id ON style_custom_property_usages(selector_id);
CREATE INDEX IF NOT EXISTS idx_style_custom_property_usages_resolved_property_id ON style_custom_property_usages(resolved_property_id);
CREATE INDEX IF NOT EXISTS idx_style_keyframes_file_id ON style_keyframes(file_id);
CREATE INDEX IF NOT EXISTS idx_style_keyframes_name ON style_keyframes(name);
CREATE INDEX IF NOT EXISTS idx_style_imports_file_id ON style_imports(file_id);
CREATE INDEX IF NOT EXISTS idx_style_imports_resolved_file_id ON style_imports(resolved_file_id);
CREATE INDEX IF NOT EXISTS idx_frontend_events_file_id ON frontend_events(file_id);
CREATE INDEX IF NOT EXISTS idx_frontend_events_element_id ON frontend_events(element_id);
CREATE INDEX IF NOT EXISTS idx_frontend_events_handler_symbol_id ON frontend_events(handler_symbol_id);
CREATE INDEX IF NOT EXISTS idx_frontend_bindings_file_id ON frontend_bindings(file_id);
CREATE INDEX IF NOT EXISTS idx_frontend_bindings_element_id ON frontend_bindings(element_id);
CREATE INDEX IF NOT EXISTS idx_render_relationships_parent_component_id ON render_relationships(parent_component_id);
CREATE INDEX IF NOT EXISTS idx_render_relationships_child_component_id ON render_relationships(child_component_id);
CREATE INDEX IF NOT EXISTS idx_render_relationships_child_component_name ON render_relationships(child_component_name);
CREATE INDEX IF NOT EXISTS idx_render_relationships_child_element_id ON render_relationships(child_element_id);
CREATE INDEX IF NOT EXISTS idx_frontend_diagnostics_file_id ON frontend_diagnostics(file_id);
CREATE INDEX IF NOT EXISTS idx_frontend_diagnostics_severity ON frontend_diagnostics(severity);
CREATE INDEX IF NOT EXISTS idx_style_selector_matches_selector_id ON style_selector_matches(selector_id);
CREATE INDEX IF NOT EXISTS idx_style_selector_matches_element_id ON style_selector_matches(element_id);
CREATE INDEX IF NOT EXISTS idx_style_custom_property_usages_property_name ON style_custom_property_usages(property_name);
CREATE INDEX IF NOT EXISTS idx_frontend_events_resolution ON frontend_events(handler_symbol_id, handler_type);

-- Temporary file references table (unresolved file-path references waiting for target file to be indexed)
-- Used for: @import, <script src>, <link href>, CSS module imports
CREATE TABLE IF NOT EXISTS temp_file_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resolved_path TEXT NOT NULL,      -- normalized relative path (e.g. "src/components/Button.tsx")
    reference_type TEXT NOT NULL,     -- 'style_import', 'script_import', 'component_import', 'css_module_import'
    source_file_id INTEGER NOT NULL,  -- file making the reference
    target_table TEXT,                -- which table row to update when resolved (e.g. 'style_imports')
    target_row_id INTEGER,            -- row ID in that table
    FOREIGN KEY (source_file_id) REFERENCES files(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_temp_file_refs_path ON temp_file_references(resolved_path);
CREATE INDEX IF NOT EXISTS idx_temp_file_refs_source ON temp_file_references(source_file_id);
"""

def init_database(db_path):
    """Initialize the database with the schema."""
    import sqlite3
    conn = sqlite3.connect(db_path, timeout=30)  # Increase timeout for concurrent access
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
