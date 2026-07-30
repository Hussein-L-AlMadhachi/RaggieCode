#!/usr/bin/env python3
"""
Code Indexer using tree-sitter
Indexes files in a codebase and tracks functions, classes, variables, methods, and type definitions.
Supports multiple languages: Python, Go, C#, JavaScript, TypeScript, Rust, Zig, Elixir, C++, PHP
"""

import json
import os
import time
import threading
import queue as queue_mod
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import xxhash

from indexing.language_config import (
    LANGUAGE_CONFIG,
)
from indexing.file_utils import (
    detect_language,
    collect_files_to_index,
    read_file_content,
    get_relative_path
)
from indexing.cli import parse_arguments, list_supported_languages, list_frontend_languages
from indexing.db_schema import init_database
from indexing.export_to_json import export_to_json
from indexing.code_index_sdk import CodeIndexSDK
from indexing.parse_worker import parse_file
from indexing.frontend.resolver import normalize_import_path, load_path_aliases, FrontendResolver


VAR_DATA = "this is to test the indexer"

class CodeIndexer:
    def __init__(self, root_dir, languages=None, db_path=".code_index.raggie", force_reindex=False, verbose=False, frontend_enabled=True):
        self.root_dir = Path(root_dir)
        self.languages = languages if languages else list(LANGUAGE_CONFIG.keys())
        self.frontend_enabled = frontend_enabled
        if not frontend_enabled:
            frontend_langs = {"html", "css", "tsx"}
            self.languages = [l for l in self.languages if l not in frontend_langs]
        self.parsers = {}
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self.current_file_id = None
        self.current_class_id = None
        self.force_reindex = force_reindex
        self.batch_size = 50000
        self.verbose = verbose
        self.path_aliases = {}  # loaded lazily on first frontend insert
        
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
        # init_database creates schema and returns a connection
        init_database(self.db_path)
        # Reopen with check_same_thread=False so the writer thread can use it
        import sqlite3
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # Optimized settings for batch indexing
        self.conn.execute("PRAGMA journal_mode = MEMORY")
        self.conn.execute("PRAGMA synchronous = OFF")
        self.conn.execute("PRAGMA temp_store = MEMORY")
        self.cursor = self.conn.cursor()
        if self.verbose:
            print(f"Database initialized: {self.db_path}")

    def _initialize_parsers(self):
        """Initialize tree-sitter parsers for selected languages.

        Parsers are only needed in the parent for the detect_language check
        in index_directory. Actual parsing happens in worker processes
        which have their own parser cache. Skip parser creation to save memory.
        """
        # Only track which languages are configured (for the parser check in index_directory)
        self._configured_languages = set()
        for lang in self.languages:
            if lang in LANGUAGE_CONFIG:
                self._configured_languages.add(lang)
                if self.verbose:
                    print(f"Configured parser for: {lang}")

    def _get_dependent_files(self, file_id):
        """Get all files that have dependencies on symbols in the given file.

        Checks both traditional dependency edges (function/class references) and
        frontend dependency edges (render relationships, style imports, custom
        property usages, event handler symbols, selector matches).
        """
        cursor = self.conn.cursor()

        # Get function IDs from this file
        cursor.execute("SELECT id FROM functions WHERE file_id = ?", (file_id,))
        function_ids = [row[0] for row in cursor.fetchall()]

        # Get class IDs from this file
        cursor.execute("SELECT id FROM classes WHERE file_id = ?", (file_id,))
        class_ids = [row[0] for row in cursor.fetchall()]

        # Get frontend component IDs from this file
        cursor.execute("SELECT id FROM frontend_components WHERE file_id = ?", (file_id,))
        component_ids = [row[0] for row in cursor.fetchall()]

        # Get custom property IDs from this file
        cursor.execute("SELECT id FROM style_custom_properties WHERE file_id = ?", (file_id,))
        custom_property_ids = [row[0] for row in cursor.fetchall()]

        # Get selector IDs from this file
        cursor.execute("SELECT id FROM style_selectors WHERE file_id = ?", (file_id,))
        selector_ids = [row[0] for row in cursor.fetchall()]

        # Get markup element IDs from this file
        cursor.execute("SELECT id FROM markup_elements WHERE file_id = ?", (file_id,))
        element_ids = [row[0] for row in cursor.fetchall()]

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

        # Frontend: render_relationships — files containing parent components
        # that render this file's components as children
        if component_ids:
            placeholders = ','.join('?' * len(component_ids))
            # Find parent component IDs that reference these child components
            cursor.execute(
                f"SELECT DISTINCT fc.file_id FROM render_relationships rr "
                f"JOIN frontend_components fc ON rr.parent_component_id = fc.id "
                f"WHERE rr.child_component_id IN ({placeholders})",
                component_ids
            )
            dependent_file_ids.update(row[0] for row in cursor.fetchall())

        # Frontend: style_imports — files that import this file via @import or <link>
        cursor.execute(
            "SELECT DISTINCT si.file_id FROM style_imports si WHERE si.resolved_file_id = ?",
            (file_id,)
        )
        dependent_file_ids.update(row[0] for row in cursor.fetchall())

        # Frontend: style_custom_property_usages — files that use this file's custom properties
        if custom_property_ids:
            placeholders = ','.join('?' * len(custom_property_ids))
            cursor.execute(
                f"SELECT DISTINCT file_id FROM style_custom_property_usages WHERE resolved_property_id IN ({placeholders})",
                custom_property_ids
            )
            dependent_file_ids.update(row[0] for row in cursor.fetchall())

        # Frontend: frontend_events — files whose events reference this file's handler functions
        if function_ids:
            placeholders = ','.join('?' * len(function_ids))
            cursor.execute(
                f"SELECT DISTINCT file_id FROM frontend_events WHERE handler_symbol_id IN ({placeholders})",
                function_ids
            )
            dependent_file_ids.update(row[0] for row in cursor.fetchall())

        # Frontend: style_selector_matches — bidirectional
        # When a CSS file changes (selectors), files containing matched elements need re-resolution
        if selector_ids:
            placeholders = ','.join('?' * len(selector_ids))
            cursor.execute(
                f"SELECT DISTINCT me.file_id FROM style_selector_matches ssm "
                f"JOIN markup_elements me ON ssm.element_id = me.id "
                f"WHERE ssm.selector_id IN ({placeholders})",
                selector_ids
            )
            dependent_file_ids.update(row[0] for row in cursor.fetchall())

        # When a TSX/HTML file changes (elements), CSS files with matched selectors need re-resolution
        if element_ids:
            placeholders = ','.join('?' * len(element_ids))
            cursor.execute(
                f"SELECT DISTINCT ss.file_id FROM style_selector_matches ssm "
                f"JOIN style_selectors ss ON ssm.selector_id = ss.id "
                f"WHERE ssm.element_id IN ({placeholders})",
                element_ids
            )
            dependent_file_ids.update(row[0] for row in cursor.fetchall())

        # Don't include the file itself
        dependent_file_ids.discard(file_id)

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
        
        # Collect frontend component IDs for cross-file FK cleanup
        cursor.execute("SELECT id FROM frontend_components WHERE file_id = ?", (file_id,))
        component_ids = [row[0] for row in cursor.fetchall()]
        
        # Collect custom property IDs for cross-file FK cleanup
        cursor.execute("SELECT id FROM style_custom_properties WHERE file_id = ?", (file_id,))
        custom_property_ids = [row[0] for row in cursor.fetchall()]
        
        # NULL out cross-file references to symbols being deleted (FK constraints not enforced)
        if component_ids:
            placeholders = ','.join('?' * len(component_ids))
            # render_relationships in OTHER files referencing these components as child
            cursor.execute(
                f"UPDATE render_relationships SET child_component_id = NULL WHERE child_component_id IN ({placeholders})",
                component_ids
            )
            # markup_elements in OTHER files referencing these components
            cursor.execute(
                f"UPDATE markup_elements SET component_id = NULL WHERE component_id IN ({placeholders})",
                component_ids
            )
            # style_selectors in OTHER files referencing these components
            cursor.execute(
                f"UPDATE style_selectors SET component_id = NULL WHERE component_id IN ({placeholders})",
                component_ids
            )
        
        if custom_property_ids:
            placeholders = ','.join('?' * len(custom_property_ids))
            # style_custom_property_usages in OTHER files referencing these properties
            cursor.execute(
                f"UPDATE style_custom_property_usages SET resolved_property_id = NULL WHERE resolved_property_id IN ({placeholders})",
                custom_property_ids
            )
        
        # Now delete the file's own symbols
        # Delete render_relationships FIRST (before frontend_components are deleted),
        # since FK constraints are not enforced and the subquery would find no rows after.
        cursor.execute(
            "DELETE FROM render_relationships WHERE parent_component_id IN "
            "(SELECT id FROM frontend_components WHERE file_id = ?)",
            (file_id,)
        )
        cursor.execute(
            "DELETE FROM style_selector_matches WHERE selector_id IN "
            "(SELECT id FROM style_selectors WHERE file_id = ?) "
            "OR element_id IN (SELECT id FROM markup_elements WHERE file_id = ?)",
            (file_id, file_id)
        )
        # Tables with direct file_id column
        for table in ("functions", "classes", "variables", "type_aliases", "structs", "interfaces", "dependencies", "temp_symbols", "namespaces",
                       "frontend_components", "markup_elements", "style_selectors", "style_custom_properties",
                       "style_custom_property_usages", "style_keyframes", "style_imports", "frontend_events",
                       "frontend_bindings", "frontend_diagnostics"):
            cursor.execute(f"DELETE FROM {table} WHERE file_id = ?", (file_id,))
        # Clean up temp_file_references where this file is the source
        cursor.execute("DELETE FROM temp_file_references WHERE source_file_id = ?", (file_id,))
    
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
            
            # Collect frontend component and custom property IDs for cross-file FK cleanup
            cursor.execute(f"SELECT id FROM frontend_components WHERE file_id IN ({placeholders})", chunk)
            component_ids = [row[0] for row in cursor.fetchall()]
            
            cursor.execute(f"SELECT id FROM style_custom_properties WHERE file_id IN ({placeholders})", chunk)
            custom_property_ids = [row[0] for row in cursor.fetchall()]
            
            # NULL out cross-file references to symbols being deleted (FK constraints not enforced)
            if component_ids:
                fp = ','.join('?' * len(component_ids))
                cursor.execute(f"UPDATE render_relationships SET child_component_id = NULL WHERE child_component_id IN ({fp})", component_ids)
                cursor.execute(f"UPDATE markup_elements SET component_id = NULL WHERE component_id IN ({fp})", component_ids)
                cursor.execute(f"UPDATE style_selectors SET component_id = NULL WHERE component_id IN ({fp})", component_ids)
            
            if custom_property_ids:
                cp2 = ','.join('?' * len(custom_property_ids))
                cursor.execute(f"UPDATE style_custom_property_usages SET resolved_property_id = NULL WHERE resolved_property_id IN ({cp2})", custom_property_ids)
            
            # NULL out style_imports.resolved_file_id in OTHER files pointing to deleted files
            cursor.execute(f"UPDATE style_imports SET resolved_file_id = NULL WHERE resolved_file_id IN ({placeholders})", chunk)
            
            # Delete render_relationships and style_selector_matches FIRST (before their parent
            # tables are emptied), since FK constraints are not enforced and subqueries would
            # find no rows after the parent table delete.
            cursor.execute(
                f"DELETE FROM render_relationships WHERE parent_component_id IN "
                f"(SELECT id FROM frontend_components WHERE file_id IN ({placeholders}))",
                chunk
            )
            cursor.execute(
                f"DELETE FROM style_selector_matches WHERE selector_id IN "
                f"(SELECT id FROM style_selectors WHERE file_id IN ({placeholders})) "
                f"OR element_id IN (SELECT id FROM markup_elements WHERE file_id IN ({placeholders}))",
                chunk + chunk
            )
            # Tables with direct file_id column
            for table in ("functions", "classes", "variables", "type_aliases", "structs", "interfaces", "dependencies", "temp_symbols", "namespaces",
                           "frontend_components", "markup_elements", "style_selectors", "style_custom_properties",
                           "style_custom_property_usages", "style_keyframes", "style_imports", "frontend_events",
                           "frontend_bindings", "frontend_diagnostics"):
                cursor.execute(f"DELETE FROM {table} WHERE file_id IN ({placeholders})", chunk)
            
            # Clean up temp_file_references for deleted source files
            cursor.execute(f"DELETE FROM temp_file_references WHERE source_file_id IN ({placeholders})", chunk)
            
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
        """Insert a file parsed by a worker process into the database.

        Wraps the insertion in a SAVEPOINT so that a failed update does not
        leave partially updated semantic state.
        """
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
        
        try:
            self._insert_parsed_file_inner(data, file_id)
        except Exception as e:
            if self.verbose:
                print(f"Warning: Failed to insert {file_path}: {e}")
            return

    def _insert_parsed_file_inner(self, data, file_id):
        """Inner insertion logic — called within a SAVEPOINT."""
        
        # Insert imports
        for imp in data.get('imports', []):
            self._insert_import(imp['name'], imp['location'], imp.get('is_external', True))
        
        # Insert classes first (so methods can reference them) — batch
        class_id_map = {}  # temp_id -> real_id
        class_names = []
        class_temp_ids = []
        class_rows = []
        for cls in data.get('classes', []):
            temp_id = cls.pop('_temp_id', None)
            class_temp_ids.append(temp_id)
            class_rows.append((
                file_id, None, cls['name'],
                json.dumps(cls['location']),
                json.dumps(cls.get('base_classes', [])),
                cls.get('docstring'),
                cls.get('namespace'),
            ))
            self.stats["total_classes"] += 1
            class_names.append(cls['name'])
        if class_rows:
            self.cursor.executemany(
                """INSERT INTO classes (file_id, parent_id, name, location, base_classes, docstring, namespace)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                class_rows
            )
            # SELECT back IDs in insertion order to rebuild class_id_map
            self.cursor.execute(
                "SELECT id FROM classes WHERE file_id = ? ORDER BY id DESC LIMIT ?",
                (file_id, len(class_rows))
            )
            real_ids = [r[0] for r in self.cursor.fetchall()]
            real_ids.reverse()  # back to insertion order
            for temp_id, real_id in zip(class_temp_ids, real_ids):
                if temp_id is not None:
                    class_id_map[temp_id] = real_id
        
        # Insert functions/methods — batch
        func_id_map = {}
        func_names = []
        func_rows = []
        for i, func in enumerate(data.get('functions', [])):
            parent_class_id = func.pop('parent_class_id', None)
            if parent_class_id is not None:
                parent_class_id = class_id_map.get(parent_class_id)
            func_rows.append((
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
            ))
            if parent_class_id is not None:
                self.stats["total_methods"] += 1
            elif func.get('type') == 'macro':
                self.stats["total_macros"] += 1
            else:
                self.stats["total_functions"] += 1
            func_names.append(func['name'])
        if func_rows:
            self.cursor.executemany(
                """INSERT INTO functions 
                   (file_id, parent_id, parent_type, name, type, location, parameters, return_type, docstring, receiver, branch_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                func_rows
            )
            # SELECT back IDs in insertion order to rebuild func_id_map
            self.cursor.execute(
                "SELECT id FROM functions WHERE file_id = ? ORDER BY id DESC LIMIT ?",
                (file_id, len(func_rows))
            )
            real_ids = [r[0] for r in self.cursor.fetchall()]
            real_ids.reverse()
            for i, real_id in enumerate(real_ids):
                func_id_map[i] = real_id
        
        # Insert variables (batch)
        var_names = []
        var_rows = []
        for var in data.get('variables', []):
            parent_class_id = var.pop('parent_class_id', None)
            if parent_class_id is not None:
                parent_class_id = class_id_map.get(parent_class_id)
            var_rows.append((
                file_id,
                parent_class_id,
                'class' if parent_class_id else None,
                var['name'],
                var['type'],
                json.dumps(var['location']),
                var.get('field_type'),
            ))
            self.stats["total_variables"] += 1
            var_names.append(var['name'])
        if var_rows:
            self.cursor.executemany(
                """INSERT INTO variables (file_id, parent_id, parent_type, name, type, location, field_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                var_rows
            )

        # Dependencies are inserted as external with temp_symbols.
        # Resolution happens in _resolve_all_dependencies after all files are indexed.
        
        # Batch insert type aliases
        type_alias_rows = []
        type_alias_names = []
        for alias in data.get('type_aliases', []):
            type_alias_rows.append((
                file_id, alias['name'],
                json.dumps(alias['location']),
                alias.get('type_definition'),
            ))
            type_alias_names.append(alias['name'])
        if type_alias_rows:
            self.cursor.executemany(
                "INSERT INTO type_aliases (file_id, name, location, type_definition) VALUES (?, ?, ?, ?)",
                type_alias_rows
            )
            self.stats["total_type_defs"] += len(type_alias_rows)

        # Batch insert structs
        struct_rows = []
        struct_names = []
        for struct in data.get('structs', []):
            struct_rows.append((file_id, struct['name'], json.dumps(struct['location'])))
            struct_names.append(struct['name'])
        if struct_rows:
            self.cursor.executemany(
                "INSERT INTO structs (file_id, name, location) VALUES (?, ?, ?)",
                struct_rows
            )
            self.stats["total_structs"] += len(struct_rows)

        # Batch insert interfaces
        iface_rows = []
        iface_names = []
        for iface in data.get('interfaces', []):
            iface_rows.append((file_id, iface['name'], json.dumps(iface['location'])))
            iface_names.append(iface['name'])
        if iface_rows:
            self.cursor.executemany(
                "INSERT INTO interfaces (file_id, name, location) VALUES (?, ?, ?)",
                iface_rows
            )
            self.stats["total_interfaces"] += len(iface_rows)

        # Batch insert enums
        enum_rows = []
        enum_names = []
        for enum in data.get('enums', []):
            enum_rows.append((file_id, enum['name'], json.dumps(enum['location'])))
            enum_names.append(enum['name'])
        if enum_rows:
            self.cursor.executemany(
                "INSERT INTO enums (file_id, name, location) VALUES (?, ?, ?)",
                enum_rows
            )
            self.stats["total_enums"] += len(enum_rows)

        # Batch insert namespaces
        ns_rows = []
        for ns in data.get('namespaces', []):
            ns_rows.append((file_id, ns['name'], json.dumps(ns['location'])))
        if ns_rows:
            self.cursor.executemany(
                "INSERT INTO namespaces (file_id, name, location) VALUES (?, ?, ?)",
                ns_rows
            )
            self.stats["total_namespaces"] += len(ns_rows)

        # Dependencies are inserted as external with temp_symbols.
        # Resolution happens in _resolve_all_dependencies after all files are indexed.
        
        # Insert dependencies — all as external with temp_symbols.
        # Resolution happens in a single batch pass after all files are indexed.
        # This avoids 7+ SELECT IN queries per file against tables that grow to millions of rows.
        deps = data.get('dependencies', [])
        if deps:
            dep_rows = []
            temp_pairs_set = set()
            for dep in deps:
                dep_type = dep['type']
                dep_name = dep['name']
                source_func_id = func_id_map.get(dep.pop('_func_index', None))
                loc = json.dumps(dep.get('location')) if dep.get('location') else None
                dep_rows.append((
                    file_id, dep_type, dep_name, source_func_id,
                    None, None, None, loc, 1,
                ))
                temp_pairs_set.add((dep_name, dep_type))

            # Batch insert dependencies
            self.cursor.executemany(
                """INSERT INTO dependencies (file_id, dependency_type, name, source_function_id, target_function_id, target_class_id, temp_symbol_id, location, is_external)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                dep_rows
            )

            # Batch create temp_symbols and link them to deps via SQL UPDATE
            if temp_pairs_set:
                temp_pairs = [(name, dtype, file_id) for name, dtype in temp_pairs_set]
                self.cursor.executemany(
                    "INSERT OR IGNORE INTO temp_symbols (name, symbol_type, file_id) VALUES (?, ?, ?)",
                    temp_pairs
                )
                # Link temp_symbols to deps by matching (name, type) within this file
                self.cursor.execute(
                    """UPDATE dependencies SET temp_symbol_id = (
                         SELECT ts.id FROM temp_symbols ts
                         WHERE ts.name = dependencies.name
                           AND ts.symbol_type = dependencies.dependency_type
                         LIMIT 1
                       )
                       WHERE dependencies.file_id = ? AND dependencies.is_external = 1
                         AND dependencies.temp_symbol_id IS NULL""",
                    (file_id,)
                )

        # Insert frontend semantic data (HTML files)
        self._insert_frontend_data(file_id, data)
    
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

    def _insert_frontend_data(self, file_id, data):
        """Insert frontend semantic data (markup elements, events, selectors, etc.).

        Also performs inline cross-file resolution using temp_symbols and temp_file_references,
        consistent with the existing temp_symbols pattern for dependencies.
        """
        # Lazily load path aliases on first frontend insert
        if not hasattr(self, '_path_aliases_loaded'):
            self.path_aliases = load_path_aliases(self.root_dir)
            self._path_aliases_loaded = True

        # Get the file path for import normalization
        self.cursor.execute("SELECT absolute_path FROM files WHERE id = ?", (file_id,))
        file_row = self.cursor.fetchone()
        source_file_path = file_row[0] if file_row else ""

        # Insert frontend components (JSX/TSX files)
        component_id_map = {}  # component_index -> db id
        for i, comp in enumerate(data.get('frontend_components', [])):
            # Try to link to already-inserted function/class by name
            impl_func_id = None
            impl_class_id = None
            func_name = comp.get('impl_function_name')
            class_name = comp.get('impl_class_name')
            if func_name:
                self.cursor.execute(
                    "SELECT id FROM functions WHERE file_id = ? AND name = ?",
                    (file_id, func_name)
                )
                row = self.cursor.fetchone()
                if row:
                    impl_func_id = row[0]
            if class_name:
                self.cursor.execute(
                    "SELECT id FROM classes WHERE file_id = ? AND name = ?",
                    (file_id, class_name)
                )
                row = self.cursor.fetchone()
                if row:
                    impl_class_id = row[0]

            self.cursor.execute(
                """INSERT INTO frontend_components
                   (file_id, name, framework, source_range, is_exported, impl_function_id, impl_class_id)
                   VALUES (?, ?, 'react', ?, ?, ?, ?)""",
                (
                    file_id,
                    comp['name'],
                    json.dumps(comp.get('source_range')) if comp.get('source_range') else None,
                    1 if comp.get('is_exported') else 0,
                    impl_func_id,
                    impl_class_id,
                )
            )
            comp_db_id = self.cursor.lastrowid
            component_id_map[i] = comp_db_id

            # Resolve any pending temp_symbols for this component name
            self._resolve_component_temp(comp['name'], comp_db_id)

        # Insert markup elements with parent-child and component resolution
        elem_id_map = {}  # index -> db id
        for i, elem in enumerate(data.get('markup_elements', [])):
            parent_idx = elem.get('parent_index')
            parent_db_id = elem_id_map.get(parent_idx) if parent_idx is not None else None
            comp_idx = elem.get('component_index')
            comp_db_id = component_id_map.get(comp_idx) if comp_idx is not None else None
            self.cursor.execute(
                """INSERT INTO markup_elements
                   (file_id, component_id, parent_element_id, tag_name, element_type,
                    source_range, element_id_attr, static_classes, attributes,
                    is_conditional, is_repeated, conditional_expr, repeated_expr)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_id,
                    comp_db_id,
                    parent_db_id,
                    elem['tag_name'],
                    elem['element_type'],
                    json.dumps(elem.get('source_range')) if elem.get('source_range') else None,
                    elem.get('element_id_attr'),
                    json.dumps(elem.get('static_classes')) if elem.get('static_classes') else None,
                    json.dumps(elem.get('attributes')) if elem.get('attributes') else None,
                    1 if elem.get('is_conditional') else 0,
                    1 if elem.get('is_repeated') else 0,
                    elem.get('conditional_expr'),
                    elem.get('repeated_expr'),
                )
            )
            elem_id_map[i] = self.cursor.lastrowid

        # Insert style selectors
        selector_id_map = {}  # index -> db id
        for i, sel in enumerate(data.get('style_selectors', [])):
            self.cursor.execute(
                """INSERT INTO style_selectors
                   (file_id, selector_text, normalized_selector, selector_type, source_range, is_scoped)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    file_id,
                    sel['selector_text'],
                    sel.get('normalized_selector'),
                    sel['selector_type'],
                    json.dumps(sel.get('source_range')) if sel.get('source_range') else None,
                    1 if sel.get('is_scoped') else 0,
                )
            )
            selector_id_map[i] = self.cursor.lastrowid

        # Insert style custom properties
        for cp in data.get('style_custom_properties', []):
            self.cursor.execute(
                """INSERT INTO style_custom_properties
                   (file_id, name, value, source_range, scope_selector)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    file_id,
                    cp['name'],
                    cp.get('value'),
                    json.dumps(cp.get('source_range')) if cp.get('source_range') else None,
                    cp.get('scope_selector'),
                )
            )
            cp_db_id = self.cursor.lastrowid
            # Resolve any pending temp_symbols for this custom property name
            self._resolve_custom_property_temp(cp['name'], cp_db_id)

        # Insert style custom property usages with resolution
        for pu in data.get('style_custom_property_usages', []):
            prop_name = pu['property_name']
            # Try to resolve to existing custom property definition
            resolved_id = self._find_custom_property(prop_name)
            self.cursor.execute(
                """INSERT INTO style_custom_property_usages
                   (file_id, property_name, source_range, selector_id, resolved_property_id)
                   VALUES (?, ?, ?, NULL, ?)""",
                (
                    file_id,
                    prop_name,
                    json.dumps(pu.get('source_range')) if pu.get('source_range') else None,
                    resolved_id,
                )
            )
            if resolved_id is None:
                # Create temp symbol for unresolved custom property reference
                self._create_temp_symbol(prop_name, 'custom_property_reference')

        # Insert style imports with file-path resolution
        for si in data.get('style_imports', []):
            import_path = si['import_path']
            is_external = si.get('is_external', False) or import_path.startswith(("http://", "https://", "//"))

            self.cursor.execute(
                """INSERT INTO style_imports
                   (file_id, import_path, is_external, resolved_file_id, source_range)
                   VALUES (?, ?, ?, NULL, ?)""",
                (
                    file_id,
                    import_path,
                    1 if is_external else 0,
                    json.dumps(si.get('source_range')) if si.get('source_range') else None,
                )
            )
            si_row_id = self.cursor.lastrowid

            if not is_external:
                # Try to resolve the import path to an existing file
                resolved_path = normalize_import_path(import_path, source_file_path, str(self.root_dir), self.path_aliases)
                resolved_file_id = self._find_file_by_path(resolved_path)
                if resolved_file_id:
                    self.cursor.execute(
                        "UPDATE style_imports SET resolved_file_id = ? WHERE id = ?",
                        (resolved_file_id, si_row_id)
                    )
                else:
                    # Create temp_file_reference for later resolution
                    self._create_temp_file_reference(
                        resolved_path, 'style_import', file_id, 'style_imports', si_row_id
                    )

        # Insert frontend events
        for ev in data.get('frontend_events', []):
            elem_idx = ev.get('element_index')
            elem_db_id = elem_id_map.get(elem_idx) if elem_idx is not None else None
            self.cursor.execute(
                """INSERT INTO frontend_events
                   (file_id, element_id, event_name, handler_type, handler_expression,
                    handler_symbol_id, resolution_status, source_range)
                   VALUES (?, ?, ?, ?, ?, NULL, ?, ?)""",
                (
                    file_id,
                    elem_db_id,
                    ev['event_name'],
                    ev['handler_type'],
                    ev.get('handler_expression'),
                    ev.get('resolution_status', 'unresolved'),
                    json.dumps(ev.get('source_range')) if ev.get('source_range') else None,
                )
            )

        # Insert style selector matches
        for sm in data.get('style_selector_matches', []):
            sel_idx = sm.get('selector_index')
            elem_idx = sm.get('element_index')
            sel_db_id = selector_id_map.get(sel_idx) if sel_idx is not None else None
            elem_db_id = elem_id_map.get(elem_idx) if elem_idx is not None else None
            if sel_db_id and elem_db_id:
                self.cursor.execute(
                    """INSERT INTO style_selector_matches
                       (selector_id, element_id, match_type, confidence, source_range)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        sel_db_id,
                        elem_db_id,
                        sm['match_type'],
                        sm.get('confidence', 'high'),
                        json.dumps(sm.get('source_range')) if sm.get('source_range') else None,
                    )
                )

        # Insert frontend diagnostics
        for diag in data.get('frontend_diagnostics', []):
            self.cursor.execute(
                """INSERT INTO frontend_diagnostics
                   (file_id, diagnostic_type, severity, message, source_range)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    file_id,
                    diag['diagnostic_type'],
                    diag['severity'],
                    diag.get('message'),
                    json.dumps(diag.get('source_range')) if diag.get('source_range') else None,
                )
            )

        # Insert style keyframes (CSS files)
        for kf in data.get('style_keyframes', []):
            self.cursor.execute(
                """INSERT INTO style_keyframes
                   (file_id, name, source_range)
                   VALUES (?, ?, ?)""",
                (
                    file_id,
                    kf['name'],
                    json.dumps(kf.get('source_range')) if kf.get('source_range') else None,
                )
            )

        # Insert frontend bindings (JSX/TSX files)
        for b in data.get('frontend_bindings', []):
            elem_db_id = elem_id_map.get(b.get('element_index'))
            self.cursor.execute(
                """INSERT INTO frontend_bindings
                   (file_id, element_id, binding_type, binding_name, binding_expression,
                    resolution_status, source_range)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_id,
                    elem_db_id,
                    b['binding_type'],
                    b.get('binding_name'),
                    b.get('expression'),
                    b.get('resolution_status', 'unresolved'),
                    json.dumps(b.get('source_range')) if b.get('source_range') else None,
                )
            )

        # Insert render relationships with component resolution
        for rr in data.get('render_relationships', []):
            parent_db_id = component_id_map.get(rr.get('parent_component_index'))
            child_elem_db_id = elem_id_map.get(rr.get('element_index'))
            child_name = rr.get('child_component_name')

            # Try to resolve child component by name
            child_component_id = None
            if child_name:
                child_component_id = self._find_component_by_name(child_name)

            self.cursor.execute(
                """INSERT INTO render_relationships
                   (parent_component_id, child_component_id, child_component_name, child_element_id, render_type, controlling_expr)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    parent_db_id,
                    child_component_id,
                    child_name,
                    child_elem_db_id,
                    rr['render_type'],
                    rr.get('controlling_expr'),
                )
            )

            # If child component not found, create temp symbol for later resolution
            if child_name and child_component_id is None:
                self._create_temp_symbol(child_name, 'component_reference')

        # After inserting all data for this file, resolve any pending temp_file_references
        # that point to this file
        relative_path = get_relative_path(source_file_path, self.root_dir)
        self._resolve_temp_file_references_for_file(file_id, relative_path)

    def _find_component_by_name(self, name):
        """Find a frontend_component by name. Returns its id or None."""
        self.cursor.execute(
            "SELECT id FROM frontend_components WHERE name = ? LIMIT 1",
            (name,)
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def _resolve_component_temp(self, name, component_id):
        """When a component is defined, resolve pending component_reference temp_symbols.

        Updates render_relationships.child_component_id for any rows that
        were waiting for this component.
        """
        self.cursor.execute(
            "SELECT id FROM temp_symbols WHERE name = ? AND symbol_type = 'component_reference'",
            (name,)
        )
        temp_rows = self.cursor.fetchall()
        for temp_row in temp_rows:
            temp_id = temp_row[0]
            self.cursor.execute(
                "UPDATE render_relationships SET child_component_id = ? WHERE child_component_id IS NULL AND child_component_name = ?",
                (component_id, name)
            )
            self.cursor.execute("DELETE FROM temp_symbols WHERE id = ?", (temp_id,))

    def _find_custom_property(self, name):
        """Find a style_custom_property by name. Returns its id or None."""
        self.cursor.execute(
            "SELECT id FROM style_custom_properties WHERE name = ? LIMIT 1",
            (name,)
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def _resolve_custom_property_temp(self, name, property_id):
        """When a custom property is defined, resolve pending custom_property_reference temp_symbols.

        Updates style_custom_property_usages.resolved_property_id for any rows
        that were waiting for this property definition.
        """
        self.cursor.execute(
            "SELECT id FROM temp_symbols WHERE name = ? AND symbol_type = 'custom_property_reference'",
            (name,)
        )
        temp_rows = self.cursor.fetchall()
        for temp_row in temp_rows:
            temp_id = temp_row[0]
            self.cursor.execute(
                "UPDATE style_custom_property_usages SET resolved_property_id = ? WHERE resolved_property_id IS NULL AND property_name = ?",
                (property_id, name)
            )
            self.cursor.execute("DELETE FROM temp_symbols WHERE id = ?", (temp_id,))

    def _find_file_by_path(self, relative_path):
        """Find a file by its project-relative path. Returns its id or None."""
        self.cursor.execute(
            "SELECT id FROM files WHERE path = ? LIMIT 1",
            (relative_path,)
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def _create_temp_file_reference(self, resolved_path, reference_type, source_file_id, target_table, target_row_id):
        """Create a temp_file_reference for an unresolved file-path reference."""
        self.cursor.execute(
            """INSERT INTO temp_file_references
               (resolved_path, reference_type, source_file_id, target_table, target_row_id)
               VALUES (?, ?, ?, ?, ?)""",
            (resolved_path, reference_type, source_file_id, target_table, target_row_id)
        )

    def _resolve_temp_file_references_for_file(self, file_id, relative_path):
        """When a file is indexed, resolve any temp_file_references pointing to it.

        Updates the target table rows (e.g. style_imports.resolved_file_id)
        and deletes the resolved temp_file_reference entries.
        """
        self.cursor.execute(
            "SELECT id, target_table, target_row_id FROM temp_file_references WHERE resolved_path = ?",
            (relative_path,)
        )
        refs = self.cursor.fetchall()
        for ref_id, target_table, target_row_id in refs:
            if target_table == 'style_imports':
                self.cursor.execute(
                    "UPDATE style_imports SET resolved_file_id = ? WHERE id = ?",
                    (file_id, target_row_id)
                )
            self.cursor.execute("DELETE FROM temp_file_references WHERE id = ?", (ref_id,))

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

    def _batch_resolve_temp_symbols(self, names, match_types):
        """Batch-resolve temp_symbols for multiple symbol names at once.

        Instead of calling _resolve_temp_for_symbol per symbol (which does a
        SELECT + UPDATE + DELETE per name), this does a single SELECT for all
        names and batches the UPDATE/DELETE.
        """
        if not names or not match_types:
            return
        name_list = list(set(names))  # deduplicate
        type_list = list(match_types)
        SQLITE_MAX_VARS = 900
        all_temp_ids = []
        for i in range(0, len(name_list), SQLITE_MAX_VARS):
            chunk = name_list[i:i + SQLITE_MAX_VARS]
            name_ph = ','.join('?' * len(chunk))
            type_ph = ','.join('?' * len(type_list))
            self.cursor.execute(
                f"SELECT id FROM temp_symbols WHERE name IN ({name_ph}) AND symbol_type IN ({type_ph})",
                chunk + type_list
            )
            all_temp_ids.extend(r[0] for r in self.cursor.fetchall())
        if not all_temp_ids:
            return
        # Batch update + delete in chunks
        for i in range(0, len(all_temp_ids), SQLITE_MAX_VARS):
            chunk = all_temp_ids[i:i + SQLITE_MAX_VARS]
            temp_ph = ','.join('?' * len(chunk))
            self.cursor.execute(
                f"UPDATE dependencies SET is_external = 0, temp_symbol_id = NULL WHERE temp_symbol_id IN ({temp_ph})",
                chunk
            )
            self.cursor.execute(
                f"DELETE FROM temp_symbols WHERE id IN ({temp_ph})",
                chunk
            )

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

    def _resolve_all_dependencies(self):
        """Resolve all temp_symbols against the complete symbol tables.

        Called once after all files are indexed. Uses bulk JOIN/UPDATE queries
        instead of per-file SELECT IN queries. This is the key optimization:
        5 SQL statements instead of 62K × 7.
        """
        # 1. Resolve function_call / method_call temp_symbols → target_function_id
        self.cursor.execute(
            """UPDATE dependencies SET
                 target_function_id = (
                   SELECT f.id FROM functions f
                   WHERE f.name = temp_symbols.name LIMIT 1
                 ),
                 is_external = CASE WHEN EXISTS (
                   SELECT 1 FROM functions f WHERE f.name = temp_symbols.name
                 ) THEN 0 ELSE 1 END,
                 temp_symbol_id = CASE WHEN EXISTS (
                   SELECT 1 FROM functions f WHERE f.name = temp_symbols.name
                 ) THEN NULL ELSE temp_symbol_id END
               FROM temp_symbols
               WHERE dependencies.temp_symbol_id = temp_symbols.id
                 AND temp_symbols.symbol_type IN ('function_call', 'method_call')
                 AND dependencies.target_function_id IS NULL"""
        )

        # 2. Resolve class_reference temp_symbols → target_class_id
        #    Check classes, structs, enums, interfaces, type_aliases
        self.cursor.execute(
            """UPDATE dependencies SET
                 target_class_id = (
                   SELECT c.id FROM classes c
                   WHERE c.name = temp_symbols.name LIMIT 1
                 ),
                 is_external = CASE WHEN EXISTS (
                   SELECT 1 FROM classes c WHERE c.name = temp_symbols.name
                   UNION SELECT 1 FROM structs s WHERE s.name = temp_symbols.name
                   UNION SELECT 1 FROM enums e WHERE e.name = temp_symbols.name
                   UNION SELECT 1 FROM interfaces i WHERE i.name = temp_symbols.name
                   UNION SELECT 1 FROM type_aliases t WHERE t.name = temp_symbols.name
                 ) THEN 0 ELSE 1 END,
                 temp_symbol_id = CASE WHEN EXISTS (
                   SELECT 1 FROM classes c WHERE c.name = temp_symbols.name
                   UNION SELECT 1 FROM structs s WHERE s.name = temp_symbols.name
                   UNION SELECT 1 FROM enums e WHERE e.name = temp_symbols.name
                   UNION SELECT 1 FROM interfaces i WHERE i.name = temp_symbols.name
                   UNION SELECT 1 FROM type_aliases t WHERE t.name = temp_symbols.name
                 ) THEN NULL ELSE temp_symbol_id END
               FROM temp_symbols
               WHERE dependencies.temp_symbol_id = temp_symbols.id
                 AND temp_symbols.symbol_type = 'class_reference'
                 AND dependencies.target_class_id IS NULL"""
        )

        # 3. Resolve variable_reference temp_symbols → is_external = 0
        self.cursor.execute(
            """UPDATE dependencies SET
                 is_external = 0,
                 temp_symbol_id = NULL
               FROM temp_symbols
               WHERE dependencies.temp_symbol_id = temp_symbols.id
                 AND temp_symbols.symbol_type = 'variable_reference'
                 AND EXISTS (
                   SELECT 1 FROM variables v WHERE v.name = temp_symbols.name
                 )"""
        )

        # 4. Delete resolved temp_symbols (those no longer referenced by any dependency)
        self.cursor.execute(
            """DELETE FROM temp_symbols
               WHERE id NOT IN (SELECT DISTINCT temp_symbol_id FROM dependencies WHERE temp_symbol_id IS NOT NULL)"""
        )

        self.conn.commit()

    def _compute_content_hash(self, content):
        """Compute xxhash of file content (faster than SHA-256)."""
        return xxhash.xxh64(content).hexdigest()
    
    def index_directory(self):
        B = "\033[34m"
        R = "\033[0m"
        print(f"{B}analyzing...{R}", flush=True)
        """Index all supported files in the directory recursively."""
        if self.verbose:
            print(f"Starting indexing of {self.root_dir}...")
            print(f"Languages: {', '.join(self.languages)}")

        t_total_start = time.perf_counter()

        t0 = time.perf_counter()
        files = collect_files_to_index(self.root_dir, self.languages)
        if self.verbose:
            print(f"  [timing] file collection: {time.perf_counter() - t0:.3f}s ({len(files)} files)")

        # First pass: identify changed files using mtime (fast, no file reads)
        # Batch-load all existing file metadata from the database in one query
        t0 = time.perf_counter()
        changed_files = []
        files_to_reindex = set()
        skipped_count = 0

        # Load all file metadata in one query instead of per-file SELECT
        self.cursor.execute("SELECT path, id, content_hash, mtime FROM files")
        db_file_meta = {}
        for row in self.cursor.fetchall():
            db_file_meta[row[0]] = (row[1], row[2], row[3])

        for file_path in files:
            language = detect_language(file_path)
            if not language or language not in self._configured_languages:
                continue

            relative_path = get_relative_path(file_path, self.root_dir)
            file_mtime = os.stat(file_path).st_mtime
            
            existing = db_file_meta.get(relative_path)
            
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
        if self.verbose:
            print(f"  [timing] changed-file detection: {time.perf_counter() - t0:.3f}s ({len(files_to_reindex)} to reindex, {skipped_count} skipped)")
        
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
        
        # Second pass: parse files in parallel with sliding window,
        # while a dedicated writer thread handles DB inserts.
        # This eliminates the sawtooth utilization pattern where workers
        # sit idle while the main process does serial DB inserts.
        if files_to_reindex:
            t_parse_start = time.perf_counter()
            worker_args = [(str(fp), str(self.root_dir), self.frontend_enabled) for fp in files_to_reindex]
            max_workers = min(os.cpu_count() or 4, len(worker_args), 16)
            window_size = max_workers * 4  # Keep workers fed with a sliding window

            # Writer thread: consumes parsed results from queue, inserts into DB
            write_queue = queue_mod.Queue(maxsize=window_size * 2)
            insert_errors = []
            
            def _writer_loop():
                """Dedicated writer thread — pulls parsed results and inserts into DB."""
                while True:
                    result = write_queue.get()
                    if result is None:  # sentinel — we're done
                        write_queue.task_done()
                        break
                    if 'error' in result:
                        if self.verbose:
                            print(f"Error parsing {result.get('file_path', '?')}: {result['error']}")
                        write_queue.task_done()
                        continue
                    try:
                        self._insert_parsed_file(result)
                    except Exception as e:
                        insert_errors.append(e)
                        if self.verbose:
                            print(f"Error inserting {result.get('file_path', '?')}: {e}")
                    write_queue.task_done()
                # Final flush after all files inserted
                self._flush_batches()

            writer_thread = threading.Thread(target=_writer_loop, daemon=True)
            writer_thread.start()

            # Sliding window: maintain window_size futures in flight at all times
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                # Submit initial window
                futures = {}
                arg_iter = iter(worker_args)
                for _ in range(min(window_size, len(worker_args))):
                    arg = next(arg_iter)
                    futures[executor.submit(parse_file, arg)] = arg

                while futures:
                    # Wait for any one to complete
                    done = next(as_completed(futures))
                    del futures[done]
                    result = done.result()
                    # Feed to writer thread (blocks if queue is full — backpressure)
                    write_queue.put(result)
                    # Immediately submit next file to keep workers fed
                    try:
                        arg = next(arg_iter)
                        futures[executor.submit(parse_file, arg)] = arg
                    except StopIteration:
                        pass

            # Wait for writer to finish all remaining inserts
            write_queue.put(None)
            writer_thread.join()

            if insert_errors and self.verbose:
                print(f"  {len(insert_errors)} insert errors during indexing")

        if self.verbose and files_to_reindex:
            print(f"  [timing] parse + insert: {time.perf_counter() - t_parse_start:.3f}s ({len(files_to_reindex)} files)")

        # Post-indexing dependency resolution pass
        # Resolve all temp_symbols against the now-complete symbol tables.
        # This is much faster than per-file resolution because we do a few large
        # JOIN/UPDATE queries instead of 62K × 7 SELECT IN queries.
        if files_to_reindex:
            t_resolve_start = time.perf_counter()
            self._resolve_all_dependencies()
            if self.verbose:
                print(f"  [timing] dependency resolution: {time.perf_counter() - t_resolve_start:.3f}s")

        # Run cross-file frontend resolution pass to refresh relationships
        # (render_relationships, style_imports, custom_property_usages, event handlers, selector matches)
        # Skip when no files changed or frontend is disabled to avoid unconditional global work
        if files_to_reindex and self.frontend_enabled:
            t_resolve_start = time.perf_counter()
            try:
                resolver = FrontendResolver(self.conn, str(self.root_dir))
                resolver.resolve_all()
            except Exception as e:
                if self.verbose:
                    print(f"Warning: Frontend resolution pass failed: {e}")

            if self.verbose:
                print(f"  [timing] frontend resolution: {time.perf_counter() - t_resolve_start:.3f}s")

        # Clean up unresolved temp_symbols and their dependencies
        # (these are external/builtin symbols that were never defined in the codebase)
        self.cursor.execute("SELECT COUNT(*) FROM temp_symbols")
        remaining = self.cursor.fetchone()[0]
        if remaining > 0:
            # Clean up traditional dependency temp_symbols
            self.cursor.execute("DELETE FROM dependencies WHERE temp_symbol_id IS NOT NULL")
            # Clean up all remaining temp_symbols (including frontend types: component_reference,
            # custom_property_reference, css_module_class_reference — these are external/missing)
            self.cursor.execute("DELETE FROM temp_symbols")
            self.conn.commit()

        # Clean up unresolved temp_file_references (external URLs or missing files)
        self.cursor.execute("SELECT COUNT(*) FROM temp_file_references")
        remaining_refs = self.cursor.fetchone()[0]
        if remaining_refs > 0:
            self.cursor.execute("DELETE FROM temp_file_references")
            self.conn.commit()
        
        if self.verbose:
            print(f"  [timing] total index_directory: {time.perf_counter() - t_total_start:.3f}s")
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

        # Frontend table counts
        for table_name in ("frontend_components", "markup_elements", "style_selectors",
                           "style_custom_properties", "style_custom_property_usages",
                           "style_keyframes", "style_imports", "frontend_events",
                           "frontend_bindings", "render_relationships",
                           "style_selector_matches", "frontend_diagnostics"):
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                if count > 0:
                    print(f"  {table_name}: {count}")
            except Exception:
                pass

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
    
    if args.list_frontend_languages:
        list_frontend_languages()
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
        
        indexer = CodeIndexer(directory, languages, output_file, args.force, verbose=args.verbose, frontend_enabled=args.frontend)
        indexer.index_directory()
        indexer.save_index()
        indexer.close()
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
