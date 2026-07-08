# Code Indexer Documentation

A tree-sitter–based source code indexer that parses files across 15 programming languages, extracts symbols (functions, classes, variables, structs, interfaces, enums, type aliases, namespaces), tracks imports and inter-function dependencies, and stores everything in a SQLite database for fast querying.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Supported Languages](#supported-languages)
- [Module Reference](#module-reference)
  - [language_config.py](#language_configpy)
  - [file_utils.py](#file_utilspy)
  - [parse_worker.py](#parse_workerpy)
  - [node_utils.py](#node_utilspy)
  - [extractors.py](#extractorspy)
  - [code_indexer.py](#code_indexerpy)
  - [code_index_sdk.py](#code_index_sdkpy)
  - [queries.py](#queriespy)
  - [models.py](#modelspy)
  - [db_schema.py](#db_schemapy)
  - [cli.py](#clipy)
  - [export_to_json.py](#export_to_jsonpy)
- [Database Schema](#database-schema)
- [Symbol Extraction Pipeline](#symbol-extraction-pipeline)
- [Dependency Tracking](#dependency-tracking)
- [Language-Specific Handling](#language-specific-handling)
- [Known Limitations and Edge Cases](#known-limitations-and-edge-cases)
- [Usage Guide](#usage-guide)
  - [CLI Usage](#cli-usage)
  - [SDK Usage](#sdk-usage)
- [Testing](#testing)

---

## Architecture Overview

```
┌───────────────────────────────────────────────────────────┐
│                       CodeIndexSDK                        │
│      (Public API: index_directory + query methods)        │
│                                                           │
│  ┌──────────────┐      ┌──────────────────────────────┐   │
│  │ QueryMixin   │      │     CodeIndexer              │   │
│  │ (get_*,      │      │  (orchestrates indexing)     │   │
│  │  search_*)   │      │                              │   │
│  └──────────────┘      │  ┌────────────────────────┐  │   │
│                        │  │  ProcessPoolExecutor   │  │   │
│  ┌────────────────┐    │  │  (parallel parsing)    │  │   │
│  │DescriptionMixin│    │  └───────────┬────────────┘  │   │
│  │(set_*_desc)    │    │              │               │   │
│  └────────────────┘    │  ┌───────────▼────────────┐  │   │
│                        │  │  parse_file() (worker) │  │   │
│                        │  │  → tree-sitter parse   │  │   │
│                        │  │  → extract symbols     │  │   │
│                        │  │  → extract imports     │  │   │
│                        │  │  → extract deps        │  │   │
│                        │  └───────────┬────────────┘  │   │
│                        │              │               │   │
│                        │  ┌───────────▼────────────┐  │   │
│                        │  │  SQLite Database       │  │   │
│                        │  │  (batch inserts)       │  │   │
│                        │  └────────────────────────┘  │   │
│                        └──────────────────────────────┘   │
└───────────────────────────────────────────────────────────┘
```

**Data flow:**

1. `CodeIndexSDK.index_directory()` creates a `CodeIndexer` instance.
2. `CodeIndexer` collects files via `file_utils.collect_files_to_index()` (respecting `.aiignore`/`.gitignore`).
3. Changed files (detected by mtime + content hash) are dispatched to `ProcessPoolExecutor` workers.
4. Each worker calls `parse_file()`, which:
   - Detects language from file extension via `language_config.get_language_for_extension()`.
   - Parses source bytes with tree-sitter.
   - Calls `_extract_symbols()` to walk the AST and extract functions, classes, variables, etc.
   - Calls `extract_imports()` to find import statements.
   - Returns a serializable dict of all extracted data.
5. `CodeIndexer._insert_parsed_file()` inserts the results into SQLite in batches.
6. Unresolved dependency references (temp_symbols) are cleaned up after all files are processed.
7. `CodeIndexSDK` query methods (from `QueryMixin`) read from the SQLite database.

---

## Supported Languages

| Language    | Extensions                          | Tree-sitter Package                  |
|-------------|-------------------------------------|--------------------------------------|
| Python      | `.py`                               | `tree_sitter_python`                 |
| Go          | `.go`                               | `tree_sitter_go`                     |
| C#          | `.cs`                               | `tree_sitter_language_pack("csharp")`|
| JavaScript  | `.js`, `.jsx`                       | `tree_sitter_language_pack("javascript")` |
| TypeScript  | `.ts`                               | `tree_sitter_language_pack("typescript")` |
| TSX         | `.tsx`                              | `tree_sitter_language_pack("tsx")`   |
| Rust        | `.rs`                               | `tree_sitter_rust`                   |
| Zig         | `.zig`                              | `tree_sitter_zig`                    |
| Elixir      | `.ex`, `.exs`                       | `tree_sitter_elixir`                 |
| C++         | `.cpp`, `.cc`, `.cxx`, `.hpp`, `.h`, `.hxx` | `tree_sitter_cpp`           |
| C           | `.c`, `.h`                          | `tree_sitter_c`                      |
| PHP         | `.php`                              | `tree_sitter_php`                    |
| Dart        | `.dart`                             | `tree_sitter_language_pack("dart")`  |
| Java        | `.java`                             | `tree_sitter_language_pack("java")`  |
| Kotlin      | `.kt`, `.kts`                       | `tree_sitter_language_pack("kotlin")`|

Languages are gracefully skipped if their tree-sitter grammar is not installed (`language_module is None`).

---

## Module Reference

### `language_config.py`

Defines the `LANGUAGE_CONFIG` dictionary that maps each language to:
- **`extensions`**: list of file extensions
- **`language_module`**: tree-sitter language object (or `None` if not installed)
- **`node_types`**: dictionary mapping symbol categories to tree-sitter node type names

**Node type categories:**
- `function` — function/method definition node types
- `class` — class definition node types (or `None` if language has no classes)
- `assignment` — variable assignment/declaration node types
- `type_alias` — type alias definition node types (or `None`)
- `struct` — struct definition node types (Go, Rust, C, C++)
- `interface` — interface/trait definition node types
- `enum` — enum definition node types
- `method` — method-specific node types (distinct from functions)
- `public_field` — class field/property node types (C#, TypeScript)

**Utility functions:**
- `get_language_for_extension(ext)` — returns language name or `None`
- `get_extensions_for_languages(languages)` — returns set of extensions
- `is_language_available(language)` — checks if grammar is installed
- `get_available_languages()` — lists all languages with installed grammars
- `get_node_types(language)` — returns the node_types dict for a language

### `file_utils.py`

File system utilities for the indexer:

- **`detect_language(file_path)`** — maps file extension to language name
- **`load_ignore_patterns(root_dir)`** — loads `.aiignore` (priority) or `.gitignore` patterns using `pathspec`
- **`collect_files_to_index(root_dir, languages)`** — walks the directory tree, filters by extension and ignore patterns, skips `test`/`tests` directories
- **`read_file_content(file_path)`** — reads file in binary mode for tree-sitter
- **`get_relative_path(file_path, root_dir)`** — returns relative path string

### `parse_worker.py`

The parallel parsing worker. Runs in separate processes via `ProcessPoolExecutor`.

**Key functions:**

- **`parse_file(args)`** — entry point. Takes `(file_path, root_dir)` tuple, returns a dict with all extracted symbols or `{'error': ...}`.
- **`_extract_symbols(...)`** — iteratively walks the tree-sitter AST using an explicit stack (avoids recursion limits on deeply nested files like Linux kernel C). Matches node types against `LANGUAGE_CONFIG` and dispatches to extractor functions.
- **`_process_class_body(...)`** — processes class body children to extract methods, nested classes, and attributes.
- **`_extract_deps(node, source_code, language, dependencies, func_index)`** — extracts function calls, class references, and variable references from a function node, attaching them to the function at `func_index`.

**Special handling:**
- **C# top-level statements**: collected into a pseudo-function named `top_level_statements`
- **Elixir**: `def`/`defp`/`defmacro`/`defmacrop` calls are treated as function definitions; `defmodule` calls are treated as classes. Functions and modules are `call` nodes, not dedicated declaration nodes.
- **Dart**: `function_signature` and `function_body` are sibling nodes (not parent-child). Dependency extraction combines both siblings.
- **Rust**: `impl_item` blocks create pseudo-classes so methods can be associated with their implementing type. `const_item` and `static_item` are treated as global variables.

### `node_utils.py`

The largest module (~1100 lines). Contains all tree-sitter node inspection utilities:

**Location and text extraction:**
- `get_node_location(node)` — returns `{start_line, start_column, end_line, end_column, start_byte, end_byte}` (1-indexed lines)
- `extract_node_text(node, source_code)` — extracts text using byte offsets (handles UTF-8 correctly)
- `extract_field_text(node, field_name, source_code)` — extracts text from a named field child

**Name extraction:**
- `extract_name(node, source_code, language)` — language-specific name extraction for functions, classes, structs, enums, etc. Handles `identifier`, `simple_identifier`, `type_identifier`, `field_identifier` across languages.

**Variable name extraction:**
- `extract_variable_name(node, source_code, language)` — extracts the variable name from an assignment/declaration node. Returns `(name, is_attribute)` tuple. Language-specific:
  - Python: `left` field of `assignment` node
  - JavaScript/TypeScript: `lexical_declaration`/`variable_declaration` → `variable_declarator` → `identifier`
  - Java/Dart: `left` field
  - Kotlin: `directly_assignable_expression` → `simple_identifier` (no `left` field)
  - Zig: direct `identifier` child of `variable_declaration`
  - Elixir: `binary_operator` with `=` operator → `left` field → `identifier`

**Other extraction utilities:**
- `extract_parameters(node, source_code, language)` — extracts parameter list
- `extract_return_type(node, source_code)` — extracts return type annotation
- `extract_base_classes(node, source_code, language)` — extracts base/parent class names
- `extract_docstring(node, source_code, language)` — extracts docstrings (Python, Go, JavaScript, Rust)
- `is_method(node, language, class_node_type)` — determines if a function is a method
- `count_branches(node, language, source_code)` — counts conditional branches (if/for/while/switch/try etc.) with language-specific node type mappings

**Import extraction:**
- `extract_imports(node, source_code, language, root_dir)` — iteratively finds import nodes. Language-specific import node types:
  - Python: `import_statement`, `import_from_statement`
  - Go: `import_declaration`
  - JavaScript/TypeScript/TSX: `import_statement`, `import_declaration`
  - C#: `using_directive`, `global_using_directive`
  - Rust: `use_declaration`, `extern_crate_declaration`
  - C/C++: `include_directive`, `preproc_include`
  - Zig: `builtin_function` (filtered to only `@import` calls)
  - Elixir: `alias` (only alias nodes; see [Known Limitations](#known-limitations-and-edge-cases))
  - PHP: `include_expression`, `include_once_expression`, `require_expression`, `require_once_expression`, `namespace_use_declaration`
  - Dart: `import_or_export`
  - Java: `import_declaration`
  - Kotlin: `import_header`

**External vs. internal import detection:**
- `_is_external_import(import_text, language, root_path)` — determines if an import is external (third-party) or internal (project-local). Language-specific heuristics:
  - Python: checks for `.` in module name and whether the package directory exists
  - Go: checks for `.` in import path (external) vs. internal module path
  - C/C++: `#include "local.h"` is internal, `#include <system.h>` is external
  - C#: checks against standard .NET namespaces and project directory structure
  - Elixir: converts CamelCase module name to snake_case and checks if `lib/<snake_path>.ex` exists
  - PHP: relative paths in include/require are internal; `use` statements checked against project structure
  - Zig: `@import("std")`, `@import("builtin")`, `@import("root")` are external; file paths are internal

**Function call extraction:**
- `extract_function_calls(node, source_code, language)` — finds all function/method calls within a node. Language-specific call node types:
  - Most languages: `call_expression` (or `call` in Python)
  - Dart: `expression_statement` with custom parsing of `identifier` + `selector` + `arguments` pattern (Dart has no `call_expression` node type)
  - Zig: `call_expression`
  - Elixir: `call` nodes (keyword-filtered in branch counting)

**Class reference extraction:**
- `extract_class_references(node, source_code, language)` — finds class instantiations and type references. Language-specific:
  - Python: `call` where function name starts with uppercase
  - JavaScript/TypeScript: `new_expression`
  - Java: `object_creation_expression`
  - Dart: `constructor_invocation`, `const_object_expression`, `type_annotation`
  - C++: `new_expression` with type extraction

**Variable reference extraction:**
- `extract_variable_references(node, source_code, language)` — finds variable references, skipping function/class definitions and parameter declarations.

### `extractors.py`

Functions that combine multiple `node_utils` calls to produce structured symbol info:

- **`extract_function_info(node, source_code, language, class_node_type)`** — returns `{type, name, location, parameters, return_type, docstring, branch_count, receiver?}`
- **`extract_class_info(node, source_code, language)`** — returns `{type, name, location, base_classes, docstring, methods, nested_classes, variables}`
- **`extract_variable_info(node, source_code, language)`** — returns `{type: "variable"|"attribute", name, location}`
- **`extract_type_alias_info(node, source_code, language)`** — returns `{type: "type_alias", name, location, type_definition}`
- **`extract_macro_info(node, source_code, language)`** — for C/Rust macros: `{type: "macro", name, location, parameters, ...}`
- **`extract_struct_info(node, source_code, language)`** — `{type: "struct", name, location}`
- **`extract_go_struct_info(node, source_code)`** — Go-specific struct extraction with fields
- **`extract_interface_info(node, source_code, language)`** — `{type: "interface", name, location}`
- **`extract_go_interface_info(node, source_code)`** — Go-specific interface extraction with methods
- **`extract_enum_info(node, source_code, language)`** — `{type: "enum", name, location}`

### `code_indexer.py`

The `CodeIndexer` class orchestrates the full indexing process:

- **`__init__(root_dir, languages, db_path, force_reindex, verbose)`** — initializes database, parsers, and statistics
- **`index_directory()`** — main entry point:
  1. Collects files to index
  2. Identifies changed files (mtime check → content hash check)
  3. Dispatches changed files to `ProcessPoolExecutor` workers
  4. Inserts parsed results into SQLite in batches (`batch_size = 2000`)
  5. Flushes remaining batches and cleans up unresolved temp_symbols
  6. Prints summary statistics if verbose

**Incremental reindexing:** Files are only re-parsed if both their mtime and content hash (xxhash64) have changed. The mtime check is a fast path; the content hash check handles cases where mtime changed but content didn't (e.g., `touch`).

**Batch insertion:** Uses `executemany()` for bulk inserts to minimize SQLite overhead. Batches are flushed when they reach `batch_size` or at the end of indexing.

### `code_index_sdk.py`

The `CodeIndexSDK` class is the public API for both indexing and querying:

```python
class CodeIndexSDK(QueryMixin, DescriptionMixin):
    def __init__(self, db_path, root_dir=None)
    def index_directory(self, force_reindex=False, verbose=False)
    def close(self)
    # Context manager support: __enter__ / __exit__
```

Inherits all query methods from `QueryMixin` and all description-update methods from `DescriptionMixin`.

### `queries.py`

Contains `QueryMixin` (read queries) and `DescriptionMixin` (description updates).

**QueryMixin methods:**

| Category    | Methods |
|-------------|---------|
| Files       | `get_files(language?)`, `get_file_by_path(path)`, `get_file_by_id(id)`, `get_files_by_language(lang)` |
| Functions   | `get_functions(file_id?)`, `get_function_by_id(id)`, `get_function_by_name(name, file_id?)`, `search_functions(pattern, file_id?)`, `get_file_functions(file_id)` |
| Complexity  | `get_functions_by_complexity(min_branches?, min_lines?, max_branches?)`, `get_complex_symbols(min_branches, min_lines, match_any)`, `get_methods_by_complexity(class_id, ...)` |
| Methods     | `get_methods(class_id)`, `get_method_by_name(class_id, name)`, `get_class_methods(class_id)` |
| Classes     | `get_classes(file_id?)`, `get_class_by_id(id)`, `get_class_by_name(name, file_id?)`, `search_classes(pattern, file_id?)`, `get_file_classes(file_id)`, `get_nested_classes(class_id)`, `get_class_variables(class_id)` |
| Variables   | `get_variables(file_id?)`, `get_variable_by_id(id)`, `get_variable_by_name(name, file_id?)`, `search_variables(pattern, file_id?)`, `get_file_variables(file_id)` |
| Type Aliases| `get_type_aliases(file_id?)`, `get_type_alias_by_id(id)`, `get_type_alias_by_name(name, file_id?)`, `search_type_aliases(pattern, file_id?)` |
| Structs     | `get_structs(file_id?)`, `get_struct_by_id(id)`, `get_struct_by_name(name, file_id?)` |
| Enums       | `get_enums(file_id?)`, `get_enum_by_id(id)`, `get_enum_by_name(name, file_id?)` |
| Namespaces  | `get_namespaces(file_id?)`, `get_namespace_by_id(id)`, `get_namespace_by_name(name, file_id?)`, `get_file_namespaces(file_id)` |
| Interfaces  | `get_interfaces(file_id?)`, `get_interface_by_id(id)`, `get_interface_by_name(name, file_id?)` |
| Dependencies| `get_dependencies(file_id?)`, `get_file_imports(file_id)`, `get_external_imports(file_id?)`, `get_internal_imports(file_id?)`, `get_function_calls(func_id)`, `get_function_dependencies(func_id, type?)`, `get_function_method_calls(func_id)`, `get_function_class_references(func_id)`, `get_function_variable_references(func_id)`, `get_function_dependencies_by_name(name, file_id?, type?)`, `get_function_dependencies_grouped(func_id)`, `get_file_function_calls(file_id)` |
| Statistics  | `get_statistics()`, `get_language_statistics()` |

**DescriptionMixin methods:**
- `set_function_description(id, desc)`, `set_function_description_by_name(name, desc, file_path?)`
- `set_method_description(id, desc)`, `set_class_description(id, desc)`, `set_class_description_by_name(...)`
- `set_variable_description(id, desc)`, `set_variable_description_by_name(...)`
- `set_type_alias_description(id, desc)`, `set_type_alias_description_by_name(...)`
- `set_struct_description(id, desc)`, `set_struct_description_by_name(...)`
- (and similar for interfaces, enums, namespaces)

### `models.py`

Dataclasses representing code entities:

- **`Location`** — `start_line`, `start_column`, `end_line`, `end_column`, `start_byte?`, `end_byte?`
- **`Function`** — `id`, `name`, `type` (`"function"` or `"method"`), `file_id`, `file_path`, `location`, `parameters`, `return_type?`, `docstring?`, `description?`, `receiver?`, `parent_id?`, `parent_type?`, `branch_count`
- **`Class`** — `id`, `name`, `file_id`, `file_path`, `location`, `base_classes`, `docstring?`, `description?`, `parent_id?`, `namespace?`
- **`Variable`** — `id`, `name`, `type` (`"variable"` or `"attribute"`), `file_id`, `file_path`, `location`, `field_type?`, `description?`, `parent_id?`, `parent_type?`
- **`TypeAlias`** — `id`, `name`, `file_id`, `file_path`, `location`, `type_definition?`, `description?`
- **`Struct`** — `id`, `name`, `file_id`, `file_path`, `location`, `description?`
- **`Interface`** — `id`, `name`, `file_id`, `file_path`, `location`, `description?`
- **`Enum`** — `id`, `name`, `file_id`, `file_path`, `location`, `description?`
- **`Namespace`** — `id`, `name`, `file_id`, `file_path`, `location`, `description?`
- **`File`** — `id`, `path`, `absolute_path`, `language`
- **`Dependency`** — `id`, `file_id`, `file_path`, `dependency_type`, `name`, `source_function_id?`, `target_function_id?`, `target_class_id?`, `location?`, `is_external`

All models have a `from_row(row, file_path?)` classmethod for constructing from SQLite rows.

### `db_schema.py`

Defines the SQLite schema via `SCHEMA_SQL` string and `init_database(db_path)` function.

### `cli.py`

Command-line argument parsing:
- `directory` — directory to index
- `-l/--languages` — comma-separated language filter
- `-o/--output` — output database path (default: `code_index.db`)
- `--list-languages` — print supported languages and exit
- `--export-json` — export database to JSON
- `--force` — force reindex all files
- `--graph` — view dependency graph for a file

### `export_to_json.py`

Exports the SQLite index database to a JSON file for external consumption or backup.

---

## Database Schema

### `files`
| Column         | Type    | Description                        |
|----------------|---------|------------------------------------|
| `id`           | INTEGER | Primary key                        |
| `path`         | TEXT    | Relative path (unique)             |
| `absolute_path`| TEXT    | Absolute filesystem path           |
| `language`     | TEXT    | Language name                      |
| `content_hash` | TEXT    | xxhash64 hex digest                |
| `mtime`        | REAL    | File modification time             |

### `functions`
| Column         | Type    | Description                        |
|----------------|---------|------------------------------------|
| `id`           | INTEGER | Primary key                        |
| `file_id`      | INTEGER | FK to files                        |
| `parent_id`    | INTEGER | FK to classes (for methods)        |
| `parent_type`  | TEXT    | `"class"` or NULL                  |
| `name`         | TEXT    | Function/method name               |
| `type`         | TEXT    | `"function"`, `"method"`, or `"macro"` |
| `location`     | TEXT    | JSON location object               |
| `parameters`   | TEXT    | JSON array of parameter dicts      |
| `return_type`  | TEXT    | Return type annotation             |
| `docstring`    | TEXT    | Extracted docstring                |
| `description`  | TEXT    | User/AI-provided description       |
| `receiver`     | TEXT    | Go method receiver                 |
| `branch_count` | INTEGER | Number of conditional branches     |

### `classes`
| Column         | Type    | Description                        |
|----------------|---------|------------------------------------|
| `id`           | INTEGER | Primary key                        |
| `file_id`      | INTEGER | FK to files                        |
| `parent_id`    | INTEGER | FK to classes (nested classes)     |
| `name`         | TEXT    | Class name                         |
| `location`     | TEXT    | JSON location object               |
| `base_classes` | TEXT    | JSON array of base class names     |
| `docstring`    | TEXT    | Extracted docstring                |
| `description`  | TEXT    | User/AI-provided description       |
| `namespace`    | TEXT    | Containing namespace (C#)          |

### `variables`
| Column         | Type    | Description                        |
|----------------|---------|------------------------------------|
| `id`           | INTEGER | Primary key                        |
| `file_id`      | INTEGER | FK to files                        |
| `parent_id`    | INTEGER | FK to classes (for attributes)     |
| `parent_type`  | TEXT    | `"class"` or NULL                  |
| `name`         | TEXT    | Variable name                      |
| `type`         | TEXT    | `"variable"` or `"attribute"`      |
| `location`     | TEXT    | JSON location object               |
| `field_type`   | TEXT    | TypeScript field type              |
| `description`  | TEXT    | User/AI-provided description       |

### `type_aliases`, `structs`, `interfaces`, `enums`, `namespaces`
Each has: `id`, `file_id`, `name`, `location` (JSON), `description`. Type aliases also have `type_definition`.

### `dependencies`
| Column                | Type    | Description                                      |
|-----------------------|---------|--------------------------------------------------|
| `id`                  | INTEGER | Primary key                                      |
| `file_id`             | INTEGER | FK to files                                      |
| `dependency_type`     | TEXT    | `import`, `function_call`, `method_call`, `class_reference`, `variable_reference`, `module_reference` |
| `name`                | TEXT    | Imported module, called function, referenced name |
| `source_function_id`  | INTEGER | FK to functions (which function made the call)   |
| `target_function_id`  | INTEGER | FK to functions (resolved target)                |
| `target_class_id`     | INTEGER | FK to classes (resolved target class)            |
| `temp_symbol_id`      | INTEGER | FK to temp_symbols (unresolved reference)        |
| `location`            | TEXT    | JSON location of the reference                   |
| `is_external`         | INTEGER | 1 = external/third-party, 0 = internal           |

### `temp_symbols`
Temporary table for unresolved dependency references. During indexing, function calls and class references that don't match any defined symbol are stored here. After all files are indexed, remaining temp_symbols (unresolved references to external/builtin symbols) are cleaned up along with their dependencies.

---

## Symbol Extraction Pipeline

The extraction pipeline in `_extract_symbols()` uses an **iterative stack-based traversal** of the tree-sitter AST (rather than recursion) to avoid stack overflow on deeply nested files (e.g., Linux kernel C files with hundreds of nested blocks).

**Traversal logic:**

1. Start with the root node on the stack.
2. For each node popped from the stack:
   - If it matches a **function** node type → extract function info, extract dependencies, push children with `in_function=True`.
   - If it matches a **class** node type → extract class info, process class body for methods/attributes.
   - If it matches **struct/interface/enum/type_alias** → extract and store.
   - If it matches an **assignment** node type and not inside a function → extract variable.
   - Language-specific special cases (Elixir calls, Rust impl blocks, C# top-level statements).
   - Otherwise, push children onto the stack with the same state.

**State tracked during traversal:**
- `in_function` — whether we're inside a function body (affects variable extraction)
- `current_class_id` — the class ID for method association
- `current_namespace` — the namespace for C# class association

---

## Dependency Tracking

The indexer tracks multiple types of dependencies:

### Import Dependencies
Extracted by `extract_imports()` at the file level. Each import is classified as internal or external via `_is_external_import()`.

### Function-Level Dependencies
Extracted by `_extract_deps()` for each function:

- **`function_call`** — direct function calls (e.g., `foo()`)
- **`method_call`** — method calls on objects (e.g., `obj.method()`)
- **`class_reference`** — class instantiations and type references (e.g., `new Foo()`)
- **`variable_reference`** — variable references within function bodies

### Resolution Process
During database insertion:
1. Each dependency is initially stored with a `temp_symbol_id` pointing to a `temp_symbols` entry.
2. When a function or class is inserted, its name is matched against existing temp_symbols of the corresponding type.
3. Matched temp_symbols are resolved: the dependency's `target_function_id` or `target_class_id` is set, and the temp_symbol is deleted.
4. After all files are processed, remaining temp_symbols (unresolved external references) and their dependencies are deleted.

---

## Language-Specific Handling

### Python
- Functions: `function_definition` nodes
- Classes: `class_definition` nodes
- Assignments: `assignment` nodes (left side = variable name)
- Imports: `import_statement`, `import_from_statement`
- Docstrings: extracted from first `block` child's `expression_statement` → `string` node

### Go
- Functions: `function_declaration`, `method_declaration`
- Structs and interfaces: both use `type_declaration` nodes; distinguished by `struct_type` vs `interface_type` child
- Methods: identified by `method_declaration` with a receiver parameter
- Imports: `import_declaration`

### C#
- Functions: `method_declaration`, `constructor_declaration`
- Classes: `class_declaration`, `record_declaration`, `record_struct_declaration`
- Top-level statements (C# 9): collected into a pseudo-function `top_level_statements`
- Namespaces: tracked and associated with classes
- Imports: `using_directive`, `global_using_directive`
- Public fields: `property_declaration`, `event_declaration`, `event_field_declaration`

### JavaScript / TypeScript / TSX
- Functions: `function_declaration`, `generator_function_declaration` (JS), `method_definition`
- Classes: `class_declaration`, `abstract_class_declaration` (TS)
- Assignments: `assignment_expression`, `lexical_declaration` (let/const), `variable_declaration` (var)
- TypeScript-specific: `interface_declaration`, `type_alias_declaration`, `enum_declaration`, `public_field_definition`
- Imports: `import_statement`, `import_declaration`

### Rust
- Functions: `function_item`
- Structs: `struct_item`; Enums: `enum_item`; Traits: `trait_item`
- Impl blocks: `impl_item` creates a pseudo-class so methods are associated with their type
- Global variables: `const_item`, `static_item`
- Imports: `use_declaration`, `extern_crate_declaration`
- Type aliases: `type_item`

### Zig
- Functions: `function_declaration`
- Variables: `variable_declaration` (const/var) — identifier is a direct child, not a `left` field
- Imports: `builtin_function` nodes, filtered to only `@import(...)` calls (other builtins like `@as`, `@bitCast` are excluded)
- Function calls: `call_expression`
- Branch types: `if_statement`, `for_statement`, `while_statement`, `switch_statement`

### Elixir
- **Functions**: `def`/`defp`/`defmacro`/`defmacrop` are `call` nodes, not dedicated declaration nodes. The function name is extracted from the first argument (either an `identifier` inside a `call`, a direct `identifier`, or an `atom`).
- **Modules**: `defmodule` calls are treated as classes. The module name is extracted from the `alias` argument.
- **Assignments**: `binary_operator` nodes where the operator is `=`. The variable name comes from the `left` field.
- **Imports**: Only `alias` nodes are captured as imports. See [Known Limitations](#known-limitations-and-edge-cases).
- **Branch counting**: `call` nodes are checked for control-flow keywords (`if`, `case`, `cond`, `try`, `receive`, `for`, `with`, `unless`). Only calls whose first `identifier` child matches one of these keywords are counted as branches.

### C / C++
- Functions: `function_definition` (name extracted from `function_declarator` or `declarator` child)
- Classes (C++): `class_specifier`, `struct_specifier`
- Structs: `struct_specifier`
- Enums: `enum_specifier`
- Imports: `include_directive`, `preproc_include` (`#include "local.h"` = internal, `#include <system.h>` = external)
- C macros: `preproc_def`, `preproc_function_def` (treated as functions with type `"macro"`)
- C type aliases: `type_definition` (`typedef`)
- C++ type aliases: `type_alias_declaration`, `alias_declaration`

### PHP
- Functions: `function_definition`, `method_declaration`
- Classes: `class_declaration`; Interfaces: `interface_declaration`
- Imports: `include_expression`, `include_once_expression`, `require_expression`, `require_once_expression`, `namespace_use_declaration`
- External detection: relative paths in include/require are internal; `use` statements checked against project structure

### Dart
- Functions: `function_signature`, `getter_signature`, `setter_signature`, `constructor_signature`, `method_signature`
- **Key difference**: `function_signature`/`method_signature` and `function_body` are **sibling nodes**, not parent-child. The indexer combines both siblings for dependency extraction.
- Classes: `class_definition`, `mixin_declaration`, `extension_declaration`
- Imports: `import_or_export`
- Function calls: `expression_statement` nodes with custom parsing of `identifier` + `selector` + `arguments` pattern (Dart has no `call_expression` node type)
- Class references: `constructor_invocation`, `const_object_expression`, `type_annotation`
- Branch types: `if_statement`, `for_statement` (covers both for and for-in), `while_statement`, `switch_statement`, `try_statement`

### Java
- Functions: `method_declaration`, `constructor_declaration`
- Classes: `class_declaration`, `record_declaration`, `annotation_type_declaration`
- Interfaces: `interface_declaration`; Enums: `enum_declaration`
- Imports: `import_declaration`
- Class references: `object_creation_expression`

### Kotlin
- Functions: `function_declaration`
- Classes: `class_declaration`, `object_declaration`
- Interfaces and enums: handled via `class_declaration` in `_extract_symbols` (Kotlin's tree-sitter grammar uses `class_declaration` for all three, with `interface`/`enum` keyword children to distinguish)
- Assignments: `assignment` nodes (not `assignment_expression`). The variable name is inside a `directly_assignable_expression` → `simple_identifier`, not a `left` field.
- Imports: `import_header`
- Branch types: `if_expression`, `for_statement`, `while_statement`, `do_while_statement`, `when_expression`, `try_expression`

---

## Known Limitations and Edge Cases

### Elixir Imports (import/require/use not captured)
Elixir imports are extracted via `alias` nodes only. The `import`, `require`, and `use` calls in Elixir are **not captured as imports** by the indexer. This is a known limitation:

- In Elixir's tree-sitter grammar, `import`, `require`, and `use` are `call` nodes (same as function calls), not dedicated import node types.
- `alias` is the only directive that produces its own node type (`alias`), so it's the only one captured.
- `alias` is the primary import mechanism in Elixir for bringing modules into scope, so this covers the majority of real-world usage.
- The `import`/`require`/`use` directives could be captured in the future by adding special handling for `call` nodes whose first identifier is `import`, `require`, or `use`.

### Elixir Function Metadata
Elixir functions extracted from `call` nodes have limited metadata:
- Parameters are not parsed (returned as empty list).
- Return types are not available (Elixir is dynamically typed).
- Docstrings are not extracted.

### Dart Function Body Siblings
Dart's tree-sitter grammar separates `function_signature` (or `method_signature`) from `function_body` as sibling nodes. The indexer handles this by:
1. When a signature is matched, searching for the next `function_body` sibling.
2. Extracting dependencies from both the signature and the body.
3. This is handled in both `_extract_symbols()` (top-level functions) and `_process_class_body()` (methods inside classes).

### Kotlin Interface/Enum Detection
Kotlin's tree-sitter grammar uses `class_declaration` for classes, interfaces, and enums. The `_extract_symbols()` function checks for `interface` and `enum` keyword children to reclassify these nodes. The `LANGUAGE_CONFIG` for Kotlin does not include `interface` or `enum` node types — they are handled entirely in `parse_worker.py` logic.

### Test Directory Skipping
`file_utils.collect_files_to_index()` skips directories named `test` or `tests`. This is a hard-coded filter that cannot be configured via ignore patterns. This may cause issues for projects that have legitimate source code in directories named `test`.

### Ignore File Priority
The indexer checks for `.aiignore` first, falling back to `.gitignore` if `.aiignore` doesn't exist. Both use `pathspec` with `GitWildMatchPattern` for git-compatible pattern matching.

### Content Hash for Incremental Reindexing
The indexer uses xxhash64 for content hashing, which is fast but not cryptographically secure. This is acceptable for change detection but should not be relied upon for integrity verification.

### Parallel Processing
File parsing runs in a `ProcessPoolExecutor` with `min(cpu_count, file_count)` workers. Parsers are cached per-worker process via a global `_parsers` dict. Batch size for in-flight futures is `max_workers * 256` to bound memory usage on large codebases.

### Unresolved Dependencies
Function calls and class references that don't match any defined symbol in the codebase are stored as `temp_symbols` during indexing. After all files are processed, these are cleaned up — their dependencies are deleted from the `dependencies` table. This means external function calls (e.g., `print()` in Python, `fmt.Println()` in Go) are not retained in the final database.

---

## Usage Guide

### CLI Usage

```bash
# Index all supported languages in a directory
python -m indexing.code_indexer /path/to/project

# Index only Python and Go files
python -m indexing.code_indexer /path/to/project -l python,go

# Use a custom database path
python -m indexing.code_indexer /path/to/project -o my_index.db

# Force reindex all files (ignore mtime/hash checks)
python -m indexing.code_indexer /path/to/project --force

# List supported languages
python -m indexing.code_indexer --list-languages

# Export database to JSON
python -m indexing.code_indexer /path/to/project --export-json output.json

# View dependency graph for a file
python -m indexing.code_indexer /path/to/project --graph src/main.py
```

### SDK Usage

```python
from indexing.code_index_sdk import CodeIndexSDK

# Initialize and index
sdk = CodeIndexSDK(db_path="code_index.db", root_dir="/path/to/project")
sdk.index_directory(verbose=True)

# Query functions
functions = sdk.get_functions()
render_funcs = sdk.search_functions("render")
file_funcs = sdk.get_file_functions(file_id=42)

# Query classes and methods
classes = sdk.get_classes()
cls = sdk.get_class_by_name("UserService")[0]
methods = sdk.get_class_methods(cls.id)
nested = sdk.get_nested_classes(cls.id)

# Query dependencies
imports = sdk.get_file_imports(file_id=42)
external_imports = sdk.get_external_imports(file_id=42)
func_calls = sdk.get_function_calls(function_id=10)
all_deps = sdk.get_function_dependencies_grouped(function_id=10)

# Complexity analysis
complex_funcs = sdk.get_complex_symbols(min_branches=10, min_lines=50)
complex_methods = sdk.get_methods_by_complexity(class_id=cls.id, min_branches=5)

# Statistics
stats = sdk.get_statistics()
lang_stats = sdk.get_language_statistics()

# Set descriptions (for AI-assisted documentation)
sdk.set_function_description_by_name("render", "Renders the view template")

# Context manager
with CodeIndexSDK("code_index.db", "/path/to/project") as sdk:
    files = sdk.get_files(language="python")
    for f in files:
        print(f"{f.path} ({f.language})")

sdk.close()
```

---

## Testing

Tests are located in `tests/indexing/` and cover:

- **`test_config.py`** — language config validation (no duplicates, node types are lists or None)
- **`test_python.py`** — Python-specific extraction (functions, classes, methods, imports, variables, docstrings, branches, base classes, dependencies)
- **`test_go.py`** — Go-specific extraction (functions, structs, interfaces, type aliases, imports, methods, branches)
- **`test_rust.py`** — Rust-specific extraction (functions, structs, enums, imports)
- **`test_c_family.py`** — C and C++ extraction (functions, classes, enums, imports)
- **`test_web_languages.py`** — JavaScript and TypeScript extraction
- **`test_jvm_languages.py`** — Java and Kotlin extraction
- **`test_pipeline.py`** — full indexing pipeline and incremental reindexing
- **`test_real_projects.py`** — integration tests against real open-source projects cloned per language

Run tests:
```bash
python -m pytest tests/ -v --tb=short
```
