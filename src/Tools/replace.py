import os
import re
from .utils import is_ignored_by_gitignore, is_within_cwd, BLUE, RESET, auto_record_change, reindex_after_change


def _fuzzy_find_literal(content, old_string):
    """Find old_string in content with whitespace-tolerant fallback.

    Returns (matches, warning) where matches is a list of (start, end, matched_text)
    and warning is None for exact matches or a string for fuzzy matches.
    """
    # 1. Exact match
    matches = []
    start_idx = 0
    sub_len = len(old_string)
    while True:
        idx = content.find(old_string, start_idx)
        if idx == -1:
            break
        matches.append((idx, idx + sub_len))
        start_idx = idx + sub_len
    if matches:
        return [(s, e, content[s:e]) for s, e in matches], None

    # 2. Stripped whole-string match (handles leading/trailing whitespace)
    stripped = old_string.strip()
    if stripped and stripped != old_string:
        start_idx = 0
        while True:
            idx = content.find(stripped, start_idx)
            if idx == -1:
                break
            matches.append((idx, idx + len(stripped)))
            start_idx = idx + len(stripped)
        if matches:
            return (
                [(s, e, content[s:e]) for s, e in matches],
                "Matched after stripping leading/trailing whitespace from old_string.",
            )

    # 3. Per-line stripped match (tolerates per-line indentation differences)
    old_lines_stripped = [line.strip() for line in old_string.split("\n")]
    if not all(old_lines_stripped):
        return [], None

    content_lines = content.split("\n")
    content_lines_stripped = [line.strip() for line in content_lines]

    n_old = len(old_lines_stripped)
    n_content = len(content_lines_stripped)

    # Precompute character offset of each line start in original content
    line_starts = [0]
    for line in content_lines[:-1]:
        line_starts.append(line_starts[-1] + len(line) + 1)

    for i in range(n_content - n_old + 1):
        if content_lines_stripped[i : i + n_old] == old_lines_stripped:
            first_line = content_lines[i]
            leading_ws = len(first_line) - len(first_line.lstrip())
            start = line_starts[i] + leading_ws

            last_line = content_lines[i + n_old - 1]
            last_line_end = line_starts[i + n_old - 1] + len(last_line)
            trailing_ws = len(last_line) - len(last_line.rstrip())
            end = last_line_end - trailing_ws

            matches.append((start, end))

    if matches:
        return (
            [(s, e, content[s:e]) for s, e in matches],
            "Matched with per-line whitespace normalization. Verify the result is correct.",
        )

    return [], None


def _find_closest_snippet(content, old_string, max_lines=10):
    """Find a region in content that resembles old_string for error reporting."""
    first_line = old_string.strip().split("\n")[0].strip()
    if not first_line or len(first_line) < 3:
        return None

    content_lines = content.split("\n")
    for i, line in enumerate(content_lines):
        if first_line in line.strip():
            start = max(0, i - 2)
            end = min(len(content_lines), i + max_lines)
            snippet_lines = []
            for j in range(start, end):
                marker = " >" if j == i else "  "
                snippet_lines.append(f"{marker} {j+1}: {content_lines[j]}")
            return (
                f"First line of old_string resembles file content at line {i+1}.\n"
                f"Actual file content:\n" + "\n".join(snippet_lines)
            )
    return None


def handle(arguments, toolcall_id, session_id=None, code_indexer=None):
    file_path = arguments.get("file_path")
    old_string = arguments.get("old_string")
    new_string = arguments.get("new_string")
    replace_all = arguments.get("replace_all", False)
    use_regex = arguments.get("use_regex", False)

    print(f"{BLUE}Replace {file_path}{RESET}")

    if not old_string:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'old_string' cannot be empty.",
        }

    try:
        # Check if the file is outside the current working directory
        if not is_within_cwd(file_path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "Error: access denied - path is outside the current working directory",
            }

        # Check if file is in .gitignore
        if is_ignored_by_gitignore(file_path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": (
                    f"Error: File '{file_path}' is in .gitignore. "
                    "Operations on gitignored files are not allowed."
                ),
            }

        if not os.path.exists(file_path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Error: File '{file_path}' does not exist.",
            }

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Gather matches as a unified list of tuples:
        # (start_idx, end_idx, matched_substring, resolved_replacement)
        match_data = []
        fuzzy_warning = None

        if use_regex:
            try:
                pattern = re.compile(old_string)
            except re.error as e:
                return {
                    "role": "tool",
                    "tool_call_id": toolcall_id,
                    "content": f"Error: Invalid regular expression: {e}",
                }

            # Collect all matches and validate expansions before applying any
            raw_matches = list(pattern.finditer(content))
            expanded = []
            for m in raw_matches:
                try:
                    repl = m.expand(new_string)
                except re.error as e:
                    return {
                        "role": "tool",
                        "tool_call_id": toolcall_id,
                        "content": f"Error expanding regex replacement group: {e}",
                    }
                expanded.append(repl)
            for m, repl in zip(raw_matches, expanded):
                match_data.append((m.start(), m.end(), content[m.start():m.end()], repl))
        else:
            # Literal mode with whitespace-tolerant fallback
            raw_matches, fuzzy_warning = _fuzzy_find_literal(content, old_string)
            for start, end, matched_text in raw_matches:
                match_data.append((start, end, matched_text, new_string))

        count = len(match_data)

        if count == 0:
            err_msg = "Error: Pattern not found in file."
            if not use_regex:
                snippet = _find_closest_snippet(content, old_string)
                if snippet:
                    err_msg += f"\n\n{snippet}"
                else:
                    err_msg += (
                        " Ensure indentation and line breaks match the file perfectly."
                    )

            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": err_msg,
            }

        if count > 1 and not replace_all:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": (
                    f"Error: Pattern is not unique in file (found {count} times). "
                    "Use replace_all=true to replace all occurrences, or provide "
                    "more context in old_string to narrow to a single match."
                ),
            }

        # Apply replacements in reverse order so string index spans stay valid
        new_content = content
        for start, end, _, replacement in reversed(match_data):
            new_content = new_content[:start] + replacement + new_content[end:]

        # Build diff view: show removed (-) and added (+) lines with context
        CONTEXT = 6
        old_lines_all = content.split("\n")
        new_lines_all = new_content.split("\n")
        result_blocks = []
        line_offset = 0

        for start, end, matched_text, replacement in match_data:
            start_line = content[:start].count("\n")
            matched_line_count = matched_text.count("\n") + 1
            replacement_line_count = replacement.count("\n") + 1

            old_start = start_line
            old_end = start_line + matched_line_count

            new_start = start_line + line_offset
            new_end = new_start + replacement_line_count

            ctx_start = max(0, new_start - CONTEXT)
            ctx_after = min(len(new_lines_all), new_end + CONTEXT)

            block = [
                f"@@ {file_path}:{new_start+1}-{new_end} @@",
            ]

            for i in range(ctx_start, new_start):
                block.append(f"    {new_lines_all[i]}")

            for i in range(old_start, old_end):
                block.append(f"  - {old_lines_all[i]}")

            for i in range(new_start, new_end):
                block.append(f"  + {new_lines_all[i]}")

            for i in range(new_end, ctx_after):
                block.append(f"    {new_lines_all[i]}")

            result_blocks.append("\n".join(block))
            line_offset += replacement_line_count - matched_line_count

        # Atomic write: temp file + os.replace
        tmp_path = file_path + ".raggie_tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.replace(tmp_path, file_path)
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Error: Failed to write file: {e}",
            }

        mode = "regex" if use_regex else "literal"
        replaced = count if replace_all else 1
        result_text = "\n\n".join(result_blocks)

        if session_id is not None:
            from Agent.chat_history_db import record_session_file
            record_session_file(session_id, file_path, "replace")
            auto_record_change(session_id, file_path, "file_edit", f"Edited {file_path}: replaced {replaced} occurrence(s)", result_text)

        summary = (
            f"Replaced {replaced} occurrence(s) in {file_path} ({mode} match):\n\n"
            f"{result_text}"
        )
        if fuzzy_warning:
            summary = f"Warning: {fuzzy_warning}\n\n" + summary

        reindex_after_change(code_indexer)

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": summary,
        }

    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error executing replace: {str(e)}",
        }