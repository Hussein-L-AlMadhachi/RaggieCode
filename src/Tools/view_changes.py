import os
from Agent.git_manager import GitManager
from .utils import BLUE, RESET

# Hard cap on characters emitted per diff call. Even one page can exceed safe
# output size if a single diff is enormous (e.g. a minified bundle).
MAX_OUTPUT_CHARS = 60000


def handle(arguments, toolcall_id):
    """Handle ViewChanges tool calls."""
    print(f"{BLUE}ViewChanges{RESET}")

    view_type = arguments.get("view_type", "status")
    path = arguments.get("path")
    max_count = arguments.get("max_count", 10)
    category = arguments.get("category")
    max_diff_lines = arguments.get("max_diff_lines", 500)
    page = arguments.get("page", 1)
    files_per_page = arguments.get("files_per_page", 25)

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

    # Validate page and files_per_page (diff pagination)
    for name, value, minimum in (("page", page, 1), ("files_per_page", files_per_page, 1)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Invalid {name}: must be a number, got {type(value).__name__}.",
            }
        if int(value) != value or value < minimum:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Invalid {name}: must be an integer >= {minimum}, got {value}.",
            }
    page = int(page)
    files_per_page = int(files_per_page)

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
                total_files = len(diffs)
                # Pagination: diffs are shown files_per_page at a time so a
                # huge change set (e.g. 1000+ files) can never overflow the
                # model's context window in a single tool result.
                total_pages = (total_files + files_per_page - 1) // files_per_page
                if page > total_pages:
                    content = (
                        f"page {page} is out of range: {total_files} changed file(s) "
                        f"span {total_pages} page(s) at {files_per_page} files per page. "
                        f"Request page 1 to {total_pages}."
                    )
                else:
                    start = (page - 1) * files_per_page
                    end = start + files_per_page
                    page_diffs = diffs[start:end]

                    result_parts = []
                    result_parts.append(
                        f"Showing {len(page_diffs)} of {total_files} changed file(s) "
                        f"(files {start + 1}-{start + len(page_diffs)}, "
                        f"page {page} of {total_pages}):"
                    )
                    if path:
                        result_parts.append(f"(filtered to files containing '{path}')")
                    if max_diff_lines:
                        result_parts.append(f"(diffs truncated to {max_diff_lines} lines each)")
                    if total_pages > 1 and page < total_pages:
                        result_parts.append(
                            f"(more pages available   call again with page={page + 1})"
                        )
                    result_parts.append("")

                    # Backstop: cap the total characters emitted per call.
                    total_chars = 0
                    emitted = 0
                    truncated = False
                    for d in page_diffs:
                        change_symbol = {"added": "+", "modified": "~", "deleted": "-"}.get(d["change_type"], "?")
                        block = "\n".join([
                            f"{'='*60}",
                            f"{change_symbol} {d['change_type'].upper()}: {d['path']}",
                            f"{'='*60}",
                            d["content"],
                            "",
                        ])
                        if emitted and total_chars + len(block) > MAX_OUTPUT_CHARS:
                            # Keep at least one file: only stop once something
                            # has already been emitted.
                            truncated = True
                            break
                        result_parts.append(block)
                        total_chars += len(block)
                        emitted += 1
                    if truncated:
                        result_parts.append(
                            f"[output truncated at ~{MAX_OUTPUT_CHARS // 1000}k characters   "
                            f"narrow the filter with 'path' or reduce 'files_per_page' "
                            f"(currently {files_per_page})]"
                        )

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
