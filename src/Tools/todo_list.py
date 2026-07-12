from .utils import BLUE, RESET, GREEN, YELLOW, RED, GRAY


def handle_create_todo_list(arguments, toolcall_id, parent_session_id=None):
    """Create a new todo list for the current session."""
    from Agent.chat_history_db import create_todo_list, get_session_effort, get_session_depth, resolve_todo_session_id
    from Agent.effort_levels import is_depth_allowed, effort_name, effort_max_depth
    
    if parent_session_id is None:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: parent_session_id is required to create a todo list",
        }
    
    # When globalTodo is enabled, resolve to the root session so all subagents share one todo list
    todo_session_id = resolve_todo_session_id(parent_session_id)
    
    effort = get_session_effort(parent_session_id)
    depth = get_session_depth(parent_session_id)
    if effort is not None and not is_depth_allowed(effort, depth):
        max_d = effort_max_depth(effort)
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Cannot create todo list: effort level '{effort_name(effort)}' limits todo list depth to {max_d}. Current session depth is {depth}. Handle the task directly without a todo list.",
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
    from Agent.chat_history_db import add_todo_task

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

    try:
        task_id = add_todo_task(todo_list_id, goal, requirements, notes,
                                context=context, insert_after=insert_after)
        print(f"{BLUE}Added task {task_id} to todo list {todo_list_id}: {goal[:50]}...{RESET}")
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Added task with ID: {task_id}",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to add task: {str(e)}",
        }


def handle_get_todo_list(arguments, toolcall_id, parent_session_id=None):
    """Get and display a todo list with all its tasks."""
    from Agent.chat_history_db import get_todo_list, get_todo_tasks
    
    todo_list_id = arguments.get("todo_list_id")
    
    if not todo_list_id:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'todo_list_id' is required",
        }
    
    try:
        todo_list = get_todo_list(todo_list_id)
        if not todo_list:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Todo list {todo_list_id} not found",
            }
        
        tasks = get_todo_tasks(todo_list_id)
        
        output = f"\n{BLUE}Todo List {todo_list_id} (Status: {todo_list['status']}){RESET}\n"
        output += "=" * 60 + "\n"
        
        for task in tasks:
            status_color = GREEN if task['status'] == 'completed' else YELLOW if task['status'] == 'in_progress' else RESET
            output += f"{status_color}[{task['status']}] {YELLOW}{task['order_index'] + 1}.{RESET} {task['goal']}{RESET}\n"
            if task['requirements']:
                output += f"   Requirements: {task['requirements']}\n"
            if task['notes']:
                output += f"   Notes: {task['notes']}\n"
            if task['context']:
                output += f"{GRAY}   Context: {task['context']}\n{RESET}"
            if task.get('cancel_reason'):
                output += f"{YELLOW}   Cancel reason: {task['cancel_reason']}{RESET}\n"
            output += "\n"
        
        print(output)
        
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Retrieved todo list with {len(tasks)} tasks",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to get todo list: {str(e)}",
        }


def handle_approve_todo_list(arguments, toolcall_id, parent_session_id=None):
    """Approve a todo list and mark it as ready for execution."""
    from Agent.chat_history_db import update_todo_list_status
    from prompt_toolkit import prompt
    
    todo_list_id = arguments.get("todo_list_id")
    
    if not todo_list_id:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'todo_list_id' is required",
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
        
        # Ask for user approval
        user_input = prompt("Do you want me to carry on with this plan? (y/n): ").strip().lower()
        
        if user_input == 'y':
            update_todo_list_status(todo_list_id, 'approved')
            print(f"{GREEN}Todo list approved. Starting execution...{RESET}")
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "Todo list approved and ready for execution",
            }
        else:
            # Ask for feedback
            feedback = prompt("Please elaborate on what should be changed: ").strip()
            update_todo_list_status(todo_list_id, 'rejected')
            print(f"{RED}Todo list rejected. Feedback: {feedback}{RESET}")
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Todo list rejected. User feedback: {feedback}",
            }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to approve todo list: {str(e)}",
        }


def handle_execute_next_task(arguments, toolcall_id, parent_session_id=None):
    """Execute the next pending task in the todo list by dispatching a subagent.

    If a task is already in_progress (from a crashed previous attempt),
    it is resumed using the original toolcall_id so dispatch_subagent
    can find and resume the existing child session.
    """
    from Agent.chat_history_db import get_next_pending_task, update_task_status, get_todo_list, get_todo_tasks, delete_todo_list, get_all_session_files_chain, set_task_toolcall_id, get_session_effort, get_session_depth
    from Tools.dispatch_subagent import handle as dispatch_handle
    from Agent.effort_levels import is_depth_allowed, effort_name, effort_max_depth
    
    todo_list_id = arguments.get("todo_list_id")
    
    if not todo_list_id:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'todo_list_id' is required",
        }
    
    if parent_session_id is not None:
        effort = get_session_effort(parent_session_id)
        depth = get_session_depth(parent_session_id)
        if effort is not None and not is_depth_allowed(effort, depth):
            max_d = effort_max_depth(effort)
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Cannot execute todo list tasks: effort level '{effort_name(effort)}' limits todo list depth to {max_d}. Current session depth is {depth}. Handle remaining tasks directly without dispatching subagents.",
            }
    
    try:
        # Check if todo list is approved before executing any task
        todo_list = get_todo_list(todo_list_id)
        if not todo_list:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Error: Todo list {todo_list_id} not found",
            }
        
        if todo_list['status'] != 'approved':
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Error: Cannot execute tasks. Todo list {todo_list_id} has not been approved by the user. Current status: {todo_list['status']}. Please call ApproveTodoList first.",
            }
        
        # Get the next task — in_progress tasks are returned first (crash recovery)
        task = get_next_pending_task(todo_list_id)
        
        if not task:
            # No more pending tasks — delete the completed todo list
            delete_todo_list(todo_list_id)
            print(f"{GREEN}All tasks completed! Todo list {todo_list_id} is done and has been removed.{RESET}")
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "All tasks completed. Todo list has been removed.",
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
        
        result = dispatch_handle(dispatch_args, dispatch_toolcall_id, parent_session_id, skip_depth_check=True)
        
        # Mark task as completed if subagent succeeded
        if result.get('role') == 'tool' and not result.get('content', '').startswith('Error'):
            update_task_status(task['id'], 'completed')
            if is_resume:
                print(f"{GREEN}Task {task['order_index'] + 1} resumed and completed{RESET}")
            else:
                print(f"{GREEN}Task {task['order_index'] + 1} completed{RESET}")
        else:
            update_task_status(task['id'], 'failed')
            print(f"{RED}Task {task['order_index'] + 1} failed{RESET}")
        
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
    from Agent.chat_history_db import update_task_status, get_todo_tasks, delete_todo_list

    task_id = arguments.get("task_id")
    todo_list_id = arguments.get("todo_list_id")

    if not task_id:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'task_id' is required",
        }

    try:
        update_task_status(task_id, 'completed')
        print(f"{GREEN}Task {task_id} marked as completed{RESET}")

        # If we know the todo_list_id, check if all tasks are now done
        if todo_list_id:
            tasks = get_todo_tasks(todo_list_id)
            all_done = all(t['status'] == 'completed' for t in tasks)
            if all_done:
                delete_todo_list(todo_list_id)
                print(f"{GREEN}All tasks completed! Todo list {todo_list_id} has been removed.{RESET}")
                return {
                    "role": "tool",
                    "tool_call_id": toolcall_id,
                    "content": f"Task {task_id} marked as completed. All tasks done -- todo list has been removed.",
                }

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Task {task_id} marked as completed",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to mark task as completed: {str(e)}",
        }


def handle_mark_task_failed(arguments, toolcall_id, parent_session_id=None):
    """Manually mark a task as failed."""
    from Agent.chat_history_db import update_task_status
    
    task_id = arguments.get("task_id")
    
    if not task_id:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'task_id' is required",
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
    from Agent.chat_history_db import update_task_status

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
