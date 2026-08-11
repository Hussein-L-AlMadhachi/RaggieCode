import * as vscode from "vscode";

export function activate(context: vscode.ExtensionContext): void {
  const disposable = vscode.commands.registerCommand(
    "copyRef.copySelection",
    async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.selection.isEmpty) {
        vscode.window.setStatusBarMessage("Nothing selected", 2000);
        return;
      }

      const relPath = vscode.workspace.asRelativePath(editor.document.uri);

      const { start, end } = editor.selection;
      // A selection ending at column 0 of a line does not visually include
      // that line, so reference the previous line instead.
      const endLine = end.character === 0 && end.line > start.line ? end.line - 1 : end.line;

      const ref =
        start.line === endLine
          ? `@${relPath}:${start.line + 1}`
          : `@${relPath}:${start.line + 1}-${endLine + 1}`;

      await vscode.env.clipboard.writeText(ref);
      vscode.window.setStatusBarMessage(`Copied ${ref}`, 2000);
    }
  );

  context.subscriptions.push(disposable);
}

export function deactivate(): void {}
