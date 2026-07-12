import os

from RAG.find import find_symbol_location
from .utils import is_ignored_by_gitignore, is_within_cwd, BLUE, RESET, auto_record_change, reindex_after_change


def handle(arguments, toolcall_id, session_id=None, code_indexer=None):
    symbol_name = arguments["symbol_name"]
    file_path = arguments.get("file_path")
    new_source = arguments.get("new_source")

    print(f"{BLUE}EditSymbol {symbol_name}{RESET}")

    if not new_source:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'new_source' cannot be empty.",
        }

    try:
        loc = find_symbol_location(symbol_name, file_path)
        if loc is None:
            hint = ""
            if file_path:
                hint = f" in file '{file_path}'"
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": (
                    f"Error: Symbol '{symbol_name}' not found in code index{hint}. "
                    "Make sure the code index is up to date and the symbol name is correct."
                ),
            }

        resolved_path = loc["file_path"]
        start_line = loc["start_line"]
        end_line = loc["end_line"]
        old_source = loc["source"]

        # Security checks
        if not is_within_cwd(resolved_path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "Error: access denied - path is outside the current working directory",
            }

        if is_ignored_by_gitignore(resolved_path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": (
                    f"Error: File '{resolved_path}' is in .gitignore. "
                    "Operations on gitignored files are not allowed."
                ),
            }

        if not os.path.exists(resolved_path):
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Error: File '{resolved_path}' does not exist.",
            }

        with open(resolved_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")

        # Replace lines [start_line-1 : end_line] (1-indexed inclusive → 0-indexed slice)
        old_lines = lines[start_line - 1:end_line]
        new_lines = new_source.split("\n")

        new_file_lines = lines[:start_line - 1] + new_lines + lines[end_line:]
        new_content = "\n".join(new_file_lines)

        with open(resolved_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        # Build diff view
        CONTEXT = 5
        ctx_start = max(0, start_line - 1 - CONTEXT)
        ctx_end = min(len(lines), end_line + CONTEXT)

        diff_lines = [
            f"@@ {resolved_path}:{start_line}-{end_line} ({len(old_lines)} lines "
            f"-> {len(new_lines)} lines) @@",
        ]

        for i in range(ctx_start, start_line - 1):
            diff_lines.append(f"    {lines[i]}")

        for line in old_lines:
            diff_lines.append(f"  - {line}")

        for line in new_lines:
            diff_lines.append(f"  + {line}")

        for i in range(end_line, ctx_end):
            diff_lines.append(f"    {lines[i]}")

        diff_text = "\n".join(diff_lines)

        if session_id is not None:
            from Agent.chat_history_db import record_session_file
            record_session_file(session_id, resolved_path, "edit_symbol")
            auto_record_change(
                session_id, resolved_path, "file_edit",
                f"Edited symbol '{symbol_name}' in {resolved_path}: replaced lines {start_line}-{end_line}",
                diff_text,
            )

        reindex_after_change(code_indexer)

        summary = (
            f"Replaced {loc['kind']} '{symbol_name}' in {resolved_path} "
            f"(lines {start_line}-{end_line} -> {len(new_lines)} lines):\n\n"
            f"{diff_text}"
        )

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": summary,
        }

    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error executing edit_symbol: {str(e)}",
        }
