# MCP

Raggie can call tools from external **MCP** (Model Context Protocol) servers: GitHub, filesystems, databases, or anything else in the MCP ecosystem. No Raggie-specific code is needed.

## Supported protocols and transports

| | stdio | Streamable HTTP |
|---|---|---|
| **2026-07-28** (stateless, "MCP 2.0") | yes | yes |
| **2025-era** (stateful) | yes | yes |

The official `mcp` Python SDK (v2.0.0) negotiates the protocol version per server, so you do not need to know which revision a server speaks.

## Configuration

Servers are defined in `~/.config/raggie/mcp_servers.json` and apply to every project:

```json
{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    "env": {"EXTRA": "value"},
    "trust": false
  },
  "github": {
    "url": "https://api.github.com/mcp",
    "trust": true
  }
}
```

| Field | Description |
|---|---|
| `command` | Executable for a stdio server |
| `args` | Arguments for the command |
| `env` | Environment variables for the command |
| `url` | URL of a Streamable HTTP server |
| `trust` | `true` skips the per-call confirmation. Default `false` |

A server needs either `command` or `url`. If both are present, `url` wins.

## Managing servers

Servers can be managed from the CLI or from the web UI. Both write to the same `mcp_servers.json`.

### Web UI

Open **Settings -> Setup -> "MCP servers"**. The section shows the config path and the configured servers, each with its transport, target and trust state.

- **Add**: choose `stdio` or `http`. For `stdio` enter the command, its arguments and optional environment variables (one `KEY=VALUE` per line); for `http` enter the URL. Tick **trust** to skip the per-call confirmation.
- **Remove**: delete a server.
- **Test**: connect to a server and list the tools it offers, or show the connection error.

A name that already exists must be removed before it can be added again.

### CLI

```bash
# Add a stdio server
raggie mcp --add filesystem --cmd npx --args -y @modelcontextprotocol/server-filesystem /tmp

# Add a stdio server with environment variables
raggie mcp --add db --cmd my-db-server --env DB_URL=postgres://localhost/app

# Add a trusted HTTP server
raggie mcp --add github --url https://api.github.com/mcp --trust

raggie mcp --list
raggie mcp --test filesystem     # connect and list the tools it offers
raggie mcp --remove filesystem
```

`--add` refuses to overwrite an existing name. Remove it first.

## How tools appear to the agent

Each MCP tool is exposed as `mcp__<server>__<tool>`, for example `mcp__filesystem__read_file`, next to the built-in tools. The model calls them like any other function.

- Names are sanitized to letters, digits, `_` and `-`, and truncated to 64 characters. If two tools end up with the same name, the second is skipped with a warning.
- The server name is added to each tool description so the model can tell where a tool comes from.
- Results longer than 30,000 characters are truncated.
- Every role gets every connected MCP tool. They are not filtered by the role's `tools` list.

## Trust and permissions

- **Trusted** (`"trust": true`): calls run immediately.
- **Untrusted** (default): each call asks first, showing the tool, the server and the arguments. In the terminal this is a y/n prompt. In the web UI and over ACP it goes through the same permission panel as built-in tools.

If you refuse, you can give a reason that is passed back to the agent.

## When servers connect

- **Terminal**: when the agent starts for a chat.
- **Web UI and ACP**: when a session is created.

Connection messages go to stderr:

```
[mcp] connected to 'filesystem' (protocol 2026-07-28, 11 tools)
```

A server that fails to connect is reported and skipped. It does not stop the agent. If nothing is configured, the MCP SDK is never imported.

After adding, editing or removing a server (in `mcp_servers.json`, with the CLI or in the web UI), restart Raggie to pick up the change. Running sessions are not hot-reloaded.
