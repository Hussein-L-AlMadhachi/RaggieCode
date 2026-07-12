from .utils import BLUE, RESET

# Safety limits
MAX_SUBAGENT_DEPTH = 3
DEFAULT_TIMEOUT = 300  # 5 minutes


def _get_session_depth(session_id: int) -> int:
    """Calculate the depth of a session in the subagent hierarchy by traversing parent_session_id."""
    import sqlite3
    from pathlib import Path
    
    DB_PATH = Path(".raggie/.raggie.chat")
    depth = 0
    current_id = session_id
    visited = set()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            cursor.execute("""
                SELECT parent_session_id FROM sessions WHERE id = ?
            """, (current_id,))
            result = cursor.fetchone()
            if result and result[0] is not None:
                current_id = result[0]
                depth += 1
            else:
                break
    finally:
        conn.close()
    
    return depth


def _collect_subagent_output(subagent, subagent_session_id, prompt=None, resume=False):
    """Run a subagent and collect its output. If resume=True, resume dangling work instead of starting fresh."""
    output_parts = []
    error_occurred = False

    try:
        if resume:
            events = subagent.resume_dangling_tool_work()
        else:
            events = subagent.start(prompt=prompt)

        if events is None:
            events = []

        for event_type, *event_data in events:
            if event_type == "response":
                output_parts.append(event_data[0])
            elif event_type == "response_end":
                output_parts.append(event_data[0])
            elif event_type == "error":
                output_parts.append(f"Error: {event_data[0]}")
                error_occurred = True
                break
    except Exception as e:
        output_parts.append(f"Subagent execution failed: {str(e)}")
        error_occurred = True

    output = "\n".join(output_parts) if output_parts else "No output from subagent"

    if error_occurred:
        output = f"Subagent encountered errors:\n{output}"

    from Agent.chat_history_db import get_all_changes_by_session_chain
    changes = get_all_changes_by_session_chain(subagent_session_id)
    if changes:
        changes_summary = "\n".join(
            f"  - [{c['change_type']}] {c['file_path'] or 'N/A'}: {c['description']}"
            for c in changes
        )
        output = f"{output}\n\n--- Changes made by subagent for you to review ---\n{changes_summary}"

    return output


def handle(arguments, toolcall_id, parent_session_id=None, skip_depth_check=False):
    prompt = arguments.get("prompt")
    timeout = arguments.get("timeout", DEFAULT_TIMEOUT)

    if not prompt:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'prompt' is a required parameter",
        }

    if parent_session_id is None:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: parent_session_id is required to determine the subagent role",
        }

    from Agent.chat_history_db import get_session_role
    role = get_session_role(parent_session_id)
    if not role:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error: Could not determine role for parent session {parent_session_id}",
        }

    # Check depth limit if parent_session_id is provided
    current_depth = 0
    if parent_session_id is not None and not skip_depth_check:
        current_depth = _get_session_depth(parent_session_id)
        print(f"{BLUE}Subagent depth: {current_depth}/{MAX_SUBAGENT_DEPTH}{RESET}")
        if current_depth >= MAX_SUBAGENT_DEPTH:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Error: Maximum subagent depth ({MAX_SUBAGENT_DEPTH}) reached. Current depth: {current_depth}",
            }

    try:
        from Agent.chat_history_db import (
            get_chat_id_for_session, create_session, get_child_session_by_toolcall,
            is_session_finished, load_messages,
            get_session_effort, get_session_depth,
            resolve_session_id,
        )
        from Agent.agent import Agent
        from Tools import setup_toolcalls
        from Commands import setup_commands

        chat_id = get_chat_id_for_session(parent_session_id)
        if chat_id is None:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Error: Could not find chat for parent session {parent_session_id}",
            }

        # Check for existing child session matching this toolcall_id (from a previous interrupted dispatch)
        child = get_child_session_by_toolcall(parent_session_id, toolcall_id)
        if child is not None:
            child_session_id = child["id"]
            # Follow redirect chain to find the active session (may have been handed over)
            active_session_id = resolve_session_id(child_session_id)
            if is_session_finished(child_session_id):
                # Subagent completed but main agent was interrupted before processing the result
                print(f"{BLUE}Found completed subagent session {active_session_id}, retrieving output...{RESET}")
                messages = load_messages(active_session_id)
                output_parts = []
                for msg in messages:
                    if msg.get("role") == "assistant" and not msg.get("tool_calls"):
                        output_parts.append(msg.get("content", ""))
                output = "\n".join(output_parts) if output_parts else "No output from subagent"

                from Agent.chat_history_db import get_all_changes_by_session_chain
                changes = get_all_changes_by_session_chain(active_session_id)
                if changes:
                    changes_summary = "\n".join(
                        f"  - [{c['change_type']}] {c['file_path'] or 'N/A'}: {c['description']}"
                        for c in changes
                    )
                    output = f"{output}\n\n--- Changes made by subagent for you to review ---\n{changes_summary}"

                return {
                    "role": "tool",
                    "tool_call_id": toolcall_id,
                    "content": output,
                    "subagent_session_id": active_session_id,
                }
            else:
                # Subagent was interrupted — resume it
                print(f"{BLUE}Resuming interrupted subagent session {active_session_id}...{RESET}")
                subagent = Agent(role=role, chat_id=chat_id, session_id=active_session_id)
                setup_toolcalls(subagent.tool_registry)
                setup_commands(subagent.command_registry)

                output = _collect_subagent_output(
                    subagent, active_session_id, resume=True
                )

                return {
                    "role": "tool",
                    "tool_call_id": toolcall_id,
                    "content": output,
                    "subagent_session_id": active_session_id,
                }

        # No existing child session — create a new one under the parent's chat
        print(f"{BLUE}Dispatching subagent with role '{role}'{RESET}")
        parent_effort = get_session_effort(parent_session_id)
        parent_depth = get_session_depth(parent_session_id)
        subagent_session_id = create_session(
            chat_id, parent_session_id=parent_session_id, toolcall_id=toolcall_id,
            effort=parent_effort, depth=parent_depth + 1,
        )

        subagent = Agent(role=role, chat_id=chat_id, session_id=subagent_session_id)
        setup_toolcalls(subagent.tool_registry)
        setup_commands(subagent.command_registry)

        output = _collect_subagent_output(
            subagent, subagent_session_id, prompt=prompt, resume=False
        )

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": output,
            "subagent_session_id": subagent_session_id,
        }

    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to dispatch subagent: {str(e)}",
        }
