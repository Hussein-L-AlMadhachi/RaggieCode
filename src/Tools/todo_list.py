from .utils import BLUE, RESET, GREEN, YELLOW, RED, GRAY


def _authorize_list(todo_list_id, parent_session_id):
    """Validate that a todo list exists and belongs to the calling (root) session.

    Returns (todo_list_dict, None) on success, or (None, error_message) on failure.
    """
    if parent_session_id is None:
        return None, "Error: parent_session_id is required"

    from Agent.chat_history_db import get_todo_list, resolve_todo_session_id

    todo_list = get_todo_list(todo_list_id)
    if not todo_list:
        return None, f"Error: Todo list {todo_list_id} not found"

    if todo_list['session_id'] != resolve_todo_session_id(parent_session_id):
        return None, f"Error: Todo list {todo_list_id} does not belong to this chat"

    return todo_list, None


def handle_create_todo_list(arguments, toolcall_id, parent_session_id=None):
    """Create a new todo list for the current session."""
    from Agent.chat_history_db import create_todo_list, get_session_thinking_mode, get_session_depth, resolve_todo_session_id
    from Agent.thinking_modes import is_depth_allowed, thinking_mode_name, thinking_mode_max_depth
    
    if parent_session_id is None:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: parent_session_id is required to create a todo list",
        }
    
    # When globalTodo is enabled, resolve to the root session so all subagents share one todo list
    todo_session_id = resolve_todo_session_id(parent_session_id)
    
    thinking_mode = get_session_thinking_mode(parent_session_id)
    depth = get_session_depth(parent_session_id)
    if thinking_mode is not None and not is_depth_allowed(thinking_mode, depth):
        max_d = thinking_mode_max_depth(thinking_mode)
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Cannot create todo list: thinking mode '{thinking_mode_name(thinking_mode)}' limits todo list depth to {max_d}. Current session depth is {depth}. Handle the task directly without a todo list.",
        }
    
    try:
        todo_list_id = create_todo_list(todo_session_id)
        print(f"{BLUE}Created todo list {todo_list_id} for session {todo_session_id}{RESET}")
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Created todo list with ID: {todo_list_id}",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to create todo list: {str(e)}",
        }


def handle_add_task(arguments, toolcall_id, parent_session_id=None):
    """Add a task to a todo list."""
    from Agent.chat_history_db import add_todo_task, get_todo_tasks, update_todo_list_status

    todo_list_id = arguments.get("todo_list_id")
    goal = arguments.get("goal")
    requirements = arguments.get("requirements")
    notes = arguments.get("notes")
    context = arguments.get("context")
    insert_after = arguments.get("insert_after")

    if not todo_list_id or not goal:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'todo_list_id' and 'goal' are required parameters",
        }

    todo_list, auth_error = _authorize_list(todo_list_id, parent_session_id)
    if auth_error:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": auth_error,
        }

    try:
        # If the list was already approved, adding tasks invalidates the approval:
        # reset to pending so the updated plan must be re-approved before execution.
        list_reset = ""
        if todo_list['status'] == 'approved':
            update_todo_list_status(todo_list_id, 'pending')
            list_reset = (" The todo list was reset to 'pending' and must be re-approved "
                          "(ApproveTodoList) before execution.")
            print(f"{YELLOW}Todo list {todo_list_id} reset to pending after AddTask; re-approval required.{RESET}")

        # Clamp insert_after so new work cannot be scheduled ahead of executed
        # (completed/in_progress/failed/cancelled) tasks, which would renumber
        # an approved or already-started plan.
        clamp_note = ""
        if insert_after is not None:
            tasks = sorted(get_todo_tasks(todo_list_id), key=lambda t: t['order_index'])
            frontier_display = None
            for position, task in enumerate(tasks):
                if task['status'] != 'pending':
                    frontier_display = position + 1
            if frontier_display is not None and insert_after < frontier_display:
                insert_after = frontier_display
                clamp_note = f" (insert position adjusted to {frontier_display} so the new task is scheduled after already-started work)"

        task_id = add_todo_task(todo_list_id, goal, requirements, notes,
                                context=context, insert_after=insert_after)
        print(f"{BLUE}Added task {task_id} to todo list {todo_list_id}: {goal[:50]}...{RESET}")
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Added task with ID: {task_id}{clamp_note}.{list_reset}",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to add task: {str(e)}",
        }


def handle_get_todo_list(arguments, toolcall_id, parent_session_id=None):
    """Get and display a todo list with all its tasks."""
    from Agent.chat_history_db import get_todo_tasks

    todo_list_id = arguments.get("todo_list_id")

    if not todo_list_id:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'todo_list_id' is required",
        }

    todo_list, auth_error = _authorize_list(todo_list_id, parent_session_id)
    if auth_error:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": auth_error,
        }

    try:
        tasks = get_todo_tasks(todo_list_id)

        header = f"Todo List {todo_list_id} (Status: {todo_list['status']})"
        separator = "=" * 60

        # Plain-text tool content (no ANSI color codes)
        content_lines = [header, separator]
        for task in tasks:
            content_lines.append(f"[{task['status']}] {task['order_index'] + 1}. {task['goal']}")
            if task['requirements']:
                content_lines.append(f"   Requirements: {task['requirements']}")
            if task['notes']:
                content_lines.append(f"   Notes: {task['notes']}")
            if task['context']:
                content_lines.append(f"   Context: {task['context']}")
            if task.get('cancel_reason'):
                content_lines.append(f"   Cancel reason: {task['cancel_reason']}")
            content_lines.append("")
        content_lines.append(separator)

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "\n".join(content_lines),
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to get todo list: {str(e)}",
        }


def handle_approve_todo_list(arguments, toolcall_id, parent_session_id=None):
    """Approve a todo list and mark it as ready for execution."""
    from Agent.chat_history_db import update_todo_list_status, delete_todo_list
    import io_backend
    
    todo_list_id = arguments.get("todo_list_id")
    
    if not todo_list_id:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'todo_list_id' is required",
        }
    
    todo_list, auth_error = _authorize_list(todo_list_id, parent_session_id)
    if auth_error:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": auth_error,
        }
    
    try:
        # Display the todo list first
        from Agent.chat_history_db import get_todo_tasks
        tasks = get_todo_tasks(todo_list_id)
        
        print(f"\n{BLUE}Todo List {todo_list_id} - Execution Plan{RESET}")
        print("=" * 60)
        for task in tasks:
            print(f"{YELLOW}{task['order_index'] + 1}.{RESET} {task['goal']}")
            if task['requirements']:
                print(f"   Requirements: {task['requirements']}")
            if task['notes']:
                print(f"   Notes: {task['notes']}")
            if task['context']:
                print(f"{GRAY}   Context: {task['context']}{RESET}")
        print("=" * 60)
        
        # Ask for user approval   io_backend.confirm enforces strict y/n validation
        # and routes through the ACP permission handler in headless mode.
        approved = io_backend.confirm("Do you want me to carry on with this plan?")

        if approved:
            update_todo_list_status(todo_list_id, 'approved')
            print(f"{GREEN}Todo list approved. Starting execution...{RESET}")
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "Todo list approved and ready for execution",
            }
        else:
            # Ask for feedback
            feedback = io_backend.ask("Please elaborate on what should be changed: ").strip()
            # Rejected plans are dead   delete the list entirely. The agent
            # rebuilds a fresh list from the feedback (kept in the tool result).
            delete_todo_list(todo_list_id)
            print(f"{RED}Todo list rejected and discarded. Feedback: {feedback}{RESET}")
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Todo list rejected and discarded. Build a new plan incorporating this user feedback: {feedback}",
            }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to approve todo list: {str(e)}",
        }


def handle_execute_next_task(arguments, toolcall_id, parent_session_id=None, cancel_check=None):
    """Execute the next pending task in the todo list by dispatching a subagent.

    If a task is already in_progress (from a crashed previous attempt),
    it is resumed using the original toolcall_id so dispatch_subagent
    can find and resume the existing child session.
    """
    from Agent.chat_history_db import get_next_pending_task, update_task_status, get_todo_tasks, delete_todo_list, get_all_session_files_chain, set_task_toolcall_id
    from Tools.dispatch_subagent import handle as dispatch_handle
    
    todo_list_id = arguments.get("todo_list_id")
    
    if not todo_list_id:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'todo_list_id' is required",
        }
    
    # Depth enforcement happens inside dispatch_subagent.handle (single
    # source of truth): an over-limit session gets a dispatch refusal there,
    # which the failure detection below marks as a failed task.

    try:
        # Validate ownership and existence before executing any task
        todo_list, auth_error = _authorize_list(todo_list_id, parent_session_id)
        if auth_error:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": auth_error,
            }
        
        if todo_list['status'] != 'approved':
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Error: Cannot execute tasks. Todo list {todo_list_id} has not been approved by the user. Current status: {todo_list['status']}. Please call ApproveTodoList first.",
            }
        
        # Get the next task   in_progress tasks are returned first (crash recovery)
        task = get_next_pending_task(todo_list_id)
        
        if not task:
            # No more pending tasks   report exhaustion. The list is only removed
            # when there are no failed tasks left; failed tasks keep the list
            # alive so the agent can retry, mark, or cancel them.
            all_tasks = get_todo_tasks(todo_list_id)
            failed_tasks = [t for t in all_tasks if t['status'] == 'failed']
            cancelled_tasks = [t for t in all_tasks if t['status'] == 'cancelled']
            completed_tasks = [t for t in all_tasks if t['status'] == 'completed']
            pending_or_running = [t for t in all_tasks if t['status'] in ('pending', 'in_progress')]

            if failed_tasks:
                lines = [
                    f"Todo list {todo_list_id} has {len(failed_tasks)} failed task(s). "
                    "The list was kept so you can retry them (re-dispatch), mark them, or cancel them:"
                ]
                for ft in failed_tasks:
                    lines.append(f"  - [FAILED] {ft['order_index'] + 1}. {ft['goal']}")
                summary = (f"Completed: {len(completed_tasks)}, "
                           f"Cancelled: {len(cancelled_tasks)}, Failed: {len(failed_tasks)}")
                if pending_or_running:
                    summary += f", Still pending/in progress: {len(pending_or_running)}"
                lines.append(summary)
                print(f"{RED}Todo list {todo_list_id} has {len(failed_tasks)} failed task(s); list kept for retry.{RESET}")
                return {
                    "role": "tool",
                    "tool_call_id": toolcall_id,
                    "content": "\n".join(lines),
                }

            delete_todo_list(todo_list_id)
            done_summary = f"All tasks completed ({len(completed_tasks)} done"
            if cancelled_tasks:
                done_summary += f", {len(cancelled_tasks)} cancelled"
                for ct in cancelled_tasks:
                    done_summary += f"\n  - [CANCELLED] {ct['order_index'] + 1}. {ct['goal']}"
            done_summary += f"). Todo list {todo_list_id} has been removed."
            print(f"{GREEN}All tasks completed! Todo list {todo_list_id} is done and has been removed.{RESET}")
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": done_summary,
            }
        
        is_resume = task['status'] == 'in_progress'
        
        if is_resume:
            # Crash recovery: resume the existing subagent session using the original toolcall_id
            print(f"{BLUE}Resuming task {task['order_index'] + 1}: {task['goal']}{RESET}")
            dispatch_toolcall_id = task.get('toolcall_id') or toolcall_id
        else:
            # New task: mark as in_progress and store the toolcall_id for future recovery
            update_task_status(task['id'], 'in_progress')
            set_task_toolcall_id(task['id'], toolcall_id)
            print(f"{BLUE}Executing task {task['order_index'] + 1}: {task['goal']}{RESET}")
            dispatch_toolcall_id = toolcall_id
        
        # Get all tasks to build context of completed/cancelled tasks
        all_tasks = get_todo_tasks(todo_list_id)
        completed_tasks = [t for t in all_tasks if t['status'] == 'completed']
        cancelled_tasks = [t for t in all_tasks if t['status'] == 'cancelled']
        
        # Build prompt for subagent
        prompt_parts = [f"Goal: {task['goal']}"]
        if task['requirements']:
            prompt_parts.append(f"Requirements: {task['requirements']}")
        if task['notes']:
            prompt_parts.append(f"Notes: {task['notes']}")
        if task['context']:
            prompt_parts.append(f"Context: {task['context']}")
        
        # Add context from previously completed tasks
        if completed_tasks:
            prompt_parts.append("\nPreviously completed tasks in this todo list:")
            for ct in completed_tasks:
                prompt_parts.append(f"  - [COMPLETED] {ct['order_index'] + 1}. {ct['goal']}")
                if ct['requirements']:
                    prompt_parts.append(f"    Requirements: {ct['requirements']}")
        
        # Add context from cancelled tasks
        if cancelled_tasks:
            prompt_parts.append("\nCancelled tasks in this todo list:")
            for ct in cancelled_tasks:
                prompt_parts.append(f"  - [CANCELLED] {ct['order_index'] + 1}. {ct['goal']}")
                if ct['notes']:
                    prompt_parts.append(f"    Notes: {ct['notes']}")
        
        subagent_prompt = "\n".join(prompt_parts)
        
        # Dispatch subagent (use original toolcall_id for resume so the child session is found)
        dispatch_args = {
            "prompt": subagent_prompt
        }
        
        result = dispatch_handle(dispatch_args, dispatch_toolcall_id, parent_session_id, cancel_check=cancel_check)

        # Structural failure detection: dispatch returns dispatch_error=True on
        # genuine subagent failures (collected error events, dispatch exceptions).
        # Validation-only failures (dicts without dispatch_error, content starting
        # with 'Error:') also count as failures since the dispatch never started.
        dispatch_failed = result.get('dispatch_error', False)
        if not dispatch_failed and result.get('content', '').startswith('Error'):
            dispatch_failed = True

        # Mark task as completed only if the subagent genuinely succeeded
        if result.get('role') == 'tool' and not dispatch_failed:
            update_task_status(task['id'], 'completed')
            if is_resume:
                print(f"{GREEN}Task {task['order_index'] + 1} resumed and completed{RESET}")
            else:
                print(f"{GREEN}Task {task['order_index'] + 1} completed{RESET}")
        else:
            update_task_status(task['id'], 'failed')
            print(f"{RED}Task {task['order_index'] + 1} failed{RESET}")

        # Pop internal keys so they don't leak into chat history
        result.pop('dispatch_error', None)

        # Append list of files modified during the subagent session
        subagent_session_id = result.pop('subagent_session_id', None)
        if subagent_session_id is not None:
            session_files = get_all_session_files_chain(subagent_session_id)
            if session_files:
                files_summary = "\n\nFiles modified in this task session:"
                for sf in session_files:
                    files_summary += f"\n  - [{sf['operation']}] {sf['file_path']}"
                result['content'] = result['content'] + files_summary
        
        return result
        
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to execute task: {str(e)}",
        }


def handle_mark_task_complete(arguments, toolcall_id, parent_session_id=None):
    """Manually mark a task as completed."""
    from Agent.chat_history_db import update_task_status, get_todo_task, get_todo_tasks, delete_todo_list

    task_id = arguments.get("task_id")
    todo_list_id = arguments.get("todo_list_id")

    if not task_id:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'task_id' is required",
        }

    task = get_todo_task(task_id)
    if task is None:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error: Task {task_id} not found",
        }

    _, auth_error = _authorize_list(task['todo_list_id'], parent_session_id)
    if auth_error:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": auth_error,
        }

    if todo_list_id and todo_list_id != task['todo_list_id']:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error: Task {task_id} does not belong to todo list {todo_list_id}",
        }

    try:
        update_task_status(task_id, 'completed')
        print(f"{GREEN}Task {task_id} marked as completed{RESET}")

        # The list is done only when no tasks remain pending, in_progress, or failed.
        tasks = get_todo_tasks(task['todo_list_id'])
        failed_tasks = [t for t in tasks if t['status'] == 'failed']
        cancelled_tasks = [t for t in tasks if t['status'] == 'cancelled']
        remaining = [t for t in tasks if t['status'] in ('pending', 'in_progress', 'failed')]

        if not remaining:
            delete_todo_list(task['todo_list_id'])
            print(f"{GREEN}All tasks completed! Todo list {task['todo_list_id']} has been removed.{RESET}")
            done_content = f"Task {task_id} marked as completed. All tasks done -- todo list has been removed."
            if cancelled_tasks:
                done_content += f" ({len(cancelled_tasks)} task(s) had been cancelled.)"
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": done_content,
            }

        completion_note = f"Task {task_id} marked as completed"
        if failed_tasks:
            completion_note += (f". Note: {len(failed_tasks)} task(s) in the list remain failed; "
                                "the todo list is kept so they can be retried.")
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": completion_note,
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to mark task as completed: {str(e)}",
        }


def handle_mark_task_failed(arguments, toolcall_id, parent_session_id=None):
    """Manually mark a task as failed."""
    from Agent.chat_history_db import update_task_status, get_todo_task
    
    task_id = arguments.get("task_id")
    
    if not task_id:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'task_id' is required",
        }
    
    task = get_todo_task(task_id)
    if task is None:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error: Task {task_id} not found",
        }
    
    _, auth_error = _authorize_list(task['todo_list_id'], parent_session_id)
    if auth_error:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": auth_error,
        }
    
    try:
        update_task_status(task_id, 'failed')
        print(f"{RED}Task {task_id} marked as failed{RESET}")
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Task {task_id} marked as failed",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to mark task as failed: {str(e)}",
        }


def handle_mark_task_cancelled(arguments, toolcall_id, parent_session_id=None):
    """Manually mark a task as cancelled. A reason is required."""
    from Agent.chat_history_db import update_task_status, get_todo_task

    task_id = arguments.get("task_id")
    reason = arguments.get("reason")

    if not task_id:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'task_id' is required",
        }

    if not reason or not reason.strip():
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'reason' is required when cancelling a task. Provide a brief explanation of why this task is being cancelled.",
        }

    task = get_todo_task(task_id)
    if task is None:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error: Task {task_id} not found",
        }

    _, auth_error = _authorize_list(task['todo_list_id'], parent_session_id)
    if auth_error:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": auth_error,
        }

    try:
        update_task_status(task_id, 'cancelled', cancel_reason=reason.strip())
        print(f"{YELLOW}Task {task_id} marked as cancelled. Reason: {reason.strip()}{RESET}")
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Task {task_id} marked as cancelled. Reason: {reason.strip()}",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to mark task as cancelled: {str(e)}",
        }


def handle_get_active_todo_list(arguments, toolcall_id, parent_session_id=None):
    """Get the active todo list for the current session."""
    from Agent.chat_history_db import get_active_todo_list, resolve_todo_session_id

    if parent_session_id is None:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: parent_session_id is required",
        }

    todo_session_id = resolve_todo_session_id(parent_session_id)

    try:
        todo_list = get_active_todo_list(todo_session_id)
        if todo_list:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Active todo list ID: {todo_list['id']}, Status: {todo_list['status']}",
            }
        else:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "No active todo list found for this chat",
            }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to get active todo list: {str(e)}",
        }
