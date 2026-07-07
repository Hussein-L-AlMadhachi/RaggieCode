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
        from Agent.chat_history_db import create_chat, get_or_create_session, get_changes_by_session, get_session_role
        from Agent.agent import Agent
        from Tools import setup_toolcalls
        from Commands import setup_commands
        
        print(f"{BLUE}Dispatching subagent with role '{role}'{RESET}")
        
        # Create a new chat for the subagent
        subagent_chat_id = create_chat(role)
        
        # Create session with parent link if parent_session_id is provided
        subagent_session_id = get_or_create_session(subagent_chat_id, parent_session_id=parent_session_id)
        
        # Create and run the subagent
        subagent = Agent(role=role, chat_id=subagent_chat_id, session_id=subagent_session_id)
        
        # Register tools and commands for the subagent
        setup_toolcalls(subagent.tool_registry)
        setup_commands(subagent.command_registry)
        
        # Collect output
        output_parts = []
        error_occurred = False
        
        try:
            for event_type, *event_data in subagent.start(prompt=prompt):
                if event_type == "response":
                    output_parts.append(event_data[0])
                elif event_type == "response_end":
                    output_parts.append(event_data[0])
                elif event_type == "error":
                    output_parts.append(f"Error: {event_data[0]}")
                    error_occurred = True
                    break
                # tool_call, response_chunk, reasoning, reasoning_chunk are
                # informational — tool execution happens internally in the agent
        except Exception as e:
            output_parts.append(f"Subagent execution failed: {str(e)}")
            error_occurred = True
        
        output = "\n".join(output_parts) if output_parts else "No output from subagent"
        
        if error_occurred:
            output = f"Subagent encountered errors:\n{output}"

        # Append changes recorded by the subagent
        changes = get_changes_by_session(subagent_session_id)
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
            "subagent_session_id": subagent_session_id,
        }

    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to dispatch subagent: {str(e)}",
        }
