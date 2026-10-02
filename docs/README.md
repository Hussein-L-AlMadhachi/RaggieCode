# Raggie Code documentation

Start with [Getting started](getting-started.md) if you have not run Raggie yet.

## Using Raggie

| Page | What it covers |
|---|---|
| [Getting started](getting-started.md) | VS Code extension, command-line install, setup, first session, `@file` references, `/undo` |
| [Commands](commands.md) | All CLI commands and in-chat slash commands |
| [Configuration](configuration.md) | Config files, `roles.json`, providers, `AGENTS.md`, `.gitignore` / `.aiignore` |
| [Local models](local-models.md) | Ollama, vLLM, LM Studio and other local servers |
| [FAQ](faq.md) | Common questions |

## How it works

| Page | What it covers |
|---|---|
| [Planning and subagents](planning-and-subagents.md) | Thinking modes, todo lists, subagents, handover, crash recovery |
| [Tools](tools.md) | The 32 built-in tools and the permission model |
| [Skills](skills.md) | Skills system, Agent Skills format, auto-discovery |
| [Code indexing](code-indexing.md) | Languages, project detection, performance |
| [Undo and history](undo-and-history.md) | `.raggie/git`, `/undo`, `/redo`, crash safety |
| [Code health](code-health.md) | Complexity score, class bloat, `/health` report |

## Interfaces and integrations

| Page | What it covers |
|---|---|
| [Web UI](web-ui.md) | The built-in web UI (`raggie code --web`) |
| [ACP](acp.md) | Zed and other editors over the Agent Client Protocol |
| [MCP](mcp.md) | Connecting external MCP tool servers |

## For contributors

| Page | What it covers |
|---|---|
| [Architecture](architecture.md) | Source layout, agent loop, databases, build and tests |
| [Indexer internals](indexer.md) | Deep dive into the tree-sitter indexer modules and schema |
| [`io_backend` specification](io_backend.md) | The I/O contract for building a custom frontend |
