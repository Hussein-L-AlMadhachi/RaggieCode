import * as vscode from "vscode";
import { spawn } from "node:child_process";
import { RaggieServerManager } from "./serverManager";
import { RaggieStatusBar } from "./statusBar";
import { ensureVenv, isVenvPlatform } from "./venvManager";
import { RaggieChatViewProvider, VIEW_ID } from "./webviewProvider";
import { registerCopySelection } from "./copyRef";
import {
  registerAskAboutSelection,
  registerMoveChatToSecondarySidebar,
  registerReloadUi,
  registerTurnOff,
  offerSecondarySidebarPin,
} from "./commands";

/**
 * Wraps a start/restart in a progress notification so the user sees feedback
 * while the readiness probe runs.
 */
function runWithProgress(
  title: string,
  action: () => Promise<void>
): Thenable<void> {
  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title },
    () => action()
  );
}

const INSTALL_BUTTON = "Install Raggie Code";

/**
 * True when the failure message looks like the raggie executable is missing
 * (spawn ENOENT or a shell "command not found" style message), which usually
 * means Raggie Code is not installed yet.
 */
function isLikelyMissingInstall(message: string): boolean {
  return /\bENOENT\b|not found|not recognized|no such file/i.test(message);
}

/**
 * Show the failure and, when the executable seems missing, an
 * "Install Raggie Code" button that runs `pip install raggiecode` and then
 * retries starting the server.
 */
async function offerInstallOnFailure(
  message: string,
  output: vscode.OutputChannel,
  serverManager: RaggieServerManager
): Promise<void> {
  const prompt = isLikelyMissingInstall(message) ? INSTALL_BUTTON : undefined;
  const choice = await vscode.window.showErrorMessage(
    message,
    ...(prompt ? [prompt] : [])
  );
  if (choice !== INSTALL_BUTTON) {
    return;
  }

  await runWithProgress("Installing Raggie Code...", async () => {
    // Abort early with a clear message when python/pip are missing instead
    // of failing with a cryptic spawn error.
    const missing = await findMissingPythonTools();
    if (missing.length > 0) {
      output.appendLine(`[raggie] missing required tools: ${missing.join(", ")}`);
      void vscode.window.showErrorMessage(missingToolsMessage(missing));
      return;
    }
    try {
      await pipInstallRaggieCode(output);
      void vscode.window.showInformationMessage(
        "Raggie Code installed. Starting the server..."
      );
      await serverManager.start();
    } catch (err) {
      void vscode.window.showErrorMessage(
        `Raggie Code installation failed: ${String(err)}`
      );
    }
  });
}

/** Install raggiecode: via the venv on linux/bsd, via system pip elsewhere. */
async function pipInstallRaggieCode(
  output: vscode.OutputChannel
): Promise<void> {
  // On venv platforms the venv creation includes installing raggiecode.
  if (isVenvPlatform()) {
    await ensureVenv(output);
    return;
  }
  return new Promise((resolve, reject) => {
    output.appendLine("[raggie] running: pip install raggiecode");
    output.show(true);

    const child = spawn("pip", ["install", "raggiecode"]);
    child.stdout?.on("data", (chunk: Buffer) => output.append(String(chunk)));
    child.stderr?.on("data", (chunk: Buffer) => output.append(String(chunk)));

    child.on("error", (err: Error) => {
      reject(err);
    });
    child.on("exit", (code: number | null) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`pip install raggiecode exited with code ${code}`));
      }
    });
  });
}

/**
 * Check whether a command is available by running `cmd --version`.
 * A spawn error (command not found) or a non-zero exit means it is missing.
 */
export function hasCommand(cmd: string): Promise<boolean> {
  return new Promise((resolve) => {
    const child = spawn(cmd, ["--version"], { stdio: "ignore" });
    child.on("error", () => resolve(false));
    child.on("exit", (code: number | null) => resolve(code === 0));
  });
}

/**
 * Returns the required tools that are not available on PATH. On venv
 * platforms only an interpreter (python3 or python) is required; pip comes
 * with the venv. Elsewhere both python and pip are required.
 */
export async function findMissingPythonTools(): Promise<string[]> {
  // On venv platforms pip is not required: it comes with the venv we create.
  if (isVenvPlatform()) {
    const hasPython =
      (await hasCommand("python3")) || (await hasCommand("python"));
    return hasPython ? [] : ["python3"];
  }
  const required = ["python", "pip"];
  const available = await Promise.all(required.map((tool) => hasCommand(tool)));
  const missing: string[] = [];
  for (let i = 0; i < required.length; i++) {
    if (!available[i]) {
      missing.push(required[i]);
    }
  }
  return missing;
}

/** User-facing explanation for the missing python/pip tools. */
export function missingToolsMessage(missing: string[]): string {
  if (isVenvPlatform()) {
    return "Raggie needs Python (python3 or python) to set up its environment, but none was found. Please install Python and restart VS Code, then try again.";
  }
  const list = missing.join(" and ");
  const verb = missing.length === 1 ? "it is" : "they are";
  return `Raggie Code needs ${list}, but ${verb} not installed. Please install Python (which includes pip) from https://www.python.org/downloads/ and restart VS Code, then try again.`;
}

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("Raggie Server");
  // First workspace folder when available, otherwise extension storage.
  const getCwd = () =>
    vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ??
    context.storageUri?.fsPath;

  const serverManager = new RaggieServerManager(output, getCwd);
  const statusBar = new RaggieStatusBar({
    start: () =>
      runWithProgress("Starting Raggie server...", () => serverManager.start()),
    restart: () =>
      runWithProgress("Restarting Raggie server...", () =>
        serverManager.restart()
      ),
    stop: () => serverManager.stop(),
  });
  // Hosts the web UI in the sidebar; it also kicks off a server start the
  // first time the view resolves.
  const chatProvider = new RaggieChatViewProvider(
    context.extensionUri,
    serverManager,
    output
  );

  // Keep the status bar in sync with the server lifecycle.
  serverManager.onStateChange((state) => statusBar.update(state, serverManager.port));

  // Surface unexpected failures once per incident. If the failure looks like
  // a missing executable (raggie not installed yet), offer to install it.
  serverManager.onError((message) => {
    void offerInstallOnFailure(message, output, serverManager);
  });

  const disposables: vscode.Disposable[] = [
    output,
    statusBar,
    serverManager,
    registerCopySelection(),
    registerAskAboutSelection(chatProvider),
    registerReloadUi(chatProvider),
    registerTurnOff(chatProvider, serverManager),
    vscode.window.registerWebviewViewProvider(VIEW_ID, chatProvider, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    // Status bar click: quick-pick menu for server management.
    vscode.commands.registerCommand("raggie.manageServer", () =>
      statusBar.showMenu()
    ),
    vscode.commands.registerCommand("raggie.startServer", () =>
      runWithProgress("Starting Raggie server...", () => serverManager.start())
    ),
    vscode.commands.registerCommand("raggie.restartServer", () =>
      runWithProgress("Restarting Raggie server...", () => serverManager.restart())
    ),
    vscode.commands.registerCommand("raggie.stopServer", () =>
      serverManager.stop()
    ),
    vscode.commands.registerCommand("raggie.openChat", async () => {
      await vscode.commands.executeCommand("raggie.chat.focus");
    }),
    registerMoveChatToSecondarySidebar(),
  ];
  context.subscriptions.push(...disposables);

  // Auto-start on activation when configured.
  const autoStart = vscode.workspace
    .getConfiguration("raggie")
    .get<boolean>("server.autoStart", true);
  if (autoStart) {
    void serverManager.start().catch(() => {
      // State and error message are already surfaced by the manager.
    });
  }

  // One-time offer to pin the chat to the secondary sidebar (next to
  // Copilot) instead of the activity bar. The answer is remembered.
  offerSecondarySidebarPin(context);
}

export function deactivate(): void {
  // Subscriptions (including the server manager) are disposed by VS Code.
}
