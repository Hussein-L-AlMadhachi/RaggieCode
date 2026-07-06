"""
File and directory utilities for the code indexer.
"""

import os
from pathlib import Path
from indexing.language_config import get_language_for_extension, get_extensions_for_languages
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern


def detect_language(file_path):
    """Detect the language based on file extension."""
    return get_language_for_extension(file_path.suffix)


def load_ignore_patterns(root_dir):
    """Load ignore patterns from .aiignore, falling back to .gitignore.

    If .aiignore exists in the root directory, its patterns are used to
    exclude files from indexing. If .aiignore does not exist, .gitignore
    is used as a fallback.
    """
    root_path = Path(root_dir)
    aiignore_path = root_path / '.aiignore'
    gitignore_path = root_path / '.gitignore'

    ignore_path = None
    if aiignore_path.exists():
        ignore_path = aiignore_path
    elif gitignore_path.exists():
        ignore_path = gitignore_path

    if ignore_path is None:
        return PathSpec.from_lines(GitWildMatchPattern, [])

    with open(ignore_path, 'r', encoding='utf-8') as f:
        patterns = f.read().splitlines()

    return PathSpec.from_lines(GitWildMatchPattern, patterns)


def collect_files_to_index(root_dir, languages):
    """Collect all files to index for given languages, respecting .aiignore (or .gitignore)."""
    root_path = Path(root_dir)
    extensions = get_extensions_for_languages(languages)

    # Load ignore patterns (.aiignore takes priority over .gitignore)
    ignore_spec = load_ignore_patterns(root_dir)
    
    files = []
    ext_set = set(extensions)
    
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Skip test directories
        dirnames[:] = [d for d in dirnames if d not in ('test', 'tests')]
        for filename in filenames:
            if any(filename.endswith(ext) for ext in ext_set):
                file_path = Path(dirpath) / filename
                relative_path = file_path.relative_to(root_path)
                if not ignore_spec.match_file(str(relative_path)):
                    files.append(file_path)
    
    return files


def read_file_content(file_path):
    """Read file content in binary mode for faster processing."""
    with open(file_path, 'rb') as f:
        return f.read()


def get_relative_path(file_path, root_dir):
    """Get relative path from root directory."""
    return str(Path(file_path).relative_to(root_dir))
