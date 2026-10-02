# Undo and history

Raggie keeps its own git repository at `.raggie/git/` and snapshots your project into it as the agent works. It is separate from your project's real git repo: nothing is ever committed to, or read from, your `.git`.

## How it works

1. **Before each prompt**, the working tree is committed as an "Auto-snapshot" if anything changed since the last commit. This captures edits you made yourself between turns, so undo always has a valid state to return to.
2. **After each response**, when the agent finishes its turn, all changes are committed. Nothing is committed if no file changed.
3. The commit message records your prompt and the number of tool calls.

Only the main agent commits. Subagent work is included in the main agent's commit for that turn.

## `/undo` and `/redo`

```
/undo    restore the project to the previous snapshot
/redo    re-apply the snapshot you just undid
```

- `/undo` moves back one commit and rewrites the working tree to match it.
- Undone commits go on a redo stack (`.raggie/.redo_stack`). `/redo` pops the latest one.
- A new commit clears the redo stack, as in any editor.
- You can undo several times in a row.

Because the pre-prompt snapshot is a commit of its own, a turn can be two steps back: the agent's commit, then the auto-snapshot of your own edits before it.

`/undo` does not snapshot first. Edits you made by hand since the last commit are discarded when the working tree is rewritten, so send a prompt (which snapshots them) or save them elsewhere before undoing.

## What is tracked

Snapshots follow your project's `.gitignore`. `.aiignore` does not affect them: it only controls what the agent may read and index.

Always excluded, whatever the ignore files say:

| Kind | Entries |
|---|---|
| Directories | `.raggie`, `.raggie-dev`, `.git`, `.venv`, `__pycache__`, `build`, `dist`, `.egg-info`, `node_modules` |
| Extensions | `.pyc`, `.pyo`, `.pyd`, `.so`, `.dll`, `.dylib`, `.exe`, `.db`, `.sqlite`, `.sqlite3`, `.db-wal`, `.db-shm` |

Symlinks are skipped. Nested `.gitignore` files are not read, only the one in the project root.

An undo never deletes files that are excluded or ignored, so your virtualenv, dependencies and databases are safe.

## `ViewChanges`

The agent can inspect the snapshot repo itself with the `ViewChanges` tool.

| `view_type` | Shows |
|---|---|
| `status` | Files added, modified and deleted since the last commit. Optional `category` filter |
| `diff` | Line-by-line diffs. Paginated with `page` and `files_per_page` (default 25), capped per file with `max_diff_lines` (default 500), optional `path` filter. Binary files are summarized by size |
| `log` | Commit history, `max_count` entries (default 10) |

Pagination exists so a huge change set can never overflow the model's context in one tool result.

## Crash safety

Undo and redo rewrite the working tree, so they guard against interruption with marker files:

- `.raggie/.undoing` is written before an undo starts changing files, and removed when it completes.
- `.raggie/.redoing` does the same for a redo.

If Raggie starts and finds a stale marker, it warns that a previous undo or redo may have been interrupted and that some files may be missing, then clears the marker. The commits themselves are intact in `.raggie/git/`, so the state can be restored.

If `.raggie/git/` is missing or not a valid repository, it is re-initialized on the next start.

## Your own git

Raggie's snapshots are a safety net, not version control. Keep committing to your real repository as usual, and add `.raggie/` to your `.gitignore`.
