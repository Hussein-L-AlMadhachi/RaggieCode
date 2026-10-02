# Planning and subagents

How Raggie handles work that is too big for one pass: thinking modes, todo lists, subagents, context handover and crash recovery.

## Thinking modes

A thinking mode sets how deep subagents may nest. Deeper nesting lets the agent break a task into more layers, at the cost of more model calls.

| Level | Name | Max depth | Use it for |
|---|---|---|---|
| 1 | **Zen** | 1 | The default. The main agent can dispatch subagents, they cannot dispatch their own |
| 2 | **Serious** | 2 | Subagents can delegate once more |
| 3 | **Extreme** | 4 | Complex multi-step work |
| 4 | **Feral** | 8 | Very large decompositions |
| 5 | **Insane** | 16 | The deepest bounded mode. Use with caution |

### Changing it

In a chat:

```
/thinkingMode 3
/thinkingMode extreme
/thinkingMode            # pick from a list
```

For a one-shot run:

```bash
raggie code . --prompt "Refactor everything" --effort 5
```

The mode is stored per chat. New chats start in Zen. `/unlimitedThinkingMode` removes the limit entirely for the current chat.

### How depth works

The main session is depth 0. Each dispatched subagent is one deeper than its parent and inherits the parent's thinking mode. A session whose depth has reached the mode's max depth cannot dispatch subagents or create todo lists, and is told to do the work directly.

## Subagents

`DispatchSubagent` starts a child agent with its own session and a fresh context window. The child:

- runs with the same role, tools and thinking mode as its parent
- starts from only the prompt the parent wrote, so it does not consume the parent's context
- runs to completion before the parent continues (subagents are sequential, never parallel)
- returns its final answer plus a list of the changes it made

Subagent work is not committed separately. The snapshot commit happens once, when the main agent finishes its turn.

In the terminal you see subagent tool calls with `--debug` or `/debug on`. The web UI streams subagent work live in a nested view.

## Todo lists

For multi-step tasks the agent writes a plan, gets your approval, then executes it one task at a time.

### Workflow

```
1. GetActiveTodoList   check for an unfinished list first
2. CreateTodoList      create a list
3. AddTask (x N)       add tasks: goal, requirements, notes, context
4. GetTodoList         review the plan
5. ApproveTodoList     show you the plan and ask y/n
6. ExecuteNextTask     run tasks one by one, each in a subagent
```

### Behavior

- **Approval is mandatory.** No task runs until you approve the list.
- **Rejection discards the list.** You are asked what should change, and the agent builds a new plan from your feedback.
- **Changing an approved plan needs re-approval.** Adding a task to an approved list resets it to pending. New tasks cannot be inserted ahead of work that already started.
- **One task, one subagent.** Each task runs in a fresh subagent that receives the task's goal, requirements, notes and context, plus a summary of completed and cancelled tasks. The subagent knows nothing else, which is why the `context` field matters.
- **Sequential.** Tasks run in order, never in parallel.
- **Status tracking.** Tasks are `pending`, `in_progress`, `completed`, `failed` or `cancelled`. The agent can set these by hand with `MarkTaskComplete`, `MarkTaskFailed` and `MarkTaskCancelled` (cancelling requires a reason).
- **Failed tasks keep the list alive** so they can be retried or cancelled. When nothing is pending, running or failed, the list is deleted.
- **Nested lists.** With `globalTodo` off, a subagent can create its own todo list for a complex task, within the thinking mode's depth.

### `globalTodo`

On by default. All subagents in a chat share the main session's todo list instead of each owning a private one. Toggle with `/globalTodo on|off`.

## Context handover

When the context window is nearly full, Raggie does not truncate. It hands the work over to a fresh session:

1. The agent is asked, without tools, for a handover document about the **current** task: the latest request verbatim, what has changed so far, the files and symbols involved, errors and failed attempts, and the exact next step.
2. A new session is created in the same chat, seeded with the system prompt and that document.
3. Any active todo list moves to the new session.
4. Work continues from the document.

When it triggers: remaining room below `min(90,000, context_window / 2)` tokens. The 90,000 figure leaves space for the provider's output-token reserve. Token usage comes from the API response, plus an estimate for tool results that were just added.

Only the main agent hands over. Subagents work within a single context window, so keep task scopes reasonable.

Old sessions stay in the chat history. In the terminal they are shown dimmed as "handed over, not in context".

If the handover request itself fails, the turn stops with an error instead of retrying an oversized request.

Tune it with `/windowSize <tokens>` (saved to `roles.json` as `context_window`).

## Crash recovery

A hard quit, a crash or a cancelled turn should never leave a chat unusable.

### Interrupted tool calls

Every message is saved as it happens. If the process dies after the model asked for tools but before they answered, those calls are left dangling. On the next start:

- **Terminal**: reopening the chat re-executes every unanswered tool call, then continues the turn. A user message that never got a reply is also continued.
- **Web UI**: the chat shows a resume action that does the same.

Subagent dispatches and todo tasks resume their **existing** child session instead of starting over. If the child had already finished, its stored output is returned directly.

### History repair

Before every API call the message history is validated and repaired: tool responses are moved next to the call they answer, content is normalized to valid types, and provider-specific fields are added or stripped. An interrupted session therefore resumes cleanly instead of failing with a 400.

### Interrupted todo lists

A list with pending or in-progress tasks is detected when the chat opens, and you are asked whether to resume it. An in-progress task resumes its original subagent session.

### Cancelling

Ctrl+C in the terminal, or the stop button in the web UI, cancels cooperatively: streaming stops, running shell commands are killed, and no new tool call starts. Partially received tool calls with incomplete arguments are dropped so they are never re-run. What was already done stays in the history and can be resumed.

### Two instances, one chat

A chat is locked only while a turn is running, using an OS-level file lock under `.raggie/locks/`. A second Raggie process trying to generate into the same chat gets "This chat is in use by another raggie instance". The lock is released by the OS when the process exits, so there are no stale locks to clean up.

For undo and redo crash safety, see [Undo and history](undo-and-history.md#crash-safety).
