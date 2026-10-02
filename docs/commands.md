# Commands

- [CLI commands](#cli-commands): what you type in your shell
- [In-chat commands](#in-chat-commands): what you type inside a chat

## CLI commands

| Command | Purpose |
|---|---|
| [`raggie <role> [project-dir]`](#raggie-role-project-dir) | Run the agent |
| [`raggie setup`](#raggie-setup) | First-time setup wizard |
| [`raggie keys`](#raggie-keys) | Manage API keys |
| [`raggie roles`](#raggie-roles) | Edit role settings |
| [`raggie skill`](#raggie-skill-role) | Manage skills |
| [`raggie mcp`](#raggie-mcp) | Manage MCP servers |
| [`raggie config`](#raggie-config) | Inspect and migrate config files |
| `raggie --version` | Print the version |

### `raggie <role> [project-dir]`

Run the agent with a role in a project directory.

| Argument | Description |
|---|---|
| `role` | Role name from `roles.json`. `code` is the default role. Optional with `--web`, `--acp-stdio` and `--acp-http` (falls back to `code`) |
| `project-dir` | Project directory. Default `.`. Created if it does not exist |
| `--prompt TEXT` | Run a single prompt and exit. Omit for interactive mode |
| `--effort N`, `--thinking-mode N` | [Thinking mode](planning-and-subagents.md#thinking-modes) 1 to 5 for a `--prompt` run |
| `--debug` | Show raw tool call outputs |
| `--web` | Serve the [web UI](web-ui.md) rooted at the current directory |
| `--acp-stdio` | Run as an [ACP](acp.md) agent over stdio (for editors such as Zed) |
| `--acp-http` | Run as an ACP agent over HTTP (JSON-RPC POST + SSE) |
| `--acp-port PORT` | Port for `--acp-http` and `--web`. Default `8765`. If taken, the next free port is used |
| `--acp-auto-approve` | Approve permission requests automatically in ACP and web modes |
| `--dev` | Use `.raggie-dev/` instead of `.raggie/` as the data directory, so a development build never touches your real chats, index or snapshots |

```bash
raggie code .                                   # interactive, current directory
raggie code /path/to/project                    # interactive, another project
raggie code . --prompt "Write a hello function" # single prompt
raggie code . --prompt "Refactor everything" --effort 5
raggie code . --debug
raggie code --web
raggie --acp-stdio
```

`--prompt` cannot be combined with `--web`.

### `raggie setup`

Guided first-time setup. Runs `raggie keys`, then `raggie roles`.

### `raggie keys`

Interactive menu to list, add and remove API keys in `~/.config/raggie/keys.json`. Adding a key asks for a provider, a base URL (pre-filled from the provider) and the key. Keys are shown masked.

### `raggie roles`

Interactive menu that lists every role with its model, base URL, provider, context window and reasoning settings, and lets you edit them. Base URLs can be picked from the ones you already have keys for.

### `raggie skill [role]`

Manage [skills](skills.md). With no flags it opens an interactive menu:

```
Skills for role 'code'
------------------------------------------------------------
  1. testing: Always write tests after implementing. Use pytest.
  2. refactoring: When refactoring, preserve behavior.

q. Exit
1. View skill content
2. Delete skill
3. Export skill to file
4. Import skill from file
5. List all skills (all roles)
```

Flags for scripting:

| Flag | Description |
|---|---|
| `--show` | With `--name`, print one skill. Without it, open the menu |
| `--name NAME` | Skill name (required for import, export, delete) |
| `--import-skill FILE` | Import a Markdown file as a skill (needs `--name`) |
| `--export-skill FILE` | Export a skill to a Markdown file (needs `--name`) |
| `--import-skill-dir DIR` | Import an Agent Skills folder (one with `SKILL.md`), or a folder of such folders |
| `--export-skill-dir DIR` | Export a skill as an Agent Skills folder (needs `--name`) |
| `--delete` | Delete a skill (needs `--name`) |
| `--list-all` | List all skills across all roles |

```bash
raggie skill code
raggie skill code --show --name testing
raggie skill code --import-skill my-skill.md --name testing
raggie skill code --export-skill backup.md --name testing
raggie skill code --import-skill-dir ./my-skills/
raggie skill code --export-skill-dir ./exported/ --name testing
raggie skill code --delete --name testing
raggie skill --list-all
```

Skills are stored per project (in `.raggie/.raggie.chat`), so run these from the project directory.

### `raggie mcp`

Manage [MCP servers](mcp.md) in `~/.config/raggie/mcp_servers.json`. The same actions are available in the web UI setup page (**Settings -> Setup -> "MCP servers"**).

| Flag | Description |
|---|---|
| `--list` | List configured servers |
| `--add NAME` | Add a server (with `--cmd` or `--url`) |
| `--remove NAME` | Remove a server |
| `--test NAME` | Connect to a server and list its tools |
| `--cmd EXE` | Executable for a stdio server |
| `--args ...` | Arguments for the stdio command |
| `--url URL` | URL for a Streamable HTTP server |
| `--trust` | Skip per-call confirmation for this server |
| `--env KEY=VALUE` | Environment variable for a stdio server (repeatable) |

```bash
raggie mcp --add local-files --cmd npx --args -y @modelcontextprotocol/server-filesystem /tmp
raggie mcp --add remote --url https://example.com/mcp --trust
raggie mcp --list
raggie mcp --test local-files
raggie mcp --remove local-files
```

### `raggie config`

Config files carry a schema version. Migrations run automatically when the agent starts, and this command lets you inspect or run them by hand.

```bash
raggie config status              # current vs latest schema version, pending migrations
raggie config migrate             # apply pending migrations
raggie config migrate --dry-run   # preview without writing
```

## In-chat commands

These are handled locally and never reach the model. They work in the terminal, the web UI (through the command menu) and the VS Code extension. `/help` prints the list.

| Command | Description |
|---|---|
| `/undo` | Undo the agent's last snapshot |
| `/redo` | Re-apply the last undone snapshot |
| `/thinkingMode [mode]` | Set the thinking mode by number (1 to 5) or name (`zen`, `serious`, `extreme`, `feral`, `insane`). No argument opens a picker |
| `/unlimitedThinkingMode` | Remove the subagent depth limit for this chat |
| `/model [name]` | Show or change the model for the current role |
| `/reasoningEffort [value]` | Show or set the provider reasoning effort (`low`, `medium`, `high`, ...). `auto` clears the override |
| `/reasoning [on\|off]` | Toggle reasoning for the current session |
| `/windowSize [tokens]` | Show or set the context window used by the handover logic |
| `/globalTodo [on\|off]` | Share one todo list across all subagents of a chat |
| `/reindex [--force]` | Re-index the codebase. `--force` rebuilds from scratch |
| `/health` | Write a full code complexity report to a `.txt` file |
| `/skills` | List loaded skills with their summaries |
| `/reload-skills` | Re-scan skill directories and refresh the agent's skill list |
| `/use <name>` | Inject a skill's content into the conversation for the agent to follow now |
| `/importSkills [dir]` | Import `SKILL.md` folders from a directory (default `.agents/skills`) into the current role |
| `/whitelist` | Review and remove shell commands you approved with "always" |
| `/debug [on\|off]` | Toggle raw tool output |
| `/help` | Show the command list |
| `!<command>` | Run a shell command directly, e.g. `!ls -la` |

Notes:

- `/model`, `/reasoningEffort`, `/windowSize` and `/globalTodo` are saved to `~/.config/raggie/roles.json` and apply to every project.
- `/reasoning` only affects the running session. At startup, reasoning is on exactly when a reasoning effort is set, so use `/reasoningEffort` for a lasting change.
- `/thinkingMode` is stored per chat.
- The valid values for `/reasoningEffort` depend on the provider. Local providers do not support it.
- A command that takes an argument shows its current value when called with none.
- `!` commands run without a permission prompt and without the agent's path sandbox. Their output is printed and not added to the conversation.
