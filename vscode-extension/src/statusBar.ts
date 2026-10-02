import * as vscode from "vscode";
import type { ServerState } from "./serverManager";

/** Actions the status bar menu can trigger; wired in extension.ts. */
export interface ServerActions {
  start: () => Thenable<void>;
  restart: () => Thenable<void>;
  stop: () => Thenable<void>;
}

export interface ServerMenuEntry {
  label: string;
  /** One-line explanation shown under the label in the menu. */
  detail: string;
  action: "start" | "restart" | "stop" | "openChat";
  /** Entries are grouped under a separator titled after the group. */
  group: "Agent" | "Chat";
}

/** Human-readable server status used in the menu header/placeholder. */
export function serverStatusLabel(
  state: ServerState,
  port?: number
): string {
  switch (state) {
    case "running":
      return port !== undefined
        ? `running on port ${port}`
        : "running";
    case "starting":
      return "starting...";
    case "error":
      return "stopped (last run failed)";
    default:
      return "stopped";
  }
}

/** Ordered menu entries for the given server state (pure; unit-tested). */
export function serverMenuEntries(state: ServerState): ServerMenuEntry[] {
  const server: ServerMenuEntry[] = [];
  if (state === "running" || state === "starting") {
    server.push(
      {
        label: "$(debug-restart) Restart Server",
        detail: "Stop the agent server and start it again.",
        action: "restart",
        group: "Agent",
      },
      {
        label: "$(debug-stop) Stop Server",
        detail: "Servers you started yourself are never killed.",
        action: "stop",
        group: "Agent",
      }
    );
  }
  if (state === "stopped" || state === "error") {
    server.push({
      label: "$(debug-start) Start Server",
      detail: "Launch the local agent server.",
      action: "start",
      group: "Agent",
    });
  }
  return [
    ...server,
    {
      label: "$(comment-discussion) Open Chat",
      detail: "Focus the Raggie chat panel.",
      action: "openChat",
      group: "Chat",
    },
  ];
}

export class RaggieStatusBar {
  private readonly item: vscode.StatusBarItem;
  private state: ServerState = "stopped";
  private port?: number;

  constructor(private readonly actions: ServerActions) {
    this.item = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      90
    );
    this.item.name = "Raggie Server";
    this.item.command = "raggie.manageServer";
    this.update("stopped");
    this.item.show();
  }

  /** Render text and color for the given state; port shown while running. */
  update(state: ServerState, port?: number): void {
    this.state = state;
    this.port = port;

    let text: string;
    let backgroundColor: vscode.ThemeColor | undefined;
    let tooltip: string;

    switch (state) {
      case "running": {
        const portSuffix = port !== undefined ? ` (${port})` : "";
        text = `Raggie: running${portSuffix}`;
        backgroundColor = undefined;
        tooltip = "The Raggie server is running. Click to manage it.";
        break;
      }
      case "starting":
        text = "Raggie: starting";
        // Raw theme color names: StatusBarItemColor enum is not in @types/vscode 1.85.
        backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
        tooltip = "The Raggie server is starting. Click to manage it.";
        break;
      case "error":
        text = "Raggie: error";
        backgroundColor = new vscode.ThemeColor("statusBarItem.errorBackground");
        tooltip = "The Raggie server reported an error. Click to manage it.";
        break;
      default:
        text = "Raggie: stopped";
        backgroundColor = undefined;
        tooltip = "The Raggie server is stopped. Click to manage it.";
        break;
    }

    this.item.text = text;
    this.item.backgroundColor = backgroundColor;
    this.item.tooltip = tooltip;
  }

  /** QuickPick menu shown when the status bar item is clicked. */
  showMenu(): void {
    const status = serverStatusLabel(this.state, this.port);
    type MenuItem = vscode.QuickPickItem & { entry?: ServerMenuEntry };
    const items: MenuItem[] = [];
    let currentGroup: string | undefined;

    for (const entry of serverMenuEntries(this.state)) {
      if (entry.group !== currentGroup) {
        currentGroup = entry.group;
        items.push({
          kind: vscode.QuickPickItemKind.Separator,
          label:
            currentGroup === "Agent"
              ? `Agent   server ${status}`
              : currentGroup,
        });
      }
      items.push({ label: entry.label, detail: entry.detail, entry });
    }

    void vscode.window
      .showQuickPick(items, {
        title: "Raggie",
        placeHolder: `Agent server ${status}. Pick an action.`,
      })
      .then((picked) => {
        if (!picked || !picked.entry) {
          return; // dismissed, or a separator header was picked
        }
        switch (picked.entry.action) {
          case "start":
            void this.actions.start();
            break;
          case "restart":
            void this.actions.restart();
            break;
          case "stop":
            void this.actions.stop();
            break;
          case "openChat":
            void vscode.commands.executeCommand("raggie.openChat");
            break;
        }
      });
  }

  dispose(): void {
    this.item.dispose();
  }
}
