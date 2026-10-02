import * as vscode from "vscode";

/**
 * Build the Raggie reference for the current selection:
 * "@path/to/file:23" or "@path/to/file:23-43" (1-based lines).
 * Returns undefined when the selection is empty.
 */
export function selectionReference(
  document: vscode.TextDocument,
  selection: vscode.Selection
): string | undefined {
  if (selection.isEmpty) {
    return undefined;
  }

  const relPath = vscode.workspace.asRelativePath(document.uri);

  const { start, end } = selection;
  // A selection ending at column 0 of a line does not visually include
  // that line, so reference the previous line instead.
  const endLine =
    end.character === 0 && end.line > start.line ? end.line - 1 : end.line;

  if (start.line === endLine) {
    return `@${relPath}:${start.line + 1}`;
  }
  return `@${relPath}:${start.line + 1}-${endLine + 1}`;
}

export function registerCopySelection(): vscode.Disposable {
  return vscode.commands.registerCommand("copyRef.copySelection", async () => {
    const editor = vscode.window.activeTextEditor;
    const ref = editor
      ? selectionReference(editor.document, editor.selection)
      : undefined;
    if (!ref) {
      vscode.window.setStatusBarMessage("Nothing selected", 2000);
      return;
    }

    await vscode.env.clipboard.writeText(ref);
    vscode.window.setStatusBarMessage(`Copied ${ref}`, 2000);
  });
}
