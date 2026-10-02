import * as vscode from "vscode";
import { selectionReference } from "./copyRef";
import type { RaggieServerManager } from "./serverManager";
import { VIEW_ID, type RaggieChatViewProvider } from "./webviewProvider";

/** Grace period after focusing the view before retrying the prompt handoff. */
const DELIVERY_RETRY_MS = 500;

/** How long to wait for the view to hide after closing the secondary bar. */
const HIDE_CONFIRM_MS = 400;

/** Registers raggie.askAboutSelection: sends the selection to the chat UI. */
export function registerAskAboutSelection(
  provider: RaggieChatViewProvider
): vscode.Disposable {
  return vscode.commands.registerCommand(
    "raggie.askAboutSelection",
    () => askAboutSelection(provider)
  );
}

/** Registers raggie.moveChatToSecondarySidebar. */
/** Registers raggie.moveChatToSecondarySidebar. */
export function registerReloadUi(
  provider: RaggieChatViewProvider
): vscode.Disposable {
  return vscode.commands.registerCommand(
    "raggie.reloadUi",
    () => provider.reloadUi()
  );
}

export function registerMoveChatToSecondarySidebar(): vscode.Disposable {
  return vscode.commands.registerCommand(
    "raggie.moveChatToSecondarySidebar",
    pinChatToSecondarySidebar
  );
}

/** Registers raggie.turnOff: stop the agent server and close its panel. */
export function registerTurnOff(
  provider: RaggieChatViewProvider,
  serverManager: RaggieServerManager
): vscode.Disposable {
  return vscode.commands.registerCommand(
    "raggie.turnOff",
    () => turnOff(provider, serverManager)
  );
}

async function turnOff(
  provider: RaggieChatViewProvider,
  serverManager: RaggieServerManager
): Promise<void> {
  await serverManager.stop();

  // Panel already closed (or never opened): nothing to hide.
  if (!provider.isViewVisible()) {
    return;
  }

  // Close the secondary sidebar (where Raggie lives after pinning). If the
  // view did not hide within the grace period, it lives in the primary
  // sidebar instead, so close that one. Closing only the panel that hosts
  // the chat avoids hiding the Explorer on the primary side.
  const hidden = provider.waitHidden(HIDE_CONFIRM_MS);
  await vscode.commands.executeCommand("workbench.action.closeAuxiliaryBar");
  if (!(await hidden)) {
    await vscode.commands.executeCommand("workbench.action.closeSidebar");
  }
}

/**
 * Focus the chat view and open the built-in move dialog pre-targeted at it.
 * VS Code has no silent "move view" command; passing the view id skips the
 * view picker, so only the destination picker appears. Picking
 * "New Secondary Side Bar Entry" pins the chat next to Copilot, and the
 * location is remembered across sessions. The original activity bar
 * container disappears once it has no views left.
 */
export async function pinChatToSecondarySidebar(): Promise<void> {
  await vscode.commands.executeCommand("raggie.chat.focus");
  await vscode.commands.executeCommand(
    "workbench.action.moveFocusedView",
    VIEW_ID
  );
}

/**
 * One-time offer on first activation: pin the chat to the secondary sidebar
 * (where Copilot Chat lives) instead of the activity bar. Either answer is
 * remembered so the prompt never shows again.
 */
export function offerSecondarySidebarPin(
  context: vscode.ExtensionContext
): void {
  const promptedKey = "raggie.pinnedToSecondarySidebarOffered";
  if (context.globalState.get<boolean>(promptedKey) === true) {
    return;
  }
  void (async () => {
    await context.globalState.update(promptedKey, true);
    const choice = await vscode.window.showInformationMessage(
      "Pin the Raggie chat to the secondary sidebar (next to Copilot)?",
      "Pin to Secondary Sidebar",
      "Keep in Activity Bar"
    );
    if (choice !== "Pin to Secondary Sidebar") {
      return;
    }
    try {
      await pinChatToSecondarySidebar();
    } catch {
      // The built-in move dialog may not exist in future VS Code versions.
      await vscode.window.showInformationMessage(
        "Could not open the move dialog. Drag the Raggie icon onto the secondary sidebar instead."
      );
    }
  })();
}

async function askAboutSelection(
  provider: RaggieChatViewProvider
): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  const ref = editor
    ? selectionReference(editor.document, editor.selection)
    : undefined;
  if (!editor || !ref) {
    vscode.window.setStatusBarMessage("Nothing selected", 2000);
    return;
  }

  const prompt = buildPrompt(editor.document, editor.selection, ref);

  if (provider.postToUi({ type: "raggie-prompt", text: prompt })) {
    await vscode.commands.executeCommand("raggie.chat.focus");
    return;
  }

  // The view is not resolved yet: focus it, then retry once.
  await vscode.commands.executeCommand("raggie.chat.focus");
  await delay(DELIVERY_RETRY_MS);
  if (provider.postToUi({ type: "raggie-prompt", text: prompt })) {
    return;
  }
  void vscode.window.showInformationMessage(
    "The Raggie chat is still loading. Open the Raggie view and try again."
  );
}

/** Reference prefix plus the selection as a fenced code block. */
function buildPrompt(
  document: vscode.TextDocument,
  selection: vscode.Selection,
  ref: string
): string {
  const code = document.getText(selection);
  return `${ref}\n\`\`\`${document.languageId}\n${code}\n\`\`\``;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
