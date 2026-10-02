# Tools

Raggie ships 32 built-in tools. A role uses the ones listed in its `tools` array in `roles.json`. The default `code` role enables 30 of them. `Document` and `ReadImage` are opt-in: add their names to the role's `tools` list to enable them.

Tools from [MCP servers](mcp.md) are added on top as `mcp__<server>__<tool>`.

## Code exploration

Powered by the [code index](code-indexing.md).

| Tool | What it does |
|---|---|
| `GetFileCodeSemantics` | A file's structure: functions with parameters, classes with methods and members, imports, and what each function depends on, resolved to definition files. `include_bodies=true` adds full source. Falls back to raw content for files that are not indexed |
| `GetSymbolSourceCode` | Full source of a function, method or class by name. Falls back to a fuzzy search across functions, classes and variables when there is no exact match |
| `WalkCallTree` | Breadth-first walk of the call graph from a function. Default depth 5, with cycle detection. Options: `include_external` for unresolved third-party calls, `exclude` for path prefixes such as `tests/` |
| `WholeFileContentDump` | Raw file content. Meant for non-code files (configs, docs, logs). The agent is steered to the semantic tools first for code |
| `ListDir` | Directory listing with type and size, to a given depth |
| `SearchAllFilesContent` | Regex search across a file or directory (ripgrep) |
| `FileNameSearch` | Fuzzy file name search. Returns the top matches (5 by default). Respects ignore files |
| `Document` | *Experimental, opt-in.* Read or write persistent descriptions for symbols in the index. Descriptions show up in `GetSymbolSourceCode` and `GetFileCodeSemantics` output |

## Files and shell

| Tool | What it does |
|---|---|
| `WriteFile` | Create or overwrite a file. Creates parent directories |
| `ReplaceText` | Find and replace in a file, literal or regex (`use_regex`). Must match exactly once unless `replace_all` is set. Returns a diff view |
| `EditSymbol` | Replace the whole implementation of a function, method or class by name. Returns a diff view |
| `RemoveFile` | Delete a file or directory |
| `Shell` | Run a shell command. Default timeout 30 seconds. The result includes the exit code |
| `TempBackgroundService` | Start a long-running process (dev server, watcher) without blocking. Returns a PID |
| `ShellKill` | Stop a background service by PID and return its captured stdout and stderr |

## Web and vision

| Tool | What it does |
|---|---|
| `WebSearch` | DuckDuckGo search, no API key. 5 results by default, up to 20, optional region |
| `WebFetch` | Fetch a URL as readable text. HTML is stripped, JSON, XML and plain text are returned as is. Output is capped at `max_chars` (default 20,000). Binary content is rejected |
| `ReadImage` | *Opt-in.* Load an image (PNG, JPG, GIF, BMP, WEBP, SVG, TIFF, ICO, HEIC, HEIF) as vision input. Needs a vision-capable model |

## Agent and communication

| Tool | What it does |
|---|---|
| `DispatchSubagent` | Start a child agent for a subtask. See [Subagents](planning-and-subagents.md#subagents) |
| `AskUser` | Ask you a question mid-task, free-form or with options (single or multiple choice). You can always type your own answer |
| `ViewChanges` | Inspect the snapshot repo: `status`, `diff` (paginated) or `log`. See [Undo and history](undo-and-history.md#viewchanges) |
| `GetSkill` | Fetch the full content of a skill by name |
| `SetSkill` | Create or update a skill for the agent's own role. Always asks for your consent |

## Todo lists

See [Todo lists](planning-and-subagents.md#todo-lists) for the workflow.

| Tool | What it does |
|---|---|
| `GetActiveTodoList` | Check for an unfinished todo list |
| `CreateTodoList` | Create a new todo list |
| `AddTask` | Add a task with goal, requirements, notes and context |
| `GetTodoList` | Show the plan with every task's status |
| `ApproveTodoList` | Present the plan to you for approval |
| `ExecuteNextTask` | Run the next pending task in a subagent |
| `MarkTaskComplete` | Mark a task as done |
| `MarkTaskFailed` | Mark a task as failed |
| `MarkTaskCancelled` | Mark a task as cancelled, with a reason |

## Permissions

### File tools

Reading, writing, replacing, editing and removing work freely inside the project on files that are not ignored. Two cases prompt you first:

- the path is **outside the project directory**
- the file matches **`.aiignore` / `.gitignore`**

```
Permission requested: write ../shared/config.py
Reason: path is outside the current working directory
Options: (a)lways  (y)es  (n)o
```

`always` remembers that path (and everything under it, for a directory) until Raggie exits. On `no` you can give a reason, which is passed back to the agent.

### Shell commands

Shell commands are checked in this order:

1. **Path sandbox.** A command that references a path outside the project, or an ignored path, is refused outright. There is no prompt for this. `/dev/null` and the standard streams are allowed.
2. **Read-only commands run automatically.** The command is parsed with a bash grammar, and it is auto-approved only when every statement is observation-only: `cat`, `head`, `tail`, `grep`, `rg`, `egrep`, `fgrep`, `ls`, `wc`, `echo`, `find` without mutating operators (`-delete`, `-exec`, ...), and `sed -n` without in-place editing or write commands. Any output redirection into a file, command substitution, subshell or parse error falls through to a prompt.
3. **Whitelisted commands run automatically.** See below.
4. **Everything else asks you.**

```
Do you want to allow the agent to run:
python -m pytest tests/test_auth.py
? (y)es (n)o (a)lways:
```

Choosing `always` whitelists each statement of the command, for that role, in the project's database. A compound command runs without a prompt when every one of its statements is either read-only or whitelisted, so `pytest tests/ | grep FAILED` passes once `pytest tests/` is whitelisted. Matching is on the exact statement text: whitelisting `git status` does not allow `git push`.

Review or remove entries with `/whitelist`.

`TempBackgroundService` applies the same path sandbox and always asks, with a plain yes or no.

### Other prompts

- `SetSkill` shows the proposed skill content and asks before saving.
- `ApproveTodoList` asks before a plan can run.
- Tools from an untrusted MCP server ask on every call.

### In the web UI and editors

The same prompts appear as Allow / Always Allow / Reject panels in the web UI, and through the editor's permission UI over ACP. With `--acp-auto-approve` they are approved automatically.

## After a tool runs

File-modifying tools and `Shell` trigger an incremental re-index, so the next exploration call sees the new code. Changes made by file tools are also recorded per session, which is how a subagent's result can list the files it touched.
