<!-- TODO: replace with a real screenshot/gif before publishing, e.g. -->
<!-- ![Raggie chat in the secondary sidebar](images/chat-sidebar.png) -->

# Raggie Code

Raggie Code is your coding agent in VS Code: chat with an AI agent in a sidebar,
watch it edit your project, and copy selection references straight into the
conversation.

## Features

- **Sidebar chat**   a full agent chat UI inside VS Code. The server runs
  locally on your machine; nothing is sent through a third party.
- **Works next to Copilot**   pin the chat to the secondary sidebar so it
  sits beside Copilot's panel.
- **Selection references**   highlight code and send it to the chat as
  `@path/to/file:23-43`, so the agent knows exactly which lines you mean.
- **Permission-first tools**   file edits and commands surface as reviewable
  requests in the chat before they run.
- **Local server management**   start, restart, and stop the agent server
  from the status bar or the command palette.
- **Session history**   continue previous conversations or start fresh.

## Requirements

- Python 3.10 or newer.

You do not need to install anything else yourself. The extension gets the
`raggiecode` package for you:

- **Linux and BSD**: on first start it creates a private virtualenv at
  `~/.config/raggie/venv` and installs `raggiecode` into it automatically.
- **macOS and Windows**: if the `raggie` command is not found, a notification
  offers an **Install Raggie Code** button that runs `pip install raggiecode`
  and then starts the server.

To use your own install instead, point the extension at it via
`raggie.server.pythonPath`.

## Usage

1. Open your project workspace.
2. Click the Raggie icon in the activity bar (or run **Raggie Code: Open Chat**).
   The first open starts the server automatically (see
   `raggie.server.autoStart`).
3. Chat as usual. Permission requests, tool calls, and sessions all flow
   through the chat panel.

### Putting the chat next to Copilot

VS Code does not let extensions place a view in the secondary sidebar
directly, so on first activation the extension offers to pin it there.
Accept and pick "New Secondary Side Bar Entry" in the dialog that opens:
the chat moves to the secondary sidebar (right side, next to Copilot) and
the Raggie icon disappears from the activity bar. VS Code remembers this
location across sessions.

You can also do it any time later:

- Drag the Raggie icon from the activity bar onto the secondary sidebar, or
- run **Raggie Code: Move Chat to Secondary Sidebar** and pick
  "New Secondary Side Bar Entry".

**Raggie Code: Open Chat** then always focuses the chat right next to Copilot.

## Commands

| Command | Description |
| --- | --- |
| `Raggie Code: Open Chat` | Focus the chat view (wherever it currently lives). |
| `Raggie Code: Manage Server` | Open the server menu (same one shown when clicking the status bar item). |
| `Raggie Code: Move Chat to Secondary Sidebar` | Open the built-in move dialog pre-targeted at the chat; pick "New Secondary Side Bar Entry" to pin it next to Copilot. |
| `Raggie Code: Start Server` | Start the local Raggie server. |
| `Raggie Code: Restart Server` | Restart the local Raggie server. |
| `Raggie Code: Stop Server` | Stop the server (servers you started yourself are never killed). |
| `Raggie Code: Turn Off Agent and Close Panel` | Stop the agent and close the sidebar panel it lives in (also a stop button on the chat's title bar). |
| `Raggie Code: Ask About Selection` | Send the current editor selection (with a `@file:line` reference) into the chat. |
| `Copy Reference for Raggie Code` | Copy the current selection as `@path/to/file:23-43`. |

## Keybindings

These are active only while the editor has a selection:

| Keybinding | Action |
| --- | --- |
| `Ctrl+Alt+C` | Copy the current selection as a Raggie reference. |
| `Ctrl+Shift+Alt+R` | Ask Raggie about the current selection. |

On macOS use `Cmd` in place of `Ctrl`.

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `raggie.server.port` | `8765` | Port the local server listens on. |
| `raggie.server.pythonPath` | `raggie` | CLI executable; `raggie` resolves via PATH. |
| `raggie.server.role` | `code` | Agent role passed to the server. |
| `raggie.server.autoStart` | `true` | Start the server when the extension activates. |
| `raggie.server.args` | `[]` | Extra CLI arguments (e.g. `--dev`). |
| `raggie.chat.openOnStartup` | `false` | Open the chat view on activation. |

## License

Apache-2.0   see the `LICENSE` file bundled with the extension.
