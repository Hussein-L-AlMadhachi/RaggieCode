# Raggie Code

> *Raggie Code v1.0.1*

<p style="padding:30px 50px;">
  <img src="Raggie.png" alt="Raggie" width="312">
</p>

**Raggie** is an autonomous AI coding agent that doesn't just read your codebase. It *understands* it.

Most AI coding assistants dump file contents into a prompt and hope for the best. Raggie builds a **semantic index** of your codebase with tree-sitter, navigates **call graphs**, traces **dependency chains**, and uses that structure to make surgical, context-aware changes.

- **Understands code structure**: symbols, imports, callers and callees across 15 languages, plus HTML, CSS, Vue and Svelte.
- **Plans before it acts**: todo lists you approve, executed one task at a time by isolated subagents.
- **Survives long tasks**: automatic context handover to a fresh session, and crash recovery that resumes interrupted tool calls.
- **Safe by design**: every change is snapshotted in a private git repo (`/undo`, `/redo`), shell commands need your approval, ignored files stay off limits.
- **Works with your stack**: any OpenAI-compatible LLM, local or cloud. Terminal, built-in web UI, VS Code extension, or any ACP editor such as Zed. External tools over MCP.
- **Runs locally**: the code index, chat history and snapshot repo never leave your machine.

## Install

### VS Code extension (recommended)

1. Install **Raggie Code** from the VS Code Extensions view.
2. Open your project and click the Raggie icon.

That's it. The extension installs the `raggiecode` Python package for you, starts the agent, and shows a setup page for your API key and model. You only need Python 3.10+ on your machine. See [Getting started](docs/getting-started.md#vs-code-extension-recommended).

for some reason if that failed just run `pip install raggiecode` in the terminal to install the `raggiecode` python package manually.

### Command line

```bash
pip install raggiecode
```

Or from source:

```bash
git clone https://github.com/Hussein-L-AlMadhachi/RaggieCode.git
cd RaggieCode
pip install .
```

Requires Python 3.10+ and an API key for an OpenAI-compatible provider (or a local model server).

## Quick start

With the extension, just open the chat. From a terminal:

```bash
raggie setup            # add an API key, pick a provider and model
raggie code .           # interactive chat in the current project
raggie code --web       # same agent, in your browser
raggie code . --prompt "Add input validation to the login endpoint"
```

In the terminal chat, press **Esc then Enter** to send. Type `/help` for the in-chat commands, `/undo` to roll back the agent's last change.

Point at exact lines with `@path/to/file.py:10-25` anywhere in your prompt.

## See it in action

```
$ raggie code .

Raggie Agent (code) v1.0.1 - Interactive Mode
--------------------------------------------------

Thinking mode: Zen - to change it use /thinkingMode

Press Esc followed by Enter to send message, or type 'exit' to quit

You:
❯ Add input validation to the login endpoint and update all callers

Agent (deepseek-v4-flash:0):
I'll start by finding the login endpoint and tracing its callers.

[tool] GetSymbolSourceCode(symbol_name=login)
[tool] WalkCallTree(symbol_name=login, max_depth=3)
[tool] EditSymbol(symbol_name=login, new_source=...)
[tool] ReplaceText(file_path=src/api/routes.py, ...)
[tool] Shell(command=python -m pytest tests/test_auth.py)

All 3 callers updated and tests pass.

tracking changes...
type /undo to undo the last code changes
```

## Documentation

Everything lives in [`docs/`](docs/README.md).

| | |
|---|---|
| [Getting started](docs/getting-started.md) | VS Code extension, command-line install, setup, first session, `@file` references, `/undo` |
| [Commands](docs/commands.md) | All CLI commands and in-chat slash commands |
| [Configuration](docs/configuration.md) | Config files, `roles.json`, providers, `AGENTS.md`, ignore files |
| [Local models](docs/local-models.md) | Ollama, vLLM, LM Studio and other local servers |
| [Planning and subagents](docs/planning-and-subagents.md) | Thinking modes, todo lists, subagents, handover, crash recovery |
| [Tools](docs/tools.md) | The 32 built-in tools and how permissions work |
| [Skills](docs/skills.md) | Skills system, Agent Skills format, auto-discovery |
| [Code indexing](docs/code-indexing.md) | Languages, project detection, performance |
| [Undo and history](docs/undo-and-history.md) | `.raggie/git`, `/undo`, `/redo`, crash safety |
| [Code health](docs/code-health.md) | Complexity score, class bloat, `/health` report |
| [Web UI](docs/web-ui.md) | The built-in web UI |
| [ACP](docs/acp.md) | Zed and other editors over ACP |
| [MCP](docs/mcp.md) | External MCP servers |
| [Architecture](docs/architecture.md) | Source layout and agent loop, for contributors |
| [FAQ](docs/faq.md) | |

## License

```
Copyright 2026 Hussein Al-Madhachi

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
