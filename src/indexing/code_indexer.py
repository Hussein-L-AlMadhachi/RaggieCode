#!/usr/bin/env python3
"""
Code Indexer using tree-sitter
Indexes files in a codebase and tracks functions, classes, variables, methods, and type definitions.
Supports multiple languages: Python, Go, C#, JavaScript, TypeScript, Rust, Zig, Elixir, C++, PHP
"""

import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import xxhash

from indexing.language_config import (
    LANGUAGE_CONFIG,
)
from indexing.node_utils import create_parser
from indexing.file_utils import (
    detect_language,
    collect_files_to_index,
    read_file_content,
    get_relative_path
)
from indexing.cli import parse_arguments, list_supported_languages
from indexing.db_schema import init_database
from indexing.export_to_json import export_to_json
from indexing.code_index_sdk import CodeIndexSDK
from indexing.parse_worker import parse_file


VAR_DATA = "this is to test the indexer"

class CodeIndexer:
    def __init__(self, root_dir, languages=None, db_path=".code_index.raggie", force_reindex=False, verbose=False):
        self.root_dir = Path(root_dir)
        self.languages = languages if languages else list(LANGUAGE_CONFIG.keys())
        self.parsers = {}
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.current_file_id = None
        self.current_class_id = None
        self.force_reindex = force_reindex
        self.batch_size = 2000
        self.verbose = verbose
        
        # Statistics counters
        self.stats = {
            "total_functions": 0,
            "total_macros": 0,
            "total_classes": 0,
            "total_variables": 0,
            "total_methods": 0,
            "total_type_defs": 0,
            "total_structs": 0,
            "total_interfaces": 0,
            "total_enums": 0,
            "total_namespaces": 0,
            "skipped_files": 0
        }
        
        # Batch buffers for executemany()
        self.batches = {
            "files": [],
            "functions": [],
            "classes": [],
            "variables": [],
            "type_aliases": [],
            "structs": [],
            "interfaces": [],
            "dependencies": []
        }
        
        self._initialize_database()
        self._initialize_parsers()
    
    def _flush_batches(self):
        """Flush all batch buffers using executemany()."""
        if self.batches["variables"]:
            self.cursor.executemany(
                """INSERT INTO variables 
                   (file_id, parent_id, parent_type, name, type, location, field_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                self.batches["variables"]
            )
            self.batches["variables"] = []
        
        if self.batches["type_aliases"]:
            self.cursor.executemany(
                """INSERT INTO type_aliases 
                   (file_id, name, location, type_definition)
                   VALUES (?, ?, ?, ?)""",
                self.batches["type_aliases"]
            )
            self.batches["type_aliases"] = []
        
        if self.batches["dependencies"]:
            self.cursor.executemany(
                """INSERT INTO dependencies (file_id, dependency_type, name, source_function_id, target_function_id, target_class_id, temp_symbol_id, location, is_external)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                self.batches["dependencies"]
            )
            self.batches["dependencies"] = []
        
        self.conn.commit()
    
    def _check_and_flush(self, batch_name):
        """Check if a batch has reached the size limit and flush if so."""
        if len(self.batches[batch_name]) >= self.batch_size:
            self._flush_batches()

    def _initialize_database(self):
        """Initialize SQLite database."""
        self.conn = init_database(self.db_path)
        # Optimized settings for batch indexing
        self.conn.execute("PRAGMA journal_mode = MEMORY")
        self.conn.execute("PRAGMA synchronous = OFF")
        self.conn.execute("PRAGMA temp_store = MEMORY")
        # Removed EXCLUSIVE locking to allow concurrent reads by code analysis tools
        # self.conn.execute("PRAGMA locking_mode = EXCLUSIVE")
        # self.conn.execute("BEGIN EXCLUSIVE")
        # Reuse cursor for batch operations
        self.cursor = self.conn.cursor()
        if self.verbose:
            print(f"Database initialized: {self.db_path}")

    def _initialize_parsers(self):
        """Initialize tree-sitter parsers for selected languages."""
        for lang in self.languages:
            if lang in LANGUAGE_CONFIG:
                lang_module = LANGUAGE_CONFIG[lang]["language_module"]
                if lang_module:
                    try:
                        self.parsers[lang] = create_parser(lang_module)
                        if self.verbose:
                            print(f"Loaded parser for: {lang}")
                    except Exception as e:
                        print(f"Warning: Could not load parser for {lang}: {e}")
                else:
                    print(f"Warning: Language module for {lang} not available")

    def _get_dependent_files(self, file_id):
        """Get all files that have dependencies on symbols in the given file."""
        cursor = self.conn.cursor()
        
        # Get function IDs from this file
        cursor.execute("SELECT id FROM functions WHERE file_id = ?", (file_id,))
        function_ids = [row[0] for row in cursor.fetchall()]
        
        # Get class IDs from this file
        cursor.execute("SELECT id FROM classes WHERE file_id = ?", (file_id,))
        class_ids = [row[0] for row in cursor.fetchall()]
        
        dependent_file_ids = set()
        
        # Find files that reference these functions
        if function_ids:
            placeholders = ','.join('?' * len(function_ids))
            cursor.execute(
                f"SELECT DISTINCT file_id FROM dependencies WHERE target_function_id IN ({placeholders})",
                function_ids
            )
            dependent_file_ids.update(row[0] for row in cursor.fetchall())
        
        # Find files that reference these classes
        if class_ids:
            placeholders = ','.join('?' * len(class_ids))
            cursor.execute(
                f"SELECT DISTINCT file_id FROM dependencies WHERE target_class_id IN ({placeholders})",
                class_ids
            )
            dependent_file_ids.update(row[0] for row in cursor.fetchall())
        
        return list(dependent_file_ids)
    
    def _delete_file_symbols(self, file_id):
        """Delete all symbol rows belonging to a file (for re-indexing)."""
        cursor = self.conn.cursor()
        
        # First, collect the IDs of symbols being deleted
        cursor.execute("SELECT id FROM functions WHERE file_id = ?", (file_id,))
        function_ids = [row[0] for row in cursor.fetchall()]
        
        cursor.execute("SELECT id FROM classes WHERE file_id = ?", (file_id,))
        class_ids = [row[0] for row in cursor.fetchall()]
        
        # Update dependencies in OTHER files that reference these symbols to NULL their target IDs
        # This prevents stale references when the file is re-indexed
        if function_ids:
            placeholders = ','.join('?' * len(function_ids))
            cursor.execute(
                f"UPDATE dependencies SET target_function_id = NULL WHERE target_function_id IN ({placeholders})",
                function_ids
            )
        
        if class_ids:
            placeholders = ','.join('?' * len(class_ids))
            cursor.execute(
                f"UPDATE dependencies SET target_class_id = NULL WHERE target_class_id IN ({placeholders})",
                class_ids
            )
        
        # Now delete the file's own symbols
        for table in ("functions", "classes", "variables", "type_aliases", "structs", "interfaces", "dependencies", "temp_symbols", "namespaces"):
            cursor.execute(f"DELETE FROM {table} WHERE file_id = ?", (file_id,))
    
    def _get_deleted_files(self, current_files):
        """Get list of file IDs for files that exist in database but not on filesystem."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, absolute_path FROM files")
        db_files = cursor.fetchall()
        
        deleted_file_ids = []
        current_file_paths = {str(f) for f in current_files}
        
        for file_id, abs_path in db_files:
            if abs_path not in current_file_paths:
                deleted_file_ids.append(file_id)
        
        return deleted_file_ids
    
    def _remove_deleted_files(self, deleted_file_ids):
        """Remove deleted files and all their symbols from the database (bulk, chunked)."""
        cursor = self.conn.cursor()
        SQLITE_MAX_VARS = 999
        
        for i in range(0, len(deleted_file_ids), SQLITE_MAX_VARS):
            chunk = deleted_file_ids[i:i + SQLITE_MAX_VARS]
            placeholders = ','.join('?' * len(chunk))
            
            # Collect function/class IDs being deleted
            cursor.execute(f"SELECT id FROM functions WHERE file_id IN ({placeholders})", chunk)
            function_ids = [row[0] for row in cursor.fetchall()]
            
            cursor.execute(f"SELECT id FROM classes WHERE file_id IN ({placeholders})", chunk)
            class_ids = [row[0] for row in cursor.fetchall()]
            
            # NULL out dependency references to deleted symbols
            if function_ids:
                fp = ','.join('?' * len(function_ids))
                cursor.execute(f"UPDATE dependencies SET target_function_id = NULL WHERE target_function_id IN ({fp})", function_ids)
            
            if class_ids:
                cp = ','.join('?' * len(class_ids))
                cursor.execute(f"UPDATE dependencies SET target_class_id = NULL WHERE target_class_id IN ({cp})", class_ids)
            
            # Delete all symbols for this chunk
            for table in ("functions", "classes", "variables", "type_aliases", "structs", "interfaces", "dependencies", "temp_symbols", "namespaces"):
                cursor.execute(f"DELETE FROM {table} WHERE file_id IN ({placeholders})", chunk)
            
            # Delete file records
            cursor.execute(f"DELETE FROM files WHERE id IN ({placeholders})", chunk)
        
        self.conn.commit()

    def _insert_file(self, file_path, language, content_hash, mtime):
        """Insert or update file record and return its ID. Returns None if file should be skipped."""
        relative_path = get_relative_path(file_path, self.root_dir)
        self.cursor.execute("SELECT id, content_hash, mtime FROM files WHERE path = ?", (relative_path,))
        existing = self.cursor.fetchone()
        if existing:
            file_id, existing_hash, existing_mtime = existing
            # Fast path: mtime unchanged => file hasn't been modified
            if not self.force_reindex and existing_mtime == mtime:
                return None  # Skip reindexing
            # Slow path: mtime changed, check content hash
            if not self.force_reindex and content_hash is not None and existing_hash == content_hash:
                # mtime changed but content is the same (e.g. touch), update mtime only
                self.cursor.execute("UPDATE files SET mtime = ? WHERE id = ?", (mtime, file_id))
                return None
            # Content changed or force_reindex, reindex
            self._delete_file_symbols(file_id)
            self.cursor.execute(
                "UPDATE files SET absolute_path = ?, language = ?, content_hash = ?, mtime = ? WHERE id = ?",
                (str(file_path), language, content_hash, mtime, file_id)
            )
            return file_id
        self.cursor.execute(
            "INSERT INTO files (path, absolute_path, language, content_hash, mtime) VALUES (?, ?, ?, ?, ?)",
            (relative_path, str(file_path), language, content_hash, mtime)
        )
        return self.cursor.lastrowid
    
    def _update_file_hash(self, file_id, content_hash, mtime):
        """Update content hash and mtime after file has been read and parsed."""
        self.cursor.execute(
            "UPDATE files SET content_hash = ?, mtime = ? WHERE id = ?",
            (content_hash, mtime, file_id)
        )
    
    def _insert_parsed_file(self, data):
        """Insert a file parsed by a worker process into the database."""
        file_path = Path(data['file_path'])
        language = data['language']
        content_hash = data['content_hash']
        file_mtime = data['file_mtime']
        
        # Insert/update file record
        file_id = self._insert_file(file_path, language, content_hash, file_mtime)
        if file_id is None:
            self.stats["skipped_files"] += 1
            return
        
        self.current_file_id = file_id
        
        # Insert imports
        for imp in data.get('imports', []):
            self._insert_import(imp['name'], imp['location'], imp.get('is_external', True))
        
        # Insert classes first (so methods can reference them)
        class_id_map = {}  # temp_id -> real_id
        for cls in data.get('classes', []):
            temp_id = cls.pop('_temp_id', None)
            self.cursor.execute(
                """INSERT INTO classes (file_id, parent_id, name, location, base_classes, docstring, namespace)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_id,
                    None,
                    cls['name'],
                    json.dumps(cls['location']),
                    json.dumps(cls.get('base_classes', [])),
                    cls.get('docstring'),
                    cls.get('namespace'),
                )
            )
            real_id = self.cursor.lastrowid
            if temp_id is not None:
                class_id_map[temp_id] = real_id
            self.stats["total_classes"] += 1
            self._resolve_temp_for_symbol(cls['name'], ['class_reference'], target_class_id=real_id)
        
        # Insert functions/methods
        func_id_map = {}
        for i, func in enumerate(data.get('functions', [])):
            parent_class_id = func.pop('parent_class_id', None)
            if parent_class_id is not None:
                parent_class_id = class_id_map.get(parent_class_id)
            
            self.cursor.execute(
                """INSERT INTO functions 
                   (file_id, parent_id, parent_type, name, type, location, parameters, return_type, docstring, receiver, branch_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_id,
                    parent_class_id,
                    'class' if parent_class_id else None,
                    func['name'],
                    func['type'],
                    json.dumps(func['location']),
                    json.dumps(func.get('parameters', [])),
                    func.get('return_type'),
                    func.get('docstring'),
                    func.get('receiver'),
                    func.get('branch_count', 0),
                )
            )
            func_real_id = self.cursor.lastrowid
            func_id_map[i] = func_real_id
            if parent_class_id is not None:
                self.stats["total_methods"] += 1
                self._resolve_temp_for_symbol(func['name'], ['function_call', 'method_call'], target_function_id=func_real_id)
            elif func.get('type') == 'macro':
                self.stats["total_macros"] += 1
                self._resolve_temp_for_symbol(func['name'], ['function_call'], target_function_id=func_real_id)
            else:
                self.stats["total_functions"] += 1
                self._resolve_temp_for_symbol(func['name'], ['function_call'], target_function_id=func_real_id)
        
        # Insert variables
        for var in data.get('variables', []):
            parent_class_id = var.pop('parent_class_id', None)
            if parent_class_id is not None:
                parent_class_id = class_id_map.get(parent_class_id)
            
            self.cursor.execute(
                """INSERT INTO variables (file_id, parent_id, parent_type, name, type, location, field_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_id,
                    parent_class_id,
                    'class' if parent_class_id else None,
                    var['name'],
                    var['type'],
                    json.dumps(var['location']),
                    var.get('field_type'),
                )
            )
            self.stats["total_variables"] += 1
            self._resolve_temp_for_symbol(var['name'], ['variable_reference'])
        
        # Insert type aliases
        for alias in data.get('type_aliases', []):
            self.cursor.execute(
                """INSERT INTO type_aliases (file_id, name, location, type_definition)
                   VALUES (?, ?, ?, ?)""",
                (
                    file_id,
                    alias['name'],
                    json.dumps(alias['location']),
                    alias.get('type_definition'),
                )
            )
            self.stats["total_type_defs"] += 1
            self._resolve_temp_for_symbol(alias['name'], ['class_reference'])
        
        # Insert structs
        for struct in data.get('structs', []):
            self.cursor.execute(
                "INSERT INTO structs (file_id, name, location) VALUES (?, ?, ?)",
                (file_id, struct['name'], json.dumps(struct['location']))
            )
            self.stats["total_structs"] += 1
            self._resolve_temp_for_symbol(struct['name'], ['class_reference'])
        
        # Insert interfaces
        for iface in data.get('interfaces', []):
            self.cursor.execute(
                "INSERT INTO interfaces (file_id, name, location) VALUES (?, ?, ?)",
                (file_id, iface['name'], json.dumps(iface['location']))
            )
            self.stats["total_interfaces"] += 1
            self._resolve_temp_for_symbol(iface['name'], ['class_reference'])
        
        # Insert enums
        for enum in data.get('enums', []):
            self.cursor.execute(
                "INSERT INTO enums (file_id, name, location) VALUES (?, ?, ?)",
                (file_id, enum['name'], json.dumps(enum['location']))
            )
            self.stats["total_enums"] += 1
            self._resolve_temp_for_symbol(enum['name'], ['class_reference'])
        
        # Insert namespaces
        for ns in data.get('namespaces', []):
            self.cursor.execute(
                "INSERT INTO namespaces (file_id, name, location) VALUES (?, ?, ?)",
                (file_id, ns['name'], json.dumps(ns['location']))
            )
            self.stats["total_namespaces"] += 1
        
        # Insert dependencies with resolution
        for dep in data.get('dependencies', []):
            dep_type = dep['type']
            dep_name = dep['name']
            source_func_id = func_id_map.get(dep.pop('_func_index', None))
            target_func_id, target_class_id, is_external = self._resolve_dependency(dep_name, dep_type, file_id)

            if target_func_id is None and target_class_id is None and is_external:
                temp_sym_id = self._create_temp_symbol(dep_name, dep_type)
            else:
                temp_sym_id = None

            self.cursor.execute(
                """INSERT INTO dependencies (file_id, dependency_type, name, source_function_id, target_function_id, target_class_id, temp_symbol_id, location, is_external)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_id,
                    dep_type,
                    dep_name,
                    source_func_id,
                    target_func_id,
                    target_class_id,
                    temp_sym_id,
                    json.dumps(dep.get('location')) if dep.get('location') else None,
                    is_external,
                )
            )
    
    def _insert_import(self, name, location, is_external):
        """Queue an import dependency for batch insertion."""
        self.batches["dependencies"].append(
            (
                self.current_file_id,
                'import',
                name,
                None,
                None,
                None,
                None,
                json.dumps(location) if location else None,
                1 if is_external else 0
            )
        )
        self._check_and_flush("dependencies")

    def _resolve_dependency(self, name, dep_type, source_file_id=None):
        """Try to resolve a dependency to an existing symbol.
        Returns (target_function_id, target_class_id, is_external) or (None, None, 1).
        
        Args:
            name: The dependency name
            dep_type: The dependency type (function_call, method_call, etc.)
            source_file_id: Optional file ID of the source making the reference, for disambiguation
        """
        # For method calls like self.init or obj.method, extract just the method name
        resolve_name = name
        if dep_type == 'method_call' and '.' in name:
            resolve_name = name.rsplit('.', 1)[-1]

        if dep_type in ('function_call', 'method_call'):
            # Prefer functions in the same file if available
            if source_file_id:
                self.cursor.execute(
                    "SELECT id, parent_type FROM functions WHERE name = ? AND file_id = ? LIMIT 1",
                    (resolve_name, source_file_id)
                )
                row = self.cursor.fetchone()
                if row:
                    if dep_type == 'method_call' and row[1] != 'class':
                        pass  # It's a standalone function, not a method
                    else:
                        return (row[0], None, 0)
            # Fall back to any function with that name
            self.cursor.execute(
                "SELECT id, parent_type FROM functions WHERE name = ? LIMIT 1",
                (resolve_name,)
            )
            row = self.cursor.fetchone()
            if row:
                if dep_type == 'method_call' and row[1] != 'class':
                    pass  # It's a standalone function, not a method
                else:
                    return (row[0], None, 0)

        if dep_type in ('function_call', 'method_call', 'class_reference'):
            # Prefer classes in the same file if available
            if source_file_id:
                self.cursor.execute(
                    "SELECT id FROM classes WHERE name = ? AND file_id = ? LIMIT 1",
                    (resolve_name, source_file_id)
                )
                row = self.cursor.fetchone()
                if row:
                    return (None, row[0], 0)
            # Fall back to any class with that name
            self.cursor.execute(
                "SELECT id FROM classes WHERE name = ? LIMIT 1",
                (resolve_name,)
            )
            row = self.cursor.fetchone()
            if row:
                return (None, row[0], 0)

            for table in ('structs', 'interfaces', 'enums', 'type_aliases'):
                self.cursor.execute(
                    f"SELECT id FROM {table} WHERE name = ? LIMIT 1",
                    (resolve_name,)
                )
                row = self.cursor.fetchone()
                if row:
                    return (None, None, 0)

        if dep_type == 'variable_reference':
            # Prefer variables in the same file if available
            if source_file_id:
                self.cursor.execute(
                    "SELECT id FROM variables WHERE name = ? AND file_id = ? LIMIT 1",
                    (name, source_file_id)
                )
                row = self.cursor.fetchone()
                if row:
                    return (None, None, 0)
            # Fall back to any variable with that name
            self.cursor.execute(
                "SELECT id FROM variables WHERE name = ? LIMIT 1",
                (name,)
            )
            row = self.cursor.fetchone()
            if row:
                return (None, None, 0)

        return (None, None, 1)

    def _create_temp_symbol(self, name, dep_type):
        """Create a temp_symbol for an unresolved dependency. Returns the temp_symbol_id."""
        self.cursor.execute(
            "INSERT OR IGNORE INTO temp_symbols (name, symbol_type, file_id) VALUES (?, ?, ?)",
            (name, dep_type, self.current_file_id)
        )
        if self.cursor.lastrowid:
            return self.cursor.lastrowid
        self.cursor.execute(
            "SELECT id FROM temp_symbols WHERE name = ? AND symbol_type = ?",
            (name, dep_type)
        )
        return self.cursor.fetchone()[0]

    def _resolve_temp_for_symbol(self, name, match_types, target_function_id=None, target_class_id=None):
        """When a real symbol is defined, resolve any temp_symbols waiting for it.

        Args:
            name: Symbol name to match
            match_types: List of dependency_type values to match
            target_function_id: If set, update dependencies with this function ID
            target_class_id: If set, update dependencies with this class ID
        """
        if not match_types:
            return

        placeholders = ','.join('?' * len(match_types))
        self.cursor.execute(
            f"SELECT id, symbol_type FROM temp_symbols WHERE name = ? AND symbol_type IN ({placeholders})",
            [name] + list(match_types)
        )
        temp_rows = self.cursor.fetchall()

        for temp_row in temp_rows:
            temp_id = temp_row[0]
            sym_type = temp_row[1]

            if target_function_id is not None and sym_type in ('function_call', 'method_call'):
                self.cursor.execute(
                    "UPDATE dependencies SET target_function_id = ?, is_external = 0, temp_symbol_id = NULL WHERE temp_symbol_id = ?",
                    (target_function_id, temp_id)
                )
            elif target_class_id is not None and sym_type == 'class_reference':
                self.cursor.execute(
                    "UPDATE dependencies SET target_class_id = ?, is_external = 0, temp_symbol_id = NULL WHERE temp_symbol_id = ?",
                    (target_class_id, temp_id)
                )
            else:
                self.cursor.execute(
                    "UPDATE dependencies SET is_external = 0, temp_symbol_id = NULL WHERE temp_symbol_id = ?",
                    (temp_id,)
                )

            self.cursor.execute("DELETE FROM temp_symbols WHERE id = ?", (temp_id,))

    def _compute_content_hash(self, content):
        """Compute xxhash of file content (faster than SHA-256)."""
        return xxhash.xxh64(content).hexdigest()
    
    def index_directory(self):
        B = "\033[34m"
        R = "\033[0m"
        print(f"{B}analyzing...{R}", flush=True)
        """Index all supported files in the directory recursiv[ely."""
        if self.verbose:
            print(f"Starting indexing of {self.root_dir}...")
            print(f"Languages: {', '.join(self.languages)}")

        files = collect_files_to_index(self.root_dir, self.languages)
        
        # First pass: identify changed files using mtime (fast, no file reads)
        changed_files = []
        files_to_reindex = set()
        skipped_count = 0
        
        for file_path in files:
            language = detect_language(file_path)
            if not language or language not in self.parsers:
                continue
            
            relative_path = get_relative_path(file_path, self.root_dir)
            file_mtime = os.stat(file_path).st_mtime
            
            self.cursor.execute("SELECT id, content_hash, mtime FROM files WHERE path = ?", (relative_path,))
            existing = self.cursor.fetchone()
            
            if existing:
                file_id, existing_hash, existing_mtime = existing
                if self.force_reindex or existing_mtime != file_mtime:
                    # mtime changed - verify with content hash
                    source_bytes = read_file_content(file_path)
                    content_hash = self._compute_content_hash(source_bytes)
                    if self.force_reindex or existing_hash != content_hash:
                        changed_files.append((file_path, file_id))
                        files_to_reindex.add(file_path)
                    else:
                        skipped_count += 1
                else:
                    skipped_count += 1
            else:
                # New file
                files_to_reindex.add(file_path)
        
        self.stats["skipped_files"] = skipped_count
        
        # Cascade: find all files that depend on changed files
        for file_path, file_id in changed_files:
            dependent_file_ids = self._get_dependent_files(file_id)
            for dep_file_id in dependent_file_ids:
                self.cursor.execute("SELECT absolute_path FROM files WHERE id = ?", (dep_file_id,))
                result = self.cursor.fetchone()
                if result:
                    dep_file_path = Path(result[0])
                    if dep_file_path.exists():  # Only reindex if file still exists
                        files_to_reindex.add(dep_file_path)
                        #print(f"Cascade re-index: {dep_file_path} depends on changed file {file_path}")
        
        # Remove deleted files from the database
        deleted_file_ids = self._get_deleted_files(files)
        if deleted_file_ids:
            if self.verbose:
                print(f"Found {len(deleted_file_ids)} deleted file(s) to remove from index")
            self._remove_deleted_files(deleted_file_ids)
        
        # Second pass: parse files in parallel, then batch insert
        # Process in batches to bound memory (submitting all 36K+ files at once
        # causes completed future results to pile up in the internal queue)
        if files_to_reindex:
            worker_args = [(str(fp), str(self.root_dir)) for fp in files_to_reindex]
            max_workers = min(os.cpu_count() or 4, len(worker_args))
            batch_size = max_workers * 256  # Keep ~256 files per worker in-flight
            
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                for i in range(0, len(worker_args), batch_size):
                    batch = worker_args[i:i + batch_size]
                    futures = {executor.submit(parse_file, arg): arg for arg in batch}
                    for future in as_completed(futures):
                        result = future.result()
                        if result and 'error' not in result:
                            self._insert_parsed_file(result)
                        elif result and 'error' in result:
                            if self.verbose:
                                print(f"Error parsing {result['file_path']}: {result['error']}")
        
        # Flush any remaining batches
        self._flush_batches()

        # Clean up unresolved temp_symbols and their dependencies
        # (these are external/builtin symbols that were never defined in the codebase)
        self.cursor.execute("SELECT COUNT(*) FROM temp_symbols")
        remaining = self.cursor.fetchone()[0]
        if remaining > 0:
            self.cursor.execute("DELETE FROM dependencies WHERE temp_symbol_id IS NOT NULL")
            self.cursor.execute("DELETE FROM temp_symbols")
            self.conn.commit()
        
        if self.verbose:
            self._print_summary()

    def _print_summary(self):
        """Print indexing summary statistics."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM files")
        file_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM functions WHERE parent_id IS NULL AND type != 'macro'")
        func_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM functions WHERE type = 'macro'")
        macro_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM functions WHERE parent_id IS NOT NULL")
        method_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM classes")
        class_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM structs")
        struct_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM interfaces")
        iface_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM enums")
        enum_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM namespaces")
        ns_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM variables")
        var_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM type_aliases")
        alias_count = cursor.fetchone()[0]

        indexed = file_count - self.stats['skipped_files']

        print(f"\nIndexing complete!")
        print(f"Total files in database: {file_count}")
        print(f"Files indexed this run: {indexed}")
        print(f"Files skipped (unchanged): {self.stats['skipped_files']}")
        if indexed > 0:
            print(f"  Functions indexed: {self.stats['total_functions']}")
            print(f"  Macros indexed:    {self.stats['total_macros']}")
            print(f"  Methods indexed:   {self.stats['total_methods']}")
            print(f"  Classes indexed:   {self.stats['total_classes']}")
            print(f"  Structs indexed:   {self.stats['total_structs']}")
            print(f"  Interfaces indexed:{self.stats['total_interfaces']}")
            print(f"  Enums indexed:     {self.stats['total_enums']}")
            print(f"  Namespaces indexed:{self.stats['total_namespaces']}")
            print(f"  Variables indexed: {self.stats['total_variables']}")
            print(f"  Type aliases idx:  {self.stats['total_type_defs']}")
        print(f"Total functions: {func_count}")
        print(f"Total macros: {macro_count}")
        print(f"Total methods: {method_count}")
        print(f"Total classes: {class_count}")
        print(f"Total structs: {struct_count}")
        print(f"Total interfaces: {iface_count}")
        print(f"Total enums: {enum_count}")
        print(f"Total namespaces: {ns_count}")
        print(f"Total variables: {var_count}")
        print(f"Total type aliases: {alias_count}")

    def save_index(self, output_file=None):
        """Commit and optionally close the database connection. Data is already saved during indexing."""
        if self.conn:
            self.conn.commit()
            if self.verbose:
                print(f"\nDatabase saved to {self.db_path}")

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()


def main():
    import sys
    import traceback

    args = parse_arguments()
    
    if args.list_languages:
        list_supported_languages()
        return
    
    try:
        # Handle view graph mode
        if args.graph:
            # Determine database file
            db_file = args.output
            if db_file.endswith('.json'):
                db_file = db_file.rsplit('.', 1)[0] + '.db'
            
            if not Path(db_file).exists():
                print(f"Error: Database file not found: {db_file}")
                print("Please run indexing first to create the database.")
                sys.exit(1)
            
            sdk = CodeIndexSDK(db_file)
            graph = sdk.get_dependency_graph(args.graph)
            print(graph)
            sdk.close()
            return
        
        # Handle JSON export mode
        if args.export_json:
            # Determine database file
            db_file = args.output
            if db_file.endswith('.json'):
                db_file = db_file.rsplit('.', 1)[0] + '.db'
            
            if not Path(db_file).exists():
                print(f"Error: Database file not found: {db_file}")
                print("Please run indexing first to create the database.")
                sys.exit(1)
            
            export_to_json(db_file, args.export_json)
            return
        
        # Handle indexing mode - directory is required
        directory = args.directory
        if not directory:
            print("Error: directory argument is required for indexing mode")
            print("Usage: python code_indexer.py <directory> [options]")
            sys.exit(1)
        
        # Determine output file extension
        output_file = args.output
        if output_file.endswith('.json'):
            # Convert to .db for SQLite
            output_file = output_file.rsplit('.', 1)[0] + '.db'
            print(f"Note: Output file changed to {output_file} (SQLite database)")
        
        # Parse languages if provided
        languages = None
        if args.languages:
            languages = [lang.strip() for lang in args.languages.split(',')]
        
        indexer = CodeIndexer(directory, languages, output_file, args.force, verbose=True)
        indexer.index_directory()
        indexer.save_index()
        indexer.close()
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
