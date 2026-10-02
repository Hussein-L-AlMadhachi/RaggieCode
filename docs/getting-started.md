# Getting started

There are two ways in. Most people use the VS Code extension, which installs and runs everything for you. The command line gives you the same agent in a terminal or browser.

Either way you need:

- Python 3.10+
- An API key for an OpenAI-compatible provider, or a local model server (see [Local models](local-models.md))

## VS Code extension (recommended)

The **Raggie Code** extension puts the full chat in a VS Code sidebar and manages the agent for you. You do not have to install anything from a terminal.

### 1. Install the extension

Open the Extensions view in VS Code, search for **Raggie Code** and install it.

### 2. Open the chat

Open your project folder and click the Raggie icon in the activity bar, or run **Raggie Code: Open Chat** from the command palette.

### 3. Let it install Raggie

The extension needs the `raggiecode` Python package, and gets it for you:

| Platform | What happens |
|---|---|
| **Linux, BSD** | Automatic, no prompt. The extension creates a private virtualenv at `~/.config/raggie/venv` and installs `raggiecode` into it. Only Python is required, pip comes with the virtualenv |
| **macOS, Windows** | If the `raggie` command is not found, an error notification appears with an **Install Raggie Code** button. Clicking it runs `pip install raggiecode` and then starts the server. Python and pip must be on your `PATH` |

Progress and pip output go to the **Raggie Server** output channel.

### 4. Add your API key

The chat opens on a setup page the first time. Add an API key, choose the provider and model, and you are ready. This is the same configuration `raggie setup` writes, see [Configuration](configuration.md).

### Using it

| Action | How |
|---|---|
| Send the current selection into the chat | **Raggie Code: Ask About Selection**, or `Ctrl+Shift+Alt+R` |
| Copy the selection as `@path/to/file:23-43` | Right-click > **Copy Reference for Raggie Code**, or `Ctrl+Alt+C` |
| Pin the chat next to Copilot | **Raggie Code: Move Chat to Secondary Sidebar**, then pick "New Secondary Side Bar Entry" |
| Start, restart or stop the server | The status bar item, or **Raggie Code: Manage Server** |
| Stop the agent and close the panel | The stop button on the chat's title bar |

On macOS use `Cmd` in place of `Ctrl`.

Everything in the chat works as described in the [Web UI](web-ui.md) page, because the sidebar embeds that UI. In-chat commands such as `/undo` are in the command menu.

### Settings

| Setting | Default | Description |
|---|---|---|
| `raggie.server.port` | `8765` | Port the local server listens on |
| `raggie.server.pythonPath` | `raggie` | Raggie executable. Set this to use your own install instead of the managed one |
| `raggie.server.role` | `code` | Agent role passed to the server |
| `raggie.server.autoStart` | `true` | Start the server when the extension activates |
| `raggie.server.args` | `[]` | Extra CLI arguments, e.g. `--dev` |
| `raggie.chat.openOnStartup` | `false` | Open the chat view on activation |

### Troubleshooting the install

| Message | Fix |
|---|---|
| Python was not found | Install Python 3.10+ and restart VS Code |
| `ensurepip` or the `venv` module is missing | On Debian and Ubuntu install the `python3-venv` package, then reload VS Code |
| pip exited with an error | Open the **Raggie Server** output channel for the full pip log |

### Using the `raggie` command too

On Linux and BSD the extension's copy lives in its own virtualenv, so `raggie` is not on your `PATH`. To use the terminal as well, either run `pip install raggiecode` yourself or call `~/.config/raggie/venv/bin/raggie` directly. Both share the same config and the same project data as the extension.

## Command line

From PyPI:

```bash
pip install raggiecode
```

From source:

```bash
git clone https://github.com/Hussein-L-AlMadhachi/RaggieCode.git
cd RaggieCode
pip install .
```

The terminal interface needs Linux or macOS (it uses `termios`).

Check the install with `raggie --version`.

## Setup

```bash
raggie setup
```

The wizard runs two steps:

1. **API keys.** Pick a provider from the known list (`deepseek`, `openai`, `z.ai`, `grok`, `qwen`, `moonshot`, `opencode-go`, `opencode-zen`, `litellm`, and the local ones). The base URL is pre-filled from the provider, so you usually just press Enter and paste the key.
2. **Roles.** Set the model, provider, base URL, context window and reasoning effort for the `code` role.

You can rerun either step on its own later with `raggie keys` and `raggie roles`. If you prefer a browser, `raggie code --web` shows the same setup as a page the first time. Details are in [Configuration](configuration.md).

## First session

```bash
raggie code .                 # current directory
raggie code /path/to/project  # another project
raggie code my-new-project    # the directory is created if it does not exist
```

`code` is the role name. It is the only role shipped by default.

On the first run in a directory that has subfolders and no `.raggie/` folder yet, Raggie asks whether to create a project there. This stops it from indexing your home directory by accident. See [Code indexing](code-indexing.md#project-detection).

If the project already has chats, you get a chat picker first:

```
Available chats for role 'code':
--------------------------------------------------
1. Add input validation to the login endpoint
2. Migrate the database layer to PostgreSQL
--------------------------------------------------

Options: <number> to select, 'n' for new chat, 'del <number>' to delete, 'del all' to delete all
```

### Keys in the chat

| Key | Action |
|---|---|
| **Enter** | New line (the prompt is multi-line) |
| **Esc then Enter** | Send the message |
| **Ctrl+C** at the prompt | Back to the chat picker |
| **Ctrl+C** in the chat picker | Exit |
| **Ctrl+C** while the agent works | Interrupt the current turn |
| **Ctrl+D**, `exit`, `quit` | Leave |

### What happens on each message

1. The code index is refreshed (incremental, so cheap when nothing changed).
2. The working tree is snapshotted if it has uncommitted changes.
3. The agent works, calling tools. Shell commands ask for approval unless they are read-only or you whitelisted them.
4. The agent's changes are committed to the private repo in `.raggie/git/`.
5. Code health stats are shown.

### One-shot mode

```bash
raggie code . --prompt "Refactor the API router to use dependency injection"
```

Runs a single turn and exits. It continues the most recent chat for the role, or starts a new one if there is none. Add `--effort 3` to raise the [thinking mode](planning-and-subagents.md#thinking-modes) for that run.

## `@file` references

Type `@path/to/file.py:10-25` (or a single line, `@path/to/file.py:10`) anywhere in a prompt. Raggie appends the referenced lines to the message, numbered, before it goes to the model:

```
❯ fix the off-by-one in @src/app.py:48-52
```

Rules:

- Paths are relative to the project directory.
- The `:line` part is required. A bare `@src/app.py` is left as plain text.
- Missing files, emails like `user@example.com`, and handles are left untouched.
- Reversed ranges (`:5-3`) are normalized, ranges past the end of the file are clamped.
- The same reference used twice is expanded once.

## Running shell commands yourself

Prefix a line with `!` to run it directly in the project directory, without going through the model:

```
❯ !git status
```

## Undo

Every agent turn that changed files ends with a snapshot commit. To roll it back:

```
❯ /undo
❯ /redo
```

`/undo` restores the project to the previous snapshot, `/redo` re-applies it. See [Undo and history](undo-and-history.md).

## Other ways to run it

- **Browser**: `raggie code --web`. See [Web UI](web-ui.md).
- **Zed and other ACP editors**: `raggie --acp-stdio`. See [ACP](acp.md).

## Next steps

- [Commands](commands.md) for the full command list
- [Planning and subagents](planning-and-subagents.md) for larger tasks
- [Configuration](configuration.md) to tune the model, context window and project conventions
