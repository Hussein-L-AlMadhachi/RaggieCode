import os
import subprocess
from pathlib import Path
from functools import lru_cache
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern



BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
GRAY = "\033[90m"
RESET = "\033[0m"



def is_within_cwd(path: str) -> bool:
    """Check if a path resolves to within the current working directory.

    Uses realpath to resolve symlinks, preventing escape via symlink tricks.
    """
    cwd = os.path.realpath(os.getcwd())
    resolved = os.path.realpath(os.path.abspath(path))
    return resolved == cwd or resolved.startswith(cwd + os.sep)



@lru_cache(maxsize=1)
def _load_ignore_spec(cwd: str):
    """Load ignore patterns from .aiignore, falling back to .gitignore.

    Returns a PathSpec instance. Cached per working directory.
    """
    root = Path(cwd)
    aiignore_path = root / '.aiignore'
    gitignore_path = root / '.gitignore'

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



def is_ignored(file_path: str) -> bool:
    """Check if a file path is ignored by .aiignore (or .gitignore as fallback).

    If a .aiignore file exists in the project root, its patterns are used.
    Otherwise, .gitignore is used as a fallback.
    Returns False if neither file exists.
    """
    cwd = os.getcwd()
    spec = _load_ignore_spec(cwd)
    rel = os.path.relpath(os.path.abspath(file_path), cwd)
    return spec.match_file(rel)



def is_ignored_by_gitignore(file_path: str) -> bool:
    """Backward-compatible alias for is_ignored."""
    return is_ignored(file_path)



def reindex_after_change(code_indexer):
    """Re-index the codebase after a file-modifying tool call.

    Silently skips if code_indexer is None or re-indexing fails.
    """
    if code_indexer is None:
        return
    try:
        code_indexer.index_directory()
    except (KeyboardInterrupt, EOFError):
        print(f"{YELLOW}Re-indexing interrupted. Using existing index.{RESET}")
    except Exception as e:
        print(f"{YELLOW}Warning: Failed to re-index after tool execution: {e}{RESET}")



def auto_record_change(session_id, file_path: str, change_type: str, description: str, details: str = None):
    """Auto-record a change to the changes database.

    Looks up the role from the session and records the change.
    Silently fails if the session or database is unavailable.
    """
    if session_id is None:
        return
    try:
        from Agent.chat_history_db import add_change, get_session_role
        role = get_session_role(session_id) or "unknown"
        add_change(
            prompt_id=str(session_id),
            role=role,
            session_id=session_id,
            change_type=change_type,
            file_path=file_path,
            description=description,
            details=details,
        )
    except Exception as e:
        print(f"{RED}Warning: Failed to record change: {e}{RESET}")
