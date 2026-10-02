# Contributing to Raggie Code

Thanks for your interest in improving Raggie. This guide covers how to set up a development environment, the project rules, and how to get a change merged.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Report a bug.** Open an issue with your OS, Python version, Raggie version (`pip show raggiecode`), the provider and model you used, the steps to reproduce, and what you expected to happen. Leave your API keys out of logs and screenshots.
- **Suggest a feature.** Open an issue describing the problem you want solved before writing code, so we can agree on the approach first.
- **Improve the docs.** Everything lives in [`docs/`](docs/README.md). Small fixes can go straight to a pull request.
- **Send code.** See below.

## Project layout

| Path | What it is | Tooling |
|---|---|---|
| `src/` | The Python agent, tools, commands, indexer and ACP server | Python 3.10+, pip |
| `web-ui/` | The Svelte 5 + TypeScript + Vite frontend | pnpm |
| `vscode-extension/` | The VS Code extension | pnpm |
| `docs/` | User and contributor documentation | Markdown |

For a full tour of the source tree, the agent loop and the event stream, read [Architecture](docs/architecture.md) before making non-trivial changes.

## Development setup

```bash
git clone https://github.com/Hussein-L-AlMadhachi/RaggieCode.git
cd RaggieCode

python -m venv .venv
source .venv/bin/activate
pip install -e .

raggie setup    # add an API key, pick a provider and model
```

Web UI:

```bash
cd web-ui
pnpm install
pnpm build      # the backend serves web-ui/dist
```

See [web-ui/README.md](web-ui/README.md) for running Vite's dev server with hot reload against a running backend.

### Use `--dev` while developing

Always run your development build with `--dev`:

```bash
raggie code . --dev
raggie code --web --dev
```

This makes Raggie use `.raggie-dev/` instead of `.raggie/`, so a broken build can never damage the chat history, index or undo snapshots of a real project.

## Project rules

These are hard rules. Pull requests that break them will not be merged.

### No recursion

**Never use recursion.** in Python. Recursion has been a source of abysmal performance and memory leaks in this project (deep trees from the indexer, call graphs and directory walks blow the stack and hold memory far longer than needed).

Use an explicit stack or queue and a loop instead:

```python
# Don't
def walk(node, out):
    out.append(node)
    for child in node.children:
        walk(child, out)

# Do
def walk(root):
    out = []
    stack = [root]
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(reversed(node.children))
    return out
```

If you find existing recursive code, a pull request converting it to iteration is welcome.

### Always use pnpm

Use **pnpm** for all JavaScript and TypeScript work. Don't commit `package-lock.json` or `yarn.lock` changes, and don't add dependencies with npm or yarn.

### Keep I/O behind `io_backend`

Agent, tool and command code must never read stdin or open its own console. Confirmations and questions go through `io_backend` (`confirm`, `confirm_with_always`, `ask`) so they work in the terminal, the web UI, VS Code and ACP editors alike. See the [`io_backend` specification](docs/io_backend.md).

## Common changes

### Adding a tool

1. Write the handler in `src/Tools/` (`handle(arguments, toolcall_id, ...)` returning a tool message dict).
2. Register it in `src/Tools/__init__.py`.
3. Add its schema to `src/config/tools.json`.
4. Add its name to the `tools` list of the roles that should have it.
5. Existing users have their own copies of the config files in `~/.config/raggie/`, so add a config migration in `src/Agent/migrations.py` that delivers the new schema to them.
6. Document it in [docs/tools.md](docs/tools.md).

### Adding an in-chat command

1. Write `handle(args, agent)` in a new module under `src/Commands/`. Return `""` when the command is fully handled, or a string to use as the prompt.
2. Register it in `src/Commands/__init__.py` with a description, and optionally a usage string and `choices`.
3. Document it in [docs/commands.md](docs/commands.md).

### Changing a config file schema

Never change the shape of a user config file without a migration. Add a `migrate_vN` function to `src/Agent/migrations.py` and register it in `MIGRATIONS`, following the instructions at the top of that file.

### Changing a database schema

Both SQLite databases are migrated with [yoyo](https://ollycope.com/software/yoyo/latest/). Add a new file, never edit an existing one:

- Chat database: `src/Agent/migrations/chat_db/`
- Code index: `src/indexing/migrations/index_db/`

Name it with a date prefix and a sequence number so it sorts after the existing ones, e.g. `20250108_01_short_description.py`. Start it with a docstring explaining the change, and make the steps idempotent (`IF NOT EXISTS`, guards) where SQLite allows it.

### Changing the web UI

After changing anything in `web-ui/src/`, rebuild with `pnpm build`. The backend serves the built files only. Run `python sync_webui.py` only when preparing a release; it copies the build into `src/acp_server/webui` for the pip package.

## Testing

The test suite is private and not part of this repository. Maintainers run it against every pull request before merging.

Before opening a pull request, run the checks for every part you touched:

```bash
cd web-ui
pnpm check                              # svelte-check + tsc
pnpm build

cd vscode-extension
pnpm run compile
```

Then try your change by hand with `raggie code . --dev`, and with `--web` if it affects the web UI or the event stream. Describe what you tried in the pull request so a maintainer can reproduce it.

## Code style

- Match the style of the surrounding code: naming, comment density, structure.
- Keep functions small. Raggie scores its own codebase with `/health`; don't make the numbers worse. See [Code health](docs/code-health.md).
- Write comments that explain *why*, not *what*.
- Don't add dependencies without discussing it in an issue first. Python dependencies are pinned in both `pyproject.toml` and `requirements.txt`; keep them in sync.
- Don't commit generated or local files: `web-ui/dist/`, `node_modules/`, `.raggie/`, `.raggie-dev/`, `*.vsix`, `.env` files.

## Pull requests

1. Fork the repository and create a branch from `main` with a descriptive name (`fix-handover-token-count`, `add-kotlin-indexing`).
2. Keep each pull request focused on one change. Separate refactors from behavior changes.
3. Write clear commit messages. A short imperative summary line (`fix: ...`, `feat: ...`, `refactor: ...` is welcome but not required), then a body explaining why if it isn't obvious.
4. Update the docs in `docs/` when you change user-visible behavior.
5. In the pull request description, explain what changed, why, and how you tested it. Include screenshots for UI changes.
6. Make sure `pnpm check` and the builds pass.

A maintainer will review your pull request. Expect questions and requested changes; that's a normal part of the process.

## License

Raggie Code is licensed under the [Apache License 2.0](LICENSE). By submitting a contribution, you agree that it is licensed under the same terms.
