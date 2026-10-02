# Configuration

Raggie has two kinds of configuration:

- **User config** in `~/.config/raggie/`, shared by all projects: keys, roles, tool definitions, MCP servers.
- **Project files** in the project root: `AGENTS.md`, `.gitignore`, `.aiignore`, skill folders.

## User config directory

```
~/.config/raggie/
├── keys.json                # API keys
├── roles.json               # role definitions
├── tools.json               # tool definitions sent to the model
├── mcp_servers.json         # MCP servers
├── coder_system_prompt.md   # system prompt for the code role
└── _meta.json               # config schema version
```

Files are copied from the package defaults the first time they are needed. After that they are yours to edit.

### Migrations

`_meta.json` records a schema version. When a release changes the config format (a renamed tool, a new role field), a migration updates your files on the next agent start. To see or run them by hand:

```bash
raggie config status
raggie config migrate --dry-run
raggie config migrate
```

## `keys.json`

Maps `provider:base_url` to an API key:

```json
{
  "deepseek:https://api.deepseek.com": "sk-...",
  "ollama:http://localhost:11434/v1": "nokey"
}
```

- Edit it with `raggie keys` rather than by hand. The base URL must match the role's base URL exactly.
- You can hold several keys for one provider under different base URLs.
- The value `nokey` is the convention for servers that need no authentication.
- Older files that use a bare base URL as the key still work.

## `roles.json`

Each role is a model plus the tools and prompt it runs with. The default file defines one role, `code`:

```json
{
  "code": {
    "tools": ["WholeFileContentDump", "Shell", "WriteFile", "..."],
    "model": "deepseek-v4-flash",
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "system_prompt_file": "coder_system_prompt.md",
    "context_window": 200000,
    "reasoning_effort": "",
    "user_agent": "",
    "globalTodo": true
  }
}
```

| Field | Description |
|---|---|
| `model` | Model name sent to the API. Change in chat with `/model` |
| `provider` | Required. One of the [known providers](#providers). Drives provider-specific request behavior. Inferred from `base_url` when empty and recognizable |
| `base_url` | API endpoint. Optional: falls back to the provider's default URL |
| `tools` | Tool names this role may use. Names must exist in `tools.json`. See [Tools](tools.md) |
| `system_prompt_file` | Prompt file. A relative name is looked up in `~/.config/raggie/`, an absolute path is used as is |
| `system_prompt` | Inline prompt text, used when `system_prompt_file` is absent |
| `context_window` | Model context length in tokens. Controls when [handover](planning-and-subagents.md#context-handover) triggers. Change with `/windowSize` |
| `reasoning_effort` | Provider reasoning effort (`low`, `medium`, `high`, ...). Empty means reasoning is off. Change with `/reasoningEffort` |
| `user_agent` | Overrides the default `raggie/<version>` User-Agent header. Empty means default |
| `globalTodo` | `true` shares one todo list across all subagents of a chat. Change with `/globalTodo` |

The default file also contains `reasoning` and `stream` fields. They are kept for compatibility: reasoning is switched on by setting `reasoning_effort`, and streaming is chosen by the interface (on in the web UI and ACP, off in the terminal).

To add a role, add another top-level entry and run it with `raggie <role-name> .`.

### Providers

| Provider | Default base URL | Reasoning effort values |
|---|---|---|
| `deepseek` | `https://api.deepseek.com` | low, medium, high |
| `openai` | `https://api.openai.com/v1` | none, minimal, low, medium, high, xhigh, max |
| `z.ai` | `https://api.z.ai/api/paas/v4/` | none, minimal, low, medium, high, xhigh, max |
| `grok` | `https://api.x.ai/v1` | low, medium, high, xhigh |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | low, medium, high |
| `moonshot` | `https://api.moonshot.ai/v1` | low, high, max |
| `opencode-go` | `https://opencode.ai/zen/go/v1` | none, minimal, low, medium, high, xhigh, max |
| `opencode-zen` | `https://opencode.ai/zen/v1` | none, minimal, low, medium, high, xhigh, max |
| `litellm` | `http://localhost:4000/v1` | none, minimal, low, medium, high, xhigh, max |
| `ollama`, `lm-studio`, `llama-cpp`, `vllm`, `text-generation-webui`, `jan`, `gpt4all` | localhost, see [Local models](local-models.md) | not supported |

The provider setting handles the differences between "OpenAI-compatible" APIs for you: whether reasoning content must be sent back on later turns, how thinking is switched on, which parameters are rejected, and session headers used for prompt caching.

Any other OpenAI-compatible endpoint works if you point one of these providers at it with a custom `base_url`. `litellm` and `openai` are the usual choices.

## `tools.json`

The function-calling schemas sent to the model: names, descriptions and parameters for all 32 built-in tools. You normally leave this alone. Editing a description changes how the model is told to use that tool.

## `mcp_servers.json`

External MCP servers. See [MCP](mcp.md).

## System prompt

On every start the system prompt is assembled in this order:

1. The role's prompt file (`coder_system_prompt.md` for `code`)
2. Today's date, the working directory and host system info
3. One-line summaries of all skills
4. The project's `AGENTS.md`, if present

## `AGENTS.md`

Put an `AGENTS.md` in the project root and its content is appended to the system prompt. Use it for project conventions:

```markdown
# Project Conventions
- Use TypeScript for all new files
- Tests go in a __tests__/ directory
- Always use pnpm
```

It is read when a chat starts, so restart the chat after editing it.

## `.gitignore` and `.aiignore`

Ignore patterns decide which files are off limits to the agent.

- If `.aiignore` exists in the project root, it is used **instead of** `.gitignore`.
- Otherwise `.gitignore` is used.
- `.aiignore` uses the same pattern syntax as `.gitignore`.

What the ignore rules affect:

| Area | Behavior |
|---|---|
| Code index | Ignored files are not indexed |
| File tools (read, write, replace, edit, remove) | Ignored files need your explicit permission per path |
| Shell tools | A command that mentions an ignored path is refused |
| Snapshot repo (`/undo`) | Follows `.gitignore` only. `.aiignore` does not change what gets snapshotted |

So `.aiignore` lets you hide things from the agent (vendored code, fixtures, secrets) without changing what git ignores.

## Per-project data

Everything Raggie stores for a project lives in `.raggie/` in the project root:

```
.raggie/
├── .raggie.chat           # chats, sessions, messages, skills, todo lists, shell whitelist
├── .code_index.raggie     # code index
├── git/                   # snapshot repo for /undo and /redo
├── locks/                 # per-chat lock files
└── frontend_config.json   # optional, see Code indexing
```

Add `.raggie/` to your project's `.gitignore`. With `--dev` the directory is `.raggie-dev/` instead.
