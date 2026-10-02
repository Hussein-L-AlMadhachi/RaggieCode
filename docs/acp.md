# ACP

Raggie can run as a headless agent speaking **ACP** (Agent Client Protocol), the JSON-RPC 2.0 protocol editors such as Zed use to talk to coding agents.

## Transports

| Flag | Transport | Use it for |
|---|---|---|
| `--acp-stdio` | JSON-RPC over stdin and stdout | Editors that launch the agent as a subprocess (Zed and others) |
| `--acp-http` | HTTP POST with SSE streaming | Custom clients, remote consumers, service-style setups |

```bash
raggie --acp-stdio

raggie code --acp-http --acp-port 8765
raggie code --acp-http --acp-auto-approve
```

The role defaults to `code` when omitted. `raggie code --web` is the HTTP transport plus the built-in [web UI](web-ui.md).

## Connecting from Zed

Add Raggie as a custom agent server in Zed's `settings.json`:

```json
{
  "agent_servers": {
    "Raggie": {
      "command": "raggie",
      "args": ["--acp-stdio"]
    }
  }
}
```

Zed starts the process and passes the project directory when it creates a session. Check Zed's documentation if the settings key differs in your version.

Run `raggie setup` once beforehand so keys and the role are configured.

## How it works

- **Working directory.** The `cwd` of the first `session/new` roots the process: Raggie changes into it and uses that project's `.raggie/` data. Later sessions with a different `cwd` are ignored with a warning, so run one Raggie process per project.
- **Sessions.** Each `session/new` creates a new chat, indexes the codebase and builds an agent with all tools and commands.
- **Events.** The agent's event stream is mapped onto ACP `session/update` notifications:

  | Raggie event | ACP update |
  |---|---|
  | response text | `agent_message_chunk` |
  | reasoning text | `agent_thought_chunk` |
  | tool call started | `tool_call` (status `in_progress`, with raw input) |
  | tool call finished | `tool_call_update` (status `completed` or `failed`, with output) |

  Completions are streamed, so text arrives progressively. Tool output is capped at 4,000 characters per call.
- **Permissions.** Shell commands, background services, restricted paths, skill changes and todo plan approvals are sent to the client with `session/request_permission`, offering Allow, Always Allow (where it applies) and Reject. The editor shows its own approval UI.
- **Cancellation.** `session/cancel` sets a per-session flag. Streaming stops, running shell commands are killed and no further tool call starts. The interrupted step stays resumable.
- **Output.** In stdio mode stdout is the protocol channel, so all human-facing output goes to stderr.
- **In-chat commands.** Slash commands such as `/undo` and `/thinkingMode` work when sent as the prompt text.
- **MCP.** Raggie connects the servers from its own `~/.config/raggie/mcp_servers.json` when a session is created. MCP servers passed by the client in `session/new` are not used.

### Capabilities

Raggie advertises text prompts only: no image, audio or embedded-context prompt content, and no `session/load`.

## Permissions without a UI

What happens to a permission request depends on who can answer it:

| Setup | Behavior |
|---|---|
| Editor over stdio | The editor's permission UI |
| HTTP client that answers `session/respond_permission` (the web UI does) | Interactive |
| `--acp-auto-approve` | Everything is approved |
| HTTP client with no open stream, no auto-approve | Denied |

`--acp-auto-approve` lets the agent run any shell command inside the project without asking. Use it only in an environment you are comfortable giving that access to.

## HTTP transport

JSON-RPC 2.0 messages are POSTed to `/`. Regular requests get one JSON response. `session/prompt` responds with a Server-Sent Events stream: one `data:` frame per `session/update` notification, then a final frame with the JSON-RPC response.

```bash
curl -s http://127.0.0.1:8765/ -H 'Content-Type: application/json' -d '{
  "jsonrpc": "2.0", "id": 1, "method": "session/new",
  "params": {"cwd": "/path/to/project"}
}'
```

The server binds `127.0.0.1`. If the port is in use it tries the next one.

On top of the standard methods the HTTP transport offers extensions for chat management, setup, todo lists and health data. They are listed in [Web UI: API](web-ui.md#api).

## Building your own frontend

If you want to drive the agent from your own UI in-process rather than over a protocol, the I/O layer is the place to plug in. See the [`io_backend` specification](io_backend.md).
