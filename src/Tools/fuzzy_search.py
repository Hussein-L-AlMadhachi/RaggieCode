import os
from pathlib import Path
from .utils import is_ignored, BLUE, RESET


def _fuzzy_score(query: str, target: str):
    """Return a score for how well *target* matches *query* fuzzily.

    Uses a subsequence-matching algorithm with bonuses for:
    - Exact substring match (highest priority)
    - Consecutive character matches
    - Matches at word boundaries (start of string, after separator)

    Returns None if query is not a subsequence of target.
    """
    query = query.lower()
    target = target.lower()

    if not query:
        return 0

    # Exact substring — best possible match
    if query in target:
        return 100 + (len(target) - len(query))

    qi = 0
    score = 0
    prev_match = -1

    for ti, ch in enumerate(target):
        if qi < len(query) and ch == query[qi]:
            # Bonus for match at start of string or after a separator
            if ti == 0 or target[ti - 1] in "/._- ":
                score += 10
            # Bonus for consecutive matches
            if prev_match == ti - 1:
                score += 5
            score += 1
            prev_match = ti
            qi += 1

    if qi < len(query):
        return None  # Not all query chars matched

    # Penalise longer targets (prefer shorter file names)
    score -= len(target) * 0.1

    return score


def handle(arguments, toolcall_id):
    query = arguments.get("query", "")
    directory = arguments.get("directory", os.getcwd())
    max_results = arguments.get("max_results", 5)

    print(f"{BLUE}Fuzzy file search '{query}' in '{directory}'{RESET}")

    if not query:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: query is required",
        }

    try:
        root = Path(directory)
        if not root.exists():
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "Directory not found",
            }
        if not root.is_dir():
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "Path is not a directory",
            }

        results = []
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip hidden directories like .git, __pycache__, etc.
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d != "__pycache__"
            ]
            for filename in filenames:
                full_path = os.path.join(dirpath, filename)
                if is_ignored(full_path):
                    continue
                score = _fuzzy_score(query, filename)
                if score is not None:
                    rel_path = os.path.relpath(full_path, root)
                    results.append((score, rel_path))

        results.sort(key=lambda x: (-x[0], x[1]))
        results = results[:max_results]

        if not results:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"No files matching '{query}' found.",
            }

        lines = [f"Found {len(results)} file(s) matching '{query}':"]
        for score, path in results:
            lines.append(f"  {path}")
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "\n".join(lines),
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error during fuzzy search: {str(e)}",
        }
