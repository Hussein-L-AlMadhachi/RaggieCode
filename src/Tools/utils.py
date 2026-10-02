import os
from pathlib import Path
from functools import lru_cache
from pathspec import GitIgnoreSpec


BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
GRAY = "\033[90m"
DIM = "\033[2m"
RESET = "\033[0m"


# Paths approved with "always" for the current process. Stored as resolved
# realpaths so symlinks can't bypass the check. A directory entry grants
# access to everything under it.
_approved_paths: set = set()
_last_denial_reason: str = ""


def _path_granted(file_path: str) -> bool:
    """Check if a path (or a parent directory) was approved with 'always'."""
    resolved = os.path.realpath(os.path.abspath(file_path))
    for approved in _approved_paths:
        if resolved == approved or resolved.startswith(approved + os.sep):
            return True
    return False


def prompt_path_permission(file_path: str, operation: str, reason: str) -> bool:
    """Prompt the user for permission to access a restricted path.

    Parameters:
      file_path: The path the tool wants to access.
      operation: A short verb describing the action (e.g. "read", "write",
        "remove", "replace").
      reason: Why permission is needed (e.g. "outside the current working
        directory" or "gitignored").

    Returns True if the user approves (yes or always), False if denied.

    In terminal mode, the user is asked interactively with three options:
      (a)lways - approve and remember for this path for the session
      (y)es    - approve just this once
      (n)o     - deny, optionally with a reason that is surfaced back to the
                 agent via denial_content()

    In headless modes (ACP), sys.stdin is the protocol stream, so raw
    input() would consume protocol bytes or block. Instead the request is
    routed through io_backend.confirm_with_always(), which may go to the
    client via the thread-local permission handler or fall back to the
    auto-approve policy. A denial reason, if any, is collected via
    io_backend.ask().
    """
    # Check if already approved via "always"
    if _path_granted(file_path):
        return True

    # Reset so a stale reason from a previously denied prompt is never reused
    global _last_denial_reason
    _last_denial_reason = ""

    # Imported lazily: io_backend imports constants from this module, so a
    # top-level import would create a circular import.
    import io_backend

    if io_backend.is_headless():
        # Never read sys.stdin directly in headless mode.
        result = io_backend.confirm_with_always(
            f"Permission requested: {operation} {file_path}",
            f"Reason: {reason}",
        )
        if result == io_backend.ALLOW_ALWAYS:
            _approved_paths.add(os.path.realpath(os.path.abspath(file_path)))
            return True
        if result == io_backend.ALLOW:
            return True
        # Denied: collect an optional reason so the agent knows why it was refused
        denial_reason = io_backend.ask("Reason for denial (optional, press Enter to skip):")
        if denial_reason:
            _last_denial_reason = denial_reason
        return False

    try:
        print(f"\n{YELLOW}Permission requested: {operation} {file_path}{RESET}")
        print(f"{YELLOW}Reason: {reason}{RESET}")
        print(f"{BLUE}Options: (a)lways  (y)es  (n)o{RESET}")
        choice = input("Choice: ").strip().lower()
        print()
    except (KeyboardInterrupt, EOFError):
        print()
        return False

    if choice in ("a", "always"):
        resolved = os.path.realpath(os.path.abspath(file_path))
        _approved_paths.add(resolved)
        return True
    if choice in ("y", "yes"):
        return True

    # Denied: collect an optional reason so the agent knows why it was refused
    try:
        denial_reason = input(f"{BLUE}Reason for denial (optional, press Enter to skip): {RESET}").strip()
        if denial_reason:
            _last_denial_reason = denial_reason
    except (KeyboardInterrupt, EOFError):
        print()
    return False


def denial_content(content: str) -> str:
    """Build the tool-result content for a denied permission request.

    Appends the reason the user gave at the denial prompt (if any) so the
    agent understands why access was refused and can adjust its approach.
    """
    if _last_denial_reason:
        return f"{content} (user denied access - reason: {_last_denial_reason})"
    return content


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

    .aiignore intentionally overrides .gitignore: when it exists, it is
    the sole source of ignore rules. Returns a GitIgnoreSpec instance.
    Cached per working directory.

    Uses GitIgnoreSpec, which replicates Git's actual gitignore behavior
    (including re-including files from excluded directories).
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
        return GitIgnoreSpec.from_lines([])

    with open(ignore_path, 'r', encoding='utf-8') as f:
        patterns = f.read().splitlines()

    return GitIgnoreSpec.from_lines(patterns)



@lru_cache(maxsize=1)
def _load_gitignore_spec(cwd: str):
    """Load ignore patterns from the project's .gitignore only.

    Unlike _load_ignore_spec(), .aiignore is never consulted. Version
    tracking (the hidden snapshot repo) follows gitignore semantics: what
    the user's VCS ignores must not be snapshotted or diffed, regardless
    of what the agent-exploration filter says. Cached per working directory.
    """
    root = Path(cwd)
    gitignore_path = root / '.gitignore'

    if not gitignore_path.exists():
        return GitIgnoreSpec.from_lines([])

    with open(gitignore_path, 'r', encoding='utf-8') as f:
        patterns = f.read().splitlines()

    return GitIgnoreSpec.from_lines(patterns)


def is_ignored_by_gitignore_file(file_path: str) -> bool:
    """Check if a file path is ignored by the project's .gitignore (only).

    Unlike is_ignored(), .aiignore is never consulted   this mirrors what
    the user's actual VCS would ignore. Used by the hidden tracking repo.
    """
    cwd = os.getcwd()
    spec = _load_gitignore_spec(cwd)
    rel = os.path.relpath(os.path.abspath(file_path), cwd)
    return spec.match_file(rel)


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
