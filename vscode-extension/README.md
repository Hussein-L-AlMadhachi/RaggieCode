# Raggie Code Tools

Copy the current selection to the clipboard as `@path/to/file:23-43` (workspace-relative path, 1-based lines). Single-line selections produce `@path/to/file:23`.

## Usage

- Select text, then:
  - Right-click → **Copy Reference (@path:lines)**, or
  - `Ctrl+Alt+C` (`Cmd+Alt+C` on macOS)

## Development

```bash
npm install
npm run compile
```

Press `F5` in VSCode to launch an Extension Development Host.

## Package

```bash
npm run package   # requires: npm i -g @vscode/vsce
```

Install the produced `.vsix` via **Extensions: Install from VSIX...**
