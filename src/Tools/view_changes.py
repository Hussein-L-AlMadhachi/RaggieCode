import os
from Agent.git_manager import GitManager
from .utils import BLUE, RESET


def handle(arguments, toolcall_id):
    """Handle ViewChanges tool calls."""
    print(f"{BLUE}ViewChanges{RESET}")

    view_type = arguments.get("view_type", "status")
    path = arguments.get("path")
    max_count = arguments.get("max_count", 10)
    category = arguments.get("category")
    max_diff_lines = arguments.get("max_diff_lines", 500)

    # --- Input validation ---
    VALID_VIEW_TYPES = {'status', 'diff', 'log'}
    if view_type not in VALID_VIEW_TYPES:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": (
                f"Unknown view_type: '{view_type}'. "
                f"Supported values: {', '.join(sorted(VALID_VIEW_TYPES))}."
            ),
        }

    # Treat empty string category as None (no filter)
    if category is not None and category == "":
        category = None

    VALID_CATEGORIES = {'added', 'modified', 'deleted', 'unchanged'}
    if category is not None and category not in VALID_CATEGORIES:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": (
                f"Invalid category: '{category}'. "
                f"Must be one of: {', '.join(sorted(VALID_CATEGORIES))}."
            ),
        }

    # Validate max_count
    if not isinstance(max_count, (int, float)) or isinstance(max_count, bool):
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Invalid max_count: must be a number, got {type(max_count).__name__}.",
        }
    max_count = int(max_count)
    if max_count < 0:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Invalid max_count: must be non-negative, got {max_count}.",
        }

    # Validate max_diff_lines
    if max_diff_lines is not None:
        if not isinstance(max_diff_lines, (int, float)) or isinstance(max_diff_lines, bool):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Invalid max_diff_lines: must be a number, got {type(max_diff_lines).__name__}.",
            }
        max_diff_lines = int(max_diff_lines)
        if max_diff_lines < 0:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Invalid max_diff_lines: must be non-negative, got {max_diff_lines}.",
            }

    try:
        git_manager = GitManager(root_dir=os.getcwd())

        if view_type == "status":
            status = git_manager.get_status(category=category)
            result_parts = []

            if status["commit_id"]:
                result_parts.append(f"Last commit: {status['commit_id'][:8]} - {status['commit_message']}")
            else:
                result_parts.append("No commits yet.")

            if category:
                # Only show the requested category
                label = category.capitalize()
                items = status[category]
                result_parts.append("")
                result_parts.append(f"{label} ({len(items)}):")
                for f in items[:50]:
                    symbol = {"added": "+", "modified": "~", "deleted": "-", "unchanged": " "}.get(category, "")
                    result_parts.append(f"  {symbol} {f}")
                if len(items) > 50:
                    result_parts.append(f"  ... and {len(items) - 50} more")
            else:
                # Show all categories
                result_parts.append("")
                result_parts.append(f"Added ({len(status['added'])}):")
                for f in status["added"][:50]:
                    result_parts.append(f"  + {f}")
                if len(status["added"]) > 50:
                    result_parts.append(f"  ... and {len(status['added']) - 50} more")

                result_parts.append("")
                result_parts.append(f"Modified ({len(status['modified'])}):")
                for f in status["modified"][:50]:
                    result_parts.append(f"  ~ {f}")
                if len(status["modified"]) > 50:
                    result_parts.append(f"  ... and {len(status['modified']) - 50} more")

                result_parts.append("")
                result_parts.append(f"Deleted ({len(status['deleted'])}):")
                for f in status["deleted"][:50]:
                    result_parts.append(f"  - {f}")
                if len(status["deleted"]) > 50:
                    result_parts.append(f"  ... and {len(status['deleted']) - 50} more")

                result_parts.append("")
                result_parts.append(f"Unchanged ({len(status['unchanged'])} files)")

            content = "\n".join(result_parts)

        elif view_type == "diff":
            diffs = git_manager.get_diff(path_filter=path, max_diff_lines=max_diff_lines)

            if not diffs:
                content = "No differences found between working tree and last commit."
            else:
                result_parts = []
                result_parts.append(f"Showing {len(diffs)} changed file(s):")
                if path:
                    result_parts.append(f"(filtered to files containing '{path}')")
                if max_diff_lines:
                    result_parts.append(f"(diffs truncated to {max_diff_lines} lines each)")
                result_parts.append("")

                for d in diffs:
                    change_symbol = {"added": "+", "modified": "~", "deleted": "-"}.get(d["change_type"], "?")
                    result_parts.append(f"{'='*60}")
                    result_parts.append(f"{change_symbol} {d['change_type'].upper()}: {d['path']}")
                    result_parts.append(f"{'='*60}")
                    result_parts.append(d["content"])
                    result_parts.append("")

                content = "\n".join(result_parts)

        elif view_type == "log":
            commits = git_manager.get_log(max_count=max_count)

            if not commits:
                content = "No commits found."
            else:
                result_parts = []
                result_parts.append(f"Last {len(commits)} commit(s):")
                result_parts.append("")
                for c in commits:
                    short_id = c["commit_id"][:8]
                    result_parts.append(f"  commit {short_id}")
                    result_parts.append(f"  Author: {c['author']}")
                    result_parts.append(f"  Date:   {c['timestamp']}")
                    result_parts.append("")
                    result_parts.append(f"      {c['message']}")
                    result_parts.append("")
                content = "\n".join(result_parts)

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": content,
        }

    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error executing ViewChanges: {str(e)}",
        }
