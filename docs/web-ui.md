# Web UI

Raggie ships a chat UI served by the agent process itself. There is no separate frontend to deploy.

## Running

```bash
cd /path/to/project
raggie code --web                   # http://127.0.0.1:8765
raggie code --web --acp-port 9000   # another port
raggie code --web --dev             # isolated data dir (.raggie-dev)
```

The server prints the link to open:

```
raggie web ui: http://127.0.0.1:8765/?sid=1a2b3c4d
```

- The UI is rooted at the directory you ran the command in.
- It listens on `127.0.0.1` only.
- If the port is taken, the next free one is used and the printed link reflects it.
- The server stays in the foreground. Ctrl+C stops it.

It is the same agent as the terminal: same chats, same `.raggie/` data, same index, same snapshots. You can switch between the two freely.

### The `sid` in the link

Each running instance gets a unique id, carried as `?sid=...`. A stale tab that belongs to a different instance is rejected instead of silently talking to the wrong project.

### Chat locking

A chat is locked only while a turn is generating, with an OS-level file lock under `.raggie/locks/`. A second instance that tries to generate into the same chat gets an error. The lock is released when the turn ends or the process exits.

## What you get

- **First-run setup page**: add API keys, configure the role's provider, model, base URL, context window, reasoning effort and custom User-Agent, and manage MCP servers (add, remove, test), without touching the CLI.
- **Chat list**: resume or delete any chat, and search across your past messages.
- **Streaming**: responses and reasoning stream in live. Tool calls appear as a timeline with parameters, status and output.
- **Subagent view**: subagent work streams live in a nested block, including subagents of subagents, and is rebuilt when you reopen the chat.
- **Permissions**: shell commands, background services and restricted paths show an Allow / Always Allow / Reject panel. The turn waits for your answer.
- **Questions**: when the agent uses `AskUser`, the question appears with clickable options.
- **Todo list**: a bar shows the active plan and progress, with a modal for the full list.
- **Command menu**: every [in-chat command](commands.md#in-chat-commands), with submenus for fixed choices such as thinking modes, reasoning effort values and skill names.
- **Handover**: when a context handover happens, the handover document is shown as its own panel.
- **Code health**: a health panel with the latest stats, refreshable on demand. It never mixes into chat text.
- **Cancel and resume**: stop a turn at any point. Pending prompts are auto-denied so the agent stops cleanly. An interrupted turn can be resumed.
- **Model and effort**: shown next to the composer and switchable for the active role.
- **Light and dark themes**, and automatic RTL / LTR text direction.

## VS Code

The Raggie Code extension embeds this UI in a sidebar and manages the server for you. See [Getting started](getting-started.md#vs-code-extension-recommended).

## Building the frontend

The pip package ships a pre-built UI. You only need this when working from a source checkout or changing the frontend. The frontend lives in `web-ui/` (Svelte 5, TypeScript, Vite) and uses **pnpm**.

```bash
cd web-ui
pnpm install
pnpm build
```

Where the server looks for the build, in order:

1. `src/acp_server/webui/`, the copy bundled in the package
2. `web-ui/dist/`, a source checkout's build

If neither exists the server still starts and the API works, but `GET /` returns 503 with a build hint.

### Development

Run the backend and Vite's dev server side by side:

```bash
raggie code --web --dev     # terminal 1: backend on 8765
cd web-ui && pnpm dev       # terminal 2: Vite with HMR, proxies POSTs to 8765
```

```bash
pnpm check    # svelte-check and tsc
pnpm test     # vitest
```

The frontend uses Svelte 5 runes only (`$state`, `$derived`, `$effect`).

### Releasing

Sync the build into the package before building a wheel, so pip installs include it:

```bash
python sync_webui.py           # web-ui/dist -> src/acp_server/webui
python -m pip wheel . -w dist
```

`python build_all.py` runs the whole pipeline: builds the web UI, syncs it into the package, mirrors it into the VS Code extension and packages the `.vsix`.

## API

The UI talks to the endpoint it is served from: JSON-RPC 2.0 over `POST /`. You can build your own client against it.

`session/prompt` and `session/resume` answer with a Server-Sent Events stream: one `data: {...}` frame per notification, then a final frame with the JSON-RPC response. A `: keepalive` comment is sent every 15 seconds of silence.

### Standard ACP methods

`initialize`, `authenticate`, `session/new`, `session/prompt`, `session/cancel` (notification).

### Extensions

| Method | Params | Result |
|---|---|---|
| `chats/list` | | `[{id, title, updatedAt, previewRole, preview}]` |
| `chats/open` | `{chatId, cwd}` | `{sessionId}` |
| `chats/delete` | `{chatId}` | `{ok: true}` |
| `chats/history` | `{sessionId, limit?, beforeId?}` | `{messages, hasMore, nextBefore}`, paginated from newest |
| `chats/search` | `{query, limit?}` | Matching user messages (full-text search) |
| `session/resume` | `{sessionId}` | SSE stream, continues an interrupted turn |
| `session/dangling` | `{sessionId}` | Whether the session has interrupted work |
| `todo/active` | `{sessionId}` | The active todo list with its tasks, or `null` |
| `commands/list` | | `[{name, description, usage, choices, kind}]` where `kind` is `action`, `choices` or `input` |
| `health/stats` | `{sessionId}` | `{healthy, functions: [...], objects: [...]}` |
| `health/report` | `{sessionId}` | The full complexity report text |
| `setup/status` | | `{setupComplete, keys, roles, providers, activeRole}`. Keys are masked |
| `setup/add_key` | `{provider, baseUrl, apiKey}` | |
| `setup/update_key` | `{keyId, apiKey}` | |
| `setup/remove_key` | `{keyId}` | |
| `setup/update_role` | `{role, model?, baseUrl?, provider?, contextWindow?, reasoningEffort?, userAgent?}` | |
| `setup/update_active_role` | `{model?, reasoningEffort?}` | |
| `mcp/list` | | `{path, servers}` where each server is `{name, kind, command, args, env, url, trust}` and `kind` is `stdio`, `http` or `unknown` |
| `mcp/add` | `{name, command?, args?, env?, url?, trust}` | `{ok, name}` |
| `mcp/remove` | `{name}` | `{ok: true}` |
| `mcp/test` | `{name}` | `{ok, tools, error}` |

`GET /identity` returns `{service: "raggie-acp", pid, cwd, port}`, which lets a client confirm the server belongs to its project.

### Frames pushed during a turn

Besides standard `session/update` notifications:

| Method | Meaning |
|---|---|
| `session/status` | `{sessionId, status}`. Status text such as "Indexing codebase...". `status: null` means done |
| `session/request_permission` | `{sessionId, requestId, toolCall, options, detail}`. Answer with the `session/respond_permission` notification `{requestId, outcome}`, outcome `allow`, `allow_always` or `reject` |
| `session/request_ask` | `{sessionId, requestId, question, options, allowMultiple}`. Answer with the `session/respond_ask` notification `{requestId, answer}` |
| `session/subagent_update` | Live subagent activity: `{phase, subagentSessionId, depth, ...}` with phases `start`, `chunk`, `thought`, `tool_call`, `tool_result`, `error`, `end` |
| `session/handover` | `{sessionId, text}`. The handover document, at the moment of handover |
| `session/health_stats` | `{sessionId, stats}`. Sent when a turn ends with fresh health data |
| `session/notice` | `{sessionId, text}`. Output of an in-chat command such as `/help` |

`session/cancel` also resolves any pending permission or question for the session, so the UI never hangs.

If a request carries a `sid` param that does not match the running instance, it is rejected with error code `-32001`. Requests without a `sid` are accepted.
