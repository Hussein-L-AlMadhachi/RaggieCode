import os
import re
from .utils import is_ignored_by_gitignore, is_within_cwd, BLUE, RESET, auto_record_change, reindex_after_change, remove_em_dashes


def handle(arguments, toolcall_id, session_id=None, code_indexer=None):
    file_path = arguments.get("file_path")
    old_string = arguments.get("old_string")
    new_string = arguments.get("new_string")
    if new_string:
        new_string = remove_em_dashes(new_string)
    replace_all = arguments.get("replace_all", False)
    use_regex = arguments.get("use_regex", False)  # Explicit mode flag

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

        with open(file_path, "r") as f:
            content = f.read()

        # Gather matches as a unified list of tuples:
        # (start_idx, end_idx, matched_substring, resolved_replacement)
        match_data = []

        if use_regex:
            try:
                pattern = re.compile(old_string)
            except re.error as e:
                return {
                    "role": "tool",
                    "tool_call_id": toolcall_id,
                    "content": f"Error: Invalid regular expression: {e}",
                }

            for m in pattern.finditer(content):
                start, end = m.span()
                try:
                    repl = m.expand(new_string)
                except re.error as e:
                    return {
                        "role": "tool",
                        "tool_call_id": toolcall_id,
                        "content": f"Error expanding regex replacement group: {e}",
                    }
                match_data.append((start, end, content[start:end], repl))
        else:
            # Pure literal mode — bypass the 're' module entirely
            start_idx = 0
            sub_len = len(old_string)
            while True:
                idx = content.find(old_string, start_idx)
                if idx == -1:
                    break
                match_data.append((idx, idx + sub_len, old_string, new_string))
                start_idx = idx + sub_len

        count = len(match_data)

        if count == 0:
            err_msg = "Error: Pattern not found in file."
            # Smart LLM recovery hint for literal mode
            if not use_regex:
                stripped = old_string.strip()
                if stripped and content.find(stripped) != -1:
                    err_msg += (
                        " However, a trimmed version of your string WAS found. "
                        "Check your exact leading/trailing whitespace and indentation."
                    )
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

        # Build result view: show new file content with 6 lines context around each change
        CONTEXT = 6
        new_lines_all = new_content.split("\n")
        result_blocks = []
        line_offset = 0

        for start, end, matched_text, replacement in match_data:
            start_line = content[:start].count("\n")
            matched_line_count = matched_text.count("\n") + 1
            replacement_line_count = replacement.count("\n") + 1

            new_start = start_line + line_offset
            new_end = new_start + replacement_line_count

            ctx_start = max(0, new_start - CONTEXT)
            ctx_after = min(len(new_lines_all), new_end + CONTEXT)

            block = [
                f"@@ {file_path}:{new_start+1}-{new_end} @@",
            ]

            for i in range(ctx_start, new_start):
                block.append(f"    {new_lines_all[i]}")

            for i in range(new_start, new_end):
                block.append(f"  > {new_lines_all[i]}")

            for i in range(new_end, ctx_after):
                block.append(f"    {new_lines_all[i]}")

            result_blocks.append("\n".join(block))
            line_offset += replacement_line_count - matched_line_count

        with open(file_path, "w") as f:
            f.write(new_content)

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