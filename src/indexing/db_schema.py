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
CREATE TABLE IF NOT EXISTS temp_symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    symbol_type TEXT NOT NULL,  -- matches dependency_type: 'function_call', 'method_call', 'class_reference', 'variable_reference'
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
CREATE INDEX IF NOT EXISTS idx_dependencies_temp_symbol_id ON dependencies(temp_symbol_id);
CREATE INDEX IF NOT EXISTS idx_temp_symbols_name_type ON temp_symbols(name, symbol_type);
CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
"""

def init_database(db_path):
    """Initialize the database with the schema."""
    import sqlite3
    conn = sqlite3.connect(db_path, timeout=30)  # Increase timeout for concurrent access
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
