Always test any code you write after implementation is done

## Todo List Workflow

When handling complex tasks that require multiple steps, use the todo list system to plan and execute work sequentially:

1. **Create a todo list** using `CreateTodoList` tool
2. **Add tasks** to the todo list using `AddTask` tool with:
   - `goal`: Clear description of what needs to be done
   - `requirements`: Specific requirements or constraints
   - `notes`: Additional helpful context
   - `order_index`: Execution order (0, 1, 2, ...)
3. **Get the todo list** using `GetTodoList` to review the plan
4. **Approve the todo list** using `ApproveTodoList` - this will:
   - Display the plan to the user
   - Ask for user approval (y/n)
   - If rejected, collect user feedback and rebuild the plan
5. **Execute tasks sequentially** using `ExecuteNextTask`:
   - Each task dispatches a subagent to complete the work
   - Tasks are executed in order (no parallelization)
   - Continue until all tasks are completed

**Important:**
- Always get user approval before executing the action queue
- If user rejects the plan, incorporate their feedback and rebuild
- Tasks execute sequentially - never in parallel
- Use todo lists for complex multi-step tasks, not simple single-step work
- Todo lists are persisted per session and can be resumed if interrupted