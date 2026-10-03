# Raggie Web UI

A small Svelte 5 + TypeScript + Vite app that talks to the raggie backend over
ACP (Agent Client Protocol) JSON-RPC, served directly by the backend itself.

## Running

Build the frontend once, then start the backend:

```sh
cd web-ui
pnpm install && pnpm build
cd ..

python3 build_all.py
python3 src/raggie.py code --web         # serves http://127.0.0.1:8765/?sid=<id>
# python3 src/raggie code --web --dev    # isolated: uses .raggie-dev instead of .raggie
# python3 src/raggie code --web --acp-port 9000
```

The link carries a unique session id (`?sid=...`) per running instance; a stale
tab opened against a different running instance is rejected. A chat is locked
only while a turn/generation is running: a second raggie instance trying to
generate into a locked chat gets an error. The lock is an OS-level file lock
under `.raggie/locks/`, auto-released when the turn ends or the process exits.

If `web-ui/dist/` is missing, the server still runs and the JSON-RPC API
works, but `GET /` responds with 503 and a build hint. Rebuild with
`pnpm build` in `web-ui/` whenever frontend sources change, the backend
serves the built files only (no live reload).

The pip package bundles the UI: `python sync_webui.py` copies
`web-ui/dist` into `src/acp_server/webui` (packaged as package data), and
`default_web_dist()` prefers the bundled copy in installed environments and
falls back to `web-ui/dist` in source checkouts. Run the sync before
`python -m pip wheel .` so releases include a fresh build.

## Development workflow

For iterative frontend work you can either rebuild after each change
(`pnpm build`, quick) or run Vite's dev server with HMR and a proxy to a
backend on the default port:

```sh
# terminal 1
raggie code --web                     # backend on 127.0.0.1:8765
# terminal 2
cd web-ui && pnpm dev               # Vite dev server, proxies POSTs to 8765
```

`vite.config.ts` proxies POST requests (the JSON-RPC calls and the SSE
`session/prompt` stream) to the backend, while Vite keeps serving the dev
modules and HMR for GETs.

Type-checking: `pnpm check` (svelte-check). Svelte 5 runes only
(`$state` / `$derived` / `$effect`), no `svelte/store`.

## API

Everything is JSON-RPC 2.0 POSTed to `/`. `session/prompt` responds with a
Server-Sent Events stream: one `data: {...}` frame per notification, then a
final frame carrying the JSON-RPC response.

Standard ACP methods:

- `initialize`, `authenticate`, `session/new`, `session/prompt`,
  `session/cancel` (notification)

Web UI extensions (not part of ACP):

- `chats/list` -> list of chats for the role:
  `[{id, title, updatedAt, previewRole, preview}]`
- `chats/open` `{chatId, cwd}` -> `{sessionId}` (binds a session to an
  existing chat)
- `chats/delete` `{chatId}` -> `{ok: true}`
- `chats/history` `{sessionId, limit?, beforeId?}` ->
  `{messages: [{id, role: "user"|"agent", text}], hasMore, nextBefore}`
  (paginated: without `limit` the whole history; with `limit` the newest
  `limit` messages ending before `beforeId`   the cursor for older pages)
- `health/stats` `{sessionId}` -> structured payload
  `{healthy, functions: [{name, file, line, score, severity}],
  objects: [{name, file, line, severity, score, methods, attributes, lines}]}`
  (computed on demand; errors if no session or no index data)
- `commands/list` -> `[{name, description, usage, choices, kind}]` (all
  registered commands; `kind` is `action` (run as-is), `choices`
  (submenu of fixed options   some resolved dynamically from the role,
  e.g. effort values for the provider, installed skill names) or `input`
  (needs a free-form argument, inserted into the composer))

Web-only SSE frames emitted during a prompt (dict frames, forwarded
verbatim):

- `{"method": "session/status", "params": {sessionId, status}}`, status
  text, `status: null` means done (e.g. "Indexing codebase...")
- `{"method": "session/request_permission", "params": {sessionId,
  requestId, toolCall, options}}`, answer via the `session/respond_permission`
  notification `{requestId, outcome}` where outcome is `allow`,
  `allow_always` (or `always`) or `reject`
- `{"method": "session/request_ask", "params": {sessionId, requestId,
  question}}`, free-form question; answer via the
  `session/respond_ask` notification `{requestId, answer}`
- `{"method": "session/health_stats", "params": {sessionId, stats}}`,
  emitted when a turn finishes with fresh code health data; `stats` is the
  same structured payload as the `health/stats` request; the chat text
  never contains the summary itself
- `{"method": "session/notice", "params": {sessionId, text}}`, command
  handler output (e.g. `/help`, `/skills`) captured by the backend and
  rendered as an info block; the chat text never contains it

`session/cancel` also cancels any pending permission/ask for the session
(the UI gets a denied/cancelled outcome instead of hanging).

## Layout

- `src/lib/api.ts`, JSON-RPC + SSE fetch helpers
- `src/lib/store.svelte.ts`, `ChatStore` (chats, streaming, pendings)
- `src/lib/types.ts`, message / frame types
- `src/lib/components/`, ChatList, ChatView, MessageList, AskPanel,
  PermPanel, Composer, HealthModal, CommandMenu, Markdown
- Markdown rendering: `marked` (GFM, `breaks: true`) + `dompurify`
  sanitization   see `src/lib/components/Markdown.svelte`; agent and
  thought messages render as markdown, user messages and tool output stay
  plain text
