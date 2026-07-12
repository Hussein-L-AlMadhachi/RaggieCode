import os
from dulwich import repo
from dulwich import objects
from datetime import datetime

RED = "\033[31m"
RESET = "\033[0m"


class GitManager:
    """Manages git-like operations using dulwich in the .raggie directory."""
    
    def __init__(self, root_dir=None):
        """Initialize the GitManager.
        
        Args:
            root_dir: The root directory of the project. Defaults to current working directory.
        """
        self.root_dir = root_dir or os.getcwd()
        self.raggie_dir = os.path.join(self.root_dir, ".raggie")
        self.repo_path = os.path.join(self.raggie_dir, "git")
        self._ensure_repo()
    
    def _ensure_repo(self):
        """Ensure the git repository exists in .raggie directory."""
        # Check for stale undo marker (crash recovery)
        marker_path = os.path.join(self.raggie_dir, ".undoing")
        if os.path.exists(marker_path):
            print(f"Warning: Found stale undo marker at {marker_path}. "
                  f"A previous undo may have been interrupted. "
                  f"Some files may be missing.")
            try:
                os.remove(marker_path)
            except (IOError, OSError) as e:
                print(f"{RED}Warning: Failed to remove stale undo marker: {e}{RESET}")

        # Check for stale redo marker (crash recovery)
        redo_marker_path = os.path.join(self.raggie_dir, ".redoing")
        if os.path.exists(redo_marker_path):
            print(f"Warning: Found stale redo marker at {redo_marker_path}. "
                  f"A previous redo may have been interrupted. "
                  f"Some files may be missing.")
            try:
                os.remove(redo_marker_path)
            except (IOError, OSError) as e:
                print(f"{RED}Warning: Failed to remove stale redo marker: {e}{RESET}")

        if not os.path.exists(self.repo_path):
            os.makedirs(self.repo_path, exist_ok=True)
            # Initialize a new git repository
            self.repo = repo.Repo.init(self.repo_path)
            # Create initial commit
            self._create_initial_commit()
        else:
            try:
                self.repo = repo.Repo(self.repo_path)
            except Exception:
                # If it's not a valid repo, reinitialize
                self.repo = repo.Repo.init(self.repo_path)
                self._create_initial_commit()
    
    def _create_initial_commit(self):
        """Create an initial empty commit."""
        # Create an empty tree
        tree = objects.Tree()
        self.repo.object_store.add_object(tree)
        
        # Create a commit with the empty tree
        commit = objects.Commit()
        commit.tree = tree.id
        commit.author = commit.committer = b"Raggie <raggie@local>"
        commit.commit_time = commit.author_time = int(datetime.now().timestamp())
        commit.commit_timezone = commit.author_timezone = 0
        commit.message = b"Initial commit"
        
        self.repo.object_store.add_object(commit)
        self.repo.refs[b"refs/heads/main"] = commit.id
    
    def add_changed_files(self):
        """DEPRECATED: This method is a no-op and kept only for API compatibility.

        The tree is now built from scratch during commit() via _walk_filesystem().
        This method will be removed in a future version.
        """
        pass
    
    def _build_nested_tree(self, files_dict):
        """Build nested Tree objects from a {rel_path: blob_id} mapping.

        Creates proper nested trees for subdirectories, making the repository
        compatible with standard git tools.

        Args:
            files_dict: Dict mapping relative file paths to blob IDs.

        Returns:
            Root Tree object.
        """
        if not files_dict:
            return objects.Tree()

        # Group entries by directory
        dir_entries = {}  # {dirname: {basename: blob_id}}
        for rel_path, blob_id in files_dict.items():
            parts = rel_path.split(os.sep)
            dirname = os.sep.join(parts[:-1]) if len(parts) > 1 else ''
            basename = parts[-1]
            dir_entries.setdefault(dirname, {})[basename] = blob_id

        # Collect all unique directory paths (including intermediates)
        all_dirs = set(dir_entries.keys())
        all_dirs.add('')  # Ensure root is always present
        for d in list(all_dirs):
            if d:
                parts = d.split(os.sep)
                for i in range(1, len(parts)):
                    all_dirs.add(os.sep.join(parts[:i]))

        # Build trees bottom-up (deepest directories first)
        sorted_dirs = sorted(
            all_dirs,
            key=lambda d: d.count(os.sep) if d else -1,
            reverse=True
        )

        tree_cache = {}  # {dirname: Tree object}
        for dirname in sorted_dirs:
            t = objects.Tree()

            # Add file entries in this directory
            for basename, blob_id in dir_entries.get(dirname, {}).items():
                t.add(basename.encode('utf-8'), 0o100644, blob_id)

            # Add subtree entries (child directories)
            prefix = dirname + os.sep if dirname else ''
            for child_dirname, child_tree in tree_cache.items():
                if child_dirname.startswith(prefix):
                    remainder = child_dirname[len(prefix):]
                    if remainder and os.sep not in remainder:
                        t.add(remainder.encode('utf-8'), 0o040000, child_tree.id)

            self.repo.object_store.add_object(t)
            tree_cache[dirname] = t

        return tree_cache.get('', objects.Tree())

    def commit(self, message):
        """Commit the current state of the working tree.

        Builds the tree from the filesystem with proper nested tree objects
        for subdirectories, making the repository compatible with standard git.

        Args:
            message: The commit message.

        Returns:
            The commit ID.
        """
        # Get the current HEAD
        try:
            head_id = self.repo.refs[b"refs/heads/main"]
            parent_ids = [head_id]
        except KeyError:
            parent_ids = []

        # Collect all files and their blob IDs from the filesystem
        file_blobs = {}  # {rel_path: blob_id}
        for rel_path, full_path in self._walk_filesystem():
            try:
                with open(full_path, 'rb') as f:
                    data = f.read()
                blob = objects.Blob.from_string(data)
                self.repo.object_store.add_object(blob)
                file_blobs[rel_path] = blob.id
            except (IOError, OSError):
                continue

        # Build proper nested tree structure
        root_tree = self._build_nested_tree(file_blobs)
        self.repo.object_store.add_object(root_tree)

        # Create the commit
        commit = objects.Commit()
        commit.tree = root_tree.id
        commit.parents = parent_ids
        commit.author = commit.committer = b"Raggie <raggie@local>"
        commit.commit_time = commit.author_time = int(datetime.now().timestamp())
        commit.commit_timezone = commit.author_timezone = 0
        commit.message = message.encode('utf-8') if isinstance(message, str) else message

        self.repo.object_store.add_object(commit)
        self.repo.refs[b"refs/heads/main"] = commit.id

        # A new commit invalidates the redo history
        self._clear_redo_stack()

        return bytes(commit.id).decode('utf-8')
    
    def _restore_tree_recursive(self, tree_id, base_path=''):
        """Recursively restore files from a tree, handling nested subtrees.

        Args:
            tree_id: The ID of the tree object to restore from.
            base_path: The relative directory path under root_dir.
        """
        tree = self.repo.object_store[tree_id]
        for item in tree.items():
            name, mode, oid = item
            if isinstance(name, bytes):
                name = name.decode('utf-8')

            path = os.path.join(base_path, name) if base_path else name
            obj = self.repo.object_store[oid]

            if isinstance(obj, objects.Tree):
                # Recurse into subtree (directory)
                self._restore_tree_recursive(oid, path)
            else:
                # It's a blob — write the file
                blob = obj
                file_path = os.path.join(self.root_dir, path)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'wb') as f:
                    f.write(blob.data)

    def _delete_working_files(self):
        """Delete all tracked files from the working directory (respecting exclusions).

        Uses the same ignore rules as _walk_filesystem() so that gitignored /
        aiignored files (e.g. .env, *.db) are never deleted during undo/redo.
        """
        try:
            from Tools.utils import is_ignored_by_gitignore
        except ImportError:
            def is_ignored_by_gitignore(_path):
                return False

        excluded_dirs, excluded_exts = self._get_exclusions()
        for root, dirs, files in os.walk(self.root_dir, topdown=False, followlinks=False):
            path_components = root.replace(os.sep, '/').split('/')
            if any(part in excluded_dirs for part in path_components):
                continue

            for file in files:
                if any(file.endswith(ext) for ext in excluded_exts):
                    continue
                file_path = os.path.join(root, file)
                if is_ignored_by_gitignore(file_path):
                    continue
                try:
                    os.remove(file_path)
                except (IOError, OSError) as e:
                    print(f"{RED}Warning: Failed to remove {file_path}: {e}{RESET}")

    def _redo_stack_path(self):
        """Return the path to the redo stack file."""
        return os.path.join(self.raggie_dir, ".redo_stack")

    def _read_redo_stack(self):
        """Read the redo stack and return a list of commit SHAs (top of stack last)."""
        path = self._redo_stack_path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, 'r') as f:
                return [line.strip() for line in f if line.strip()]
        except (IOError, OSError):
            return []

    def _write_redo_stack(self, stack):
        """Write the redo stack (list of commit SHAs) to disk."""
        path = self._redo_stack_path()
        try:
            with open(path, 'w') as f:
                for sha in stack:
                    f.write(sha + '\n')
        except (IOError, OSError) as e:
            print(f"{RED}Warning: Failed to write redo stack: {e}{RESET}")

    def _clear_redo_stack(self):
        """Clear the redo stack file."""
        path = self._redo_stack_path()
        try:
            if os.path.exists(path):
                os.remove(path)
        except (IOError, OSError) as e:
            print(f"{RED}Warning: Failed to clear redo stack: {e}{RESET}")

    def undo_last_commit(self):
        """Undo the last commit by restoring files from the previous commit.

        Uses a marker file for crash recovery: if the process is interrupted
        between deletion and restoration, the marker persists and a warning
        is shown on next startup.

        The undone commit is pushed onto a redo stack so it can be re-applied
        with ``redo_last_commit``.

        Returns:
            The previous commit ID, or None if there's no previous commit.
        """
        try:
            head_id = self.repo.refs[b"refs/heads/main"]
            head_commit = self.repo.object_store[head_id]

            if not head_commit.parents:
                # No parent commit, can't undo
                return None

            # Get the parent commit
            parent_id = head_commit.parents[0]
            parent_commit = self.repo.object_store[parent_id]
            parent_commit_sha = bytes(parent_id).decode('utf-8')

            # --- Transaction safety: write marker before making changes ---
            marker_path = os.path.join(self.raggie_dir, ".undoing")
            try:
                with open(marker_path, 'w') as f:
                    f.write(f"Undoing to {parent_commit_sha}")
            except (IOError, OSError) as e:
                print(f"{RED}Warning: Failed to write undo marker: {e}{RESET}")

            # Delete all current files and restore from parent tree
            self._delete_working_files()
            self._restore_tree_recursive(parent_commit.tree)

            # Reset HEAD to the parent
            self.repo.refs[b"refs/heads/main"] = parent_id

            # Push the undone commit onto the redo stack
            redo_stack = self._read_redo_stack()
            redo_stack.append(bytes(head_id).decode('utf-8'))
            self._write_redo_stack(redo_stack)

            # --- Transaction safety: remove marker after successful completion ---
            try:
                if os.path.exists(marker_path):
                    os.remove(marker_path)
            except (IOError, OSError) as e:
                print(f"{RED}Warning: Failed to remove undo marker after completion: {e}{RESET}")

            return parent_commit_sha
        except KeyError:
            return None

    def redo_last_commit(self):
        """Redo the last undone commit.

        Pops the top commit from the redo stack, restores its files, and
        moves HEAD to it. Uses a marker file for crash recovery.

        Returns:
            The redone commit ID, or None if there's nothing to redo.
        """
        redo_stack = self._read_redo_stack()
        if not redo_stack:
            return None

        commit_sha = redo_stack.pop()
        commit_id = commit_sha.encode('utf-8')

        try:
            commit_obj = self.repo.object_store[commit_id]
        except KeyError:
            # Commit object no longer exists
            self._write_redo_stack(redo_stack)
            return None

        # --- Transaction safety: write marker before making changes ---
        marker_path = os.path.join(self.raggie_dir, ".redoing")
        try:
            with open(marker_path, 'w') as f:
                f.write(f"Redoing to {commit_sha}")
        except (IOError, OSError) as e:
            print(f"{RED}Warning: Failed to write redo marker: {e}{RESET}")

        # Delete all current files and restore from the redone commit's tree
        self._delete_working_files()
        self._restore_tree_recursive(commit_obj.tree)

        # Move HEAD to the redone commit
        self.repo.refs[b"refs/heads/main"] = commit_id

        # Save the updated redo stack
        self._write_redo_stack(redo_stack)

        # --- Transaction safety: remove marker after successful completion ---
        try:
            if os.path.exists(marker_path):
                os.remove(marker_path)
        except (IOError, OSError) as e:
            print(f"{RED}Warning: Failed to remove redo marker after completion: {e}{RESET}")

        return commit_sha
    
    def get_last_commit_message(self):
        """Get the message of the last commit.
        
        Returns:
            The last commit message, or None if there are no commits.
        """
        try:
            head_id = self.repo.refs[b"refs/heads/main"]
            head_commit = self.repo.object_store[head_id]
            return head_commit.message.decode('utf-8')
        except KeyError:
            return None

    def get_last_commit_sha(self):
        """Get the full SHA of the last commit.

        Returns:
            The full hex SHA string of the last commit, or None if no commits exist.
        """
        try:
            head_id = self.repo.refs[b"refs/heads/main"]
            return bytes(head_id).decode('utf-8')
        except KeyError:
            return None
    
    def _get_exclusions(self):
        """Return the set of directory names and file extensions to exclude."""
        excluded_dirs = {'.raggie', '.git', '.venv', '__pycache__', 'build', 'dist', '.egg-info'}
        excluded_exts = {'.pyc', '.pyo', '.pyd', '.so', '.dll', '.dylib', '.exe'}
        return excluded_dirs, excluded_exts
    
    def _walk_filesystem(self):
        """Walk the root directory and yield (rel_path, full_path) for includable files.

        Respects .gitignore rules, skips symlinks, and excludes common
        build/artifact directories.
        """
        # Import gitignore checker with graceful fallback
        try:
            from Tools.utils import is_ignored_by_gitignore
        except ImportError:
            def is_ignored_by_gitignore(_path):
                return False

        excluded_dirs, excluded_exts = self._get_exclusions()
        for root, dirs, files in os.walk(self.root_dir, followlinks=False):
            dirs[:] = [d for d in dirs if d not in excluded_dirs]
            for file in files:
                if any(file.endswith(ext) for ext in excluded_exts):
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, self.root_dir)
                if is_ignored_by_gitignore(full_path):
                    continue
                yield rel_path, full_path
    
    def _get_last_commit_tree(self):
        """Get the tree object of the last commit, or None if no commits exist."""
        try:
            head_id = self.repo.refs[b"refs/heads/main"]
            head_commit = self.repo.object_store[head_id]
            return self.repo.object_store[head_commit.tree]
        except KeyError:
            return None
    
    def _build_tree_lookup(self, tree):
        """Build a dict mapping file paths to blob IDs, recursing into nested subtrees.

        Handles both the old flat tree format and the new nested tree format
        for backward compatibility.
        """
        lookup = {}
        if tree is None:
            return lookup

        def _walk(node, prefix=''):
            for item in node.items():
                name, mode, oid = item
                if isinstance(name, bytes):
                    name = name.decode('utf-8')
                path = os.path.join(prefix, name) if prefix else name

                obj = self.repo.object_store[oid]
                if isinstance(obj, objects.Tree):
                    # Recurse into subtree
                    _walk(obj, path)
                else:
                    # It's a blob
                    lookup[path] = oid

        _walk(tree)
        return lookup
    
    def _collect_fs_files(self, path_filter=None):
        """Walk the filesystem once and return {rel_path: blob_id}.

        Uses a single os.walk pass. Returns a dict of relative paths to
        blob SHA hashes for all files in the root directory.
        """
        fs_files = {}
        for rel_path, full_path in self._walk_filesystem():
            if path_filter and path_filter not in rel_path:
                continue
            try:
                with open(full_path, 'rb') as f:
                    data = f.read()
                blob = objects.Blob.from_string(data)
                fs_files[rel_path] = blob.id
            except (IOError, OSError):
                continue
        return fs_files

    def get_status(self, category=None):
        """Get the working tree status compared to the last commit.
        
        Args:
            category: Optional. If set to 'added', 'modified', 'deleted', or 'unchanged',
                      only return files in that category. The result dict still contains
                      all four keys but only the requested one will be populated.
        
        Returns:
            A dict with keys 'added', 'modified', 'deleted', 'unchanged' each being
            a list of file paths. Also includes 'commit_id' and 'commit_message'
            of the last commit, or None if no commits exist.
        
        Raises:
            ValueError: If category is not None and not one of the valid values.
        """
        VALID_CATEGORIES = {'added', 'modified', 'deleted', 'unchanged'}
        if category is not None and category not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
            )
        tree = self._get_last_commit_tree()
        tree_files = self._build_tree_lookup(tree)
        
        # Single filesystem pass
        fs_files = self._collect_fs_files()
        
        result = {
            'added': [],
            'modified': [],
            'deleted': [],
            'unchanged': [],
        }
        
        # Check files in both sets
        all_paths = set(fs_files.keys()) | set(tree_files.keys())
        for path in sorted(all_paths):
            fs_id = fs_files.get(path)
            tree_id = tree_files.get(path)
            
            if fs_id is not None and tree_id is None:
                if category is None or category == 'added':
                    result['added'].append(path)
            elif fs_id is None and tree_id is not None:
                if category is None or category == 'deleted':
                    result['deleted'].append(path)
            elif fs_id != tree_id:
                if category is None or category == 'modified':
                    result['modified'].append(path)
            else:
                if category is None or category == 'unchanged':
                    result['unchanged'].append(path)
        
        # Include info about the last commit
        try:
            head_id = self.repo.refs[b"refs/heads/main"]
            head_commit = self.repo.object_store[head_id]
            result['commit_id'] = bytes(head_id).decode('utf-8')
            result['commit_message'] = head_commit.message.decode('utf-8')
        except KeyError:
            result['commit_id'] = None
            result['commit_message'] = None
        
        return result
    
    def _truncate_diff(self, text, max_lines):
        """Truncate a diff text to max_lines, keeping head and tail."""
        if max_lines is None or max_lines <= 0:
            return text
        lines = text.splitlines(True)
        if len(lines) <= max_lines:
            return text
        half = max(1, max_lines // 2)
        head = lines[:half]
        tail = lines[-half:]
        truncated = len(lines) - (half + len(tail))
        if truncated <= 0:
            return text
        return ''.join(head) + f"... ({truncated} lines truncated) ...\n" + ''.join(tail)

    def get_diff(self, path_filter=None, max_diff_lines=500):
        """Get the diff between the working tree and the last commit.
        
        Args:
            path_filter: Optional. If set, only show diff for files whose path
                         contains this substring.
            max_diff_lines: Optional. Maximum number of lines per diff.
                            If exceeded, the middle is truncated with a marker.
                            Set to 0 or None for no limit.
        
        Returns:
            A list of dicts, each with keys: 'path', 'change_type' ('added'/'modified'/'deleted'),
            'content' (the diff text for modified, full content for added/deleted).
            Returns empty list if no commits exist.
        """
        tree = self._get_last_commit_tree()
        tree_lookup = self._build_tree_lookup(tree)
        
        diffs = []
        
        # Single filesystem walk: collect (path, data) for all fs files
        fs_data = {}  # {rel_path: raw_bytes}
        for rel_path, full_path in self._walk_filesystem():
            if path_filter and path_filter not in rel_path:
                continue
            try:
                with open(full_path, 'rb') as f:
                    fs_data[rel_path] = f.read()
            except (IOError, OSError):
                continue
        
        fs_paths = set(fs_data.keys())
        
        # Compare each fs file against the tree
        for rel_path, current_data in fs_data.items():
            tree_blob_id = tree_lookup.get(rel_path)
            
            if tree_blob_id is None:
                # File is new
                try:
                    text = current_data.decode('utf-8')
                except UnicodeDecodeError:
                    text = f"[binary file, {len(current_data)} bytes]"
                if max_diff_lines:
                    text = self._truncate_diff(text, max_diff_lines)
                diffs.append({
                    'path': rel_path,
                    'change_type': 'added',
                    'content': text,
                })
            else:
                tree_blob = self.repo.object_store[tree_blob_id]
                tree_data = tree_blob.data
                
                if tree_data != current_data:
                    # File is modified
                    try:
                        old_text = tree_data.decode('utf-8').splitlines(True)
                        new_text = current_data.decode('utf-8').splitlines(True)
                    except UnicodeDecodeError:
                        diffs.append({
                            'path': rel_path,
                            'change_type': 'modified',
                            'content': f"[binary file, old: {len(tree_data)} bytes, new: {len(current_data)} bytes]",
                        })
                        continue
                    
                    import difflib
                    diff_text = ''.join(difflib.unified_diff(
                        old_text, new_text,
                        fromfile=f'a/{rel_path}', tofile=f'b/{rel_path}', lineterm=''
                    ))
                    
                    if max_diff_lines:
                        diff_text = self._truncate_diff(diff_text, max_diff_lines)
                    
                    diffs.append({
                        'path': rel_path,
                        'change_type': 'modified',
                        'content': diff_text,
                    })
        
        # Check for deleted files (in tree but not on filesystem)
        for tree_path, blob_id in tree_lookup.items():
            if path_filter and path_filter not in tree_path:
                continue
            if tree_path not in fs_paths:
                tree_blob = self.repo.object_store[blob_id]
                try:
                    text = tree_blob.data.decode('utf-8')
                except UnicodeDecodeError:
                    text = f"[binary file, {len(tree_blob.data)} bytes]"
                if max_diff_lines:
                    text = self._truncate_diff(text, max_diff_lines)
                diffs.append({
                    'path': tree_path,
                    'change_type': 'deleted',
                    'content': text,
                })
        
        return diffs
    
    def get_log(self, max_count=10):
        """Get the commit history.
        
        Args:
            max_count: Maximum number of commits to return (default 10).
        
        Returns:
            A list of dicts, each with keys: 'commit_id', 'message', 'timestamp', 'author'.
            Most recent commit first.
        """
        commits = []
        try:
            commit_id = self.repo.refs[b"refs/heads/main"]
        except KeyError:
            return commits
        
        for _ in range(max_count):
            try:
                commit = self.repo.object_store[commit_id]
            except KeyError:
                break
            
            from datetime import timezone
            ts = datetime.fromtimestamp(commit.commit_time, tz=timezone.utc)
            
            commits.append({
                'commit_id': bytes(commit_id).decode('utf-8'),
                'message': commit.message.decode('utf-8'),
                'timestamp': ts.isoformat(),
                'author': commit.author.decode('utf-8'),
            })
            
            if commit.parents:
                commit_id = commit.parents[0]
            else:
                break
        
        return commits
