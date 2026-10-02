# FAQ

### Does my code get sent to an external API?

Your prompts, the agent's responses and whatever the tools read on the agent's behalf are sent to the LLM provider you configure. The code index, chat history and snapshot repo stay on your machine. With a [local model](local-models.md), nothing leaves it.

### Can I use it with a local model?

Yes. Ollama, LM Studio, vLLM, llama.cpp and others are built-in providers. See [Local models](local-models.md).

### Which providers are supported?

DeepSeek, OpenAI, z.ai, Grok, Qwen, Moonshot (Kimi), OpenCode Go and Zen, LiteLLM, and the local servers. Anything else that speaks the OpenAI Chat Completions API works through a custom base URL. See [Configuration](configuration.md#providers).

### Where is my data stored?

Per project, in `.raggie/` in the project root:

```
.raggie/
├── .raggie.chat           # chats, messages, skills, todo lists
├── .code_index.raggie     # code index
├── git/                   # snapshot repo for /undo
└── locks/                 # per-chat locks
```

Per user, in `~/.config/raggie/`: API keys, roles, tool definitions, MCP servers.

Add `.raggie/` to your project's `.gitignore`.

### How do I control what the agent can touch?

- Files matched by `.aiignore` (or `.gitignore` when there is no `.aiignore`) need your explicit permission to read or change, and are never indexed.
- Paths outside the project need your permission.
- Shell commands ask before running, unless they are read-only or you approved them with "always". Review those with `/whitelist`.

See [Tools: Permissions](tools.md#permissions).

### How do I undo what the agent did?

`/undo` restores the previous snapshot, `/redo` re-applies it. See [Undo and history](undo-and-history.md).

### Does Raggie commit to my git repository?

No. Snapshots go to a separate repository in `.raggie/git/`. Your project's `.git` is never read or written.

### Can I customise the agent's behavior?

- `AGENTS.md` in the project root for conventions that always apply
- [Skills](skills.md) for instructions loaded on demand
- `roles.json` for the model, tools and system prompt

See [Configuration](configuration.md).

### What happens if I interrupt the agent or it crashes?

Nothing is lost. Messages are saved as they happen. On reopening the chat, unanswered tool calls are re-executed and the turn continues. Subagents and todo tasks resume their existing sessions instead of starting over, and unfinished todo lists are offered for resumption. See [Crash recovery](planning-and-subagents.md#crash-recovery).

### What happens when the context window fills up?

The agent writes a handover document for the current task and continues in a fresh session, automatically. See [Context handover](planning-and-subagents.md#context-handover).

### The agent stops with a context length error. What now?

Your `context_window` setting is probably larger than what the model really supports, so handover starts too late. Set the real value with `/windowSize <tokens>`.

### Can the agent ask me questions?

Yes. With `AskUser` it can ask free-form or multiple-choice questions mid-task, and you can always type your own answer.

### Can I use Raggie in my editor?

- **VS Code**: the Raggie Code extension gives you the chat in a sidebar and installs Raggie for you. See [Getting started](getting-started.md#vs-code-extension-recommended).
- **Zed and other ACP editors**: run it with `raggie --acp-stdio`. See [ACP](acp.md).
- **Any browser**: `raggie code --web`. See [Web UI](web-ui.md).

### Can I extend Raggie with external tools?

Yes, through MCP. Add a server to `~/.config/raggie/mcp_servers.json` and its tools appear as `mcp__<server>__<tool>`. See [MCP](mcp.md).

### Can I run two Raggie instances on the same project?

Yes. They share the same data. A chat is locked only while a turn is generating, so two instances cannot write into the same chat at once, but they can work in different chats.

### Why are my tests missing from the call graph?

Directories named `test` or `tests` are not indexed. The agent can still read, edit and run them. See [Code indexing](code-indexing.md#what-is-skipped).

### "No API key found for ..." at startup

The key lookup uses `provider:base_url`, and the base URL must match the role's base URL exactly. Run `raggie keys` to add a key for that provider and URL, or `raggie setup` to redo both steps. For a local server, use `nokey` as the key.

### "No provider found for role ..."

The role has no `provider` and it could not be inferred from the base URL. Run `raggie roles` and pick one.

### How do I change the model quickly?

`/model <name>` in a chat. It is saved for the role.
