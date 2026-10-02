import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";
import { createBridgeHost } from "./bridgeHost";
import { RaggieServerManager } from "./serverManager";

const VIEW_ID = "raggie.chat";

/** Data needed to rewrite UI assets onto webview URIs. */
interface RewriteCtx {
  webview: vscode.Webview;
  uiDir: vscode.Uri;
  nonce: string;
}

/**
 * Hosts the built web UI (../web-ui/dist) in the Raggie sidebar view and
 * bridges its postMessage transport to the local Raggie server.
 */
export class RaggieChatViewProvider implements vscode.WebviewViewProvider {
  private view: vscode.WebviewView | undefined;
  private autoStartKicked = false;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly serverManager: RaggieServerManager,
    private readonly output: vscode.OutputChannel
  ) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    this.kickAutoStart();

    // Wire the bridge before the UI loads so early messages are not lost.
    // The handler is scoped to this webview, so replies only ever go back
    // to the webview that sent the request.
    view.webview.onDidReceiveMessage(
      createBridgeHost({
        getPort: () => this.serverManager.port,
        postToUi: (message) => this.postToUi(message),
      })
    );

    void this.loadUi(view);
  }

  /** Post a host message into the web UI (e.g. 'raggie-prompt').
   * Returns false when the view is not resolved yet.
   */
  postToUi(message: unknown): boolean {
    const webview = this.view?.webview;
    if (!webview) {
      return false;
    }
    try {
      void webview.postMessage(message).then(
        undefined,
        () => {
          /* view disposed */
        }
      );
      return true;
    } catch {
      return false;
    }
  }

  /** Whether the chat view is currently visible in the workbench. */
  isViewVisible(): boolean {
    return this.view?.visible ?? false;
  }

  /**
   * Resolve true when the view hides within timeoutMs, false otherwise.
   * Used to tell which panel the view was closed from (secondary sidebar
   * vs primary sidebar) after running a built-in close command.
   */
  waitHidden(timeoutMs: number): Promise<boolean> {
    const view = this.view;
    if (!view) {
      return Promise.resolve(false);
    }
    return new Promise((resolve) => {
      const listener = view.onDidChangeVisibility(() => {
        // The event carries no payload; read visibility off the view.
        if (!view.visible) {
          listener.dispose();
          resolve(true);
        }
      });
      setTimeout(() => {
        listener.dispose();
        resolve(false);
      }, timeoutMs);
    });
  }

  /** Start the server once, the first time the view is shown. */
  /**
   * Start the server on the first show and on every reopen. start() is a
   * no-op while already starting or running, so repeated shows are free.
   * Honors raggie.server.autoStart for users who want manual control.
   */
  private kickAutoStart(): void {
    if (!this.autoStartKicked) {
      this.autoStartKicked = true;
      // The visibility event carries no payload; check view.visible directly.
      this.view?.onDidChangeVisibility(() => {
        if (this.view?.visible) {
          this.startServerSoon();
        }
      });
    }
    this.startServerSoon();
  }

  /** Kick off a server start shortly after the panel becomes visible. */
  private startServerSoon(): void {
    if (!vscode.workspace.getConfiguration("raggie").get<boolean>("server.autoStart", true)) {
      return;
    }
    // Small delay lets the panel finish showing before the probe starts.
    setTimeout(() => {
      void this.serverManager.start().catch(() => {
        /* surfaced by the manager */
      });
    }, 50);
  }

  /** Re-render the webview HTML, effectively reloading the embedded UI. */
  reloadUi(): void {
    if (this.view) {
      void this.loadUi(this.view);
    }
  }

  private async loadUi(view: vscode.WebviewView): Promise<void> {
    const uiDir = await findUiDir(this.extensionUri, this.output);
    if (!uiDir) {
      view.webview.html = errorHtml();
      return;
    }
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [uiDir],
    };
    try {
      view.webview.html = await buildHtml(view.webview, uiDir);
    } catch (err) {
      this.output.appendLine(`[raggie] failed to load UI: ${String(err)}`);
      view.webview.html = errorHtml(String(err));
    }
  }
}

/**
 * Locate the built web UI. The first candidate containing index.html wins:
 *   1. <extdir>/media/ui        (packaged builds)
 *   2. <extdir>/../web-ui/dist  (dev: web-ui lives next to vscode-extension)
 */
async function findUiDir(
  extensionUri: vscode.Uri,
  output: vscode.OutputChannel
): Promise<vscode.Uri | undefined> {
  const candidates: Array<{ dir: vscode.Uri; source: string }> = [
    {
      dir: vscode.Uri.joinPath(extensionUri, "media", "ui"),
      source: "packaged (media/ui)",
    },
    {
      dir: vscode.Uri.joinPath(extensionUri, "..", "web-ui", "dist"),
      source: "dev fallback (../web-ui/dist)",
    },
    {
      dir: vscode.Uri.joinPath(extensionUri, "..", "..", "web-ui", "dist"),
      source: "dev fallback (../../web-ui/dist)",
    },
  ];
  for (const candidate of candidates) {
    if (
      await isFile(vscode.Uri.joinPath(candidate.dir, "index.html"))
    ) {
      output.appendLine(
        `[raggie] UI assets: ${candidate.dir.fsPath} (${candidate.source})`
      );
      return candidate.dir;
    }
  }
  output.appendLine(
    "[raggie] UI assets: none found; showing build instructions"
  );
  return undefined;
}

async function isFile(uri: vscode.Uri): Promise<boolean> {
  try {
    return (await fs.promises.stat(uri.fsPath)).isFile();
  } catch {
    return false;
  }
}

/** Read index.html and rewrite it for the webview sandbox. */
async function buildHtml(
  webview: vscode.Webview,
  uiDir: vscode.Uri
): Promise<string> {
  const ctx: RewriteCtx = {
    webview,
    uiDir,
    nonce: crypto.randomBytes(16).toString("hex"),
  };
  let html = await fs.promises.readFile(
    path.join(uiDir.fsPath, "index.html"),
    "utf8"
  );
  // Stamp hosted mode directly onto <html> so the bundled hosted-layout
  // CSS (app.css 'html.vscode-host' rules) applies even if the UI's own
  // runtime detection never runs. The standalone app never goes through
  // this rewrite, so the browser build is unaffected.
  html = html.replace(/<html\b([^>]*)>/i, (tag, attrs: string) =>
    /\bclass\s*=/.test(attrs)
      ? tag
      : `<html${attrs} class="vscode-host">`
  );
  html = rewriteScripts(html, ctx);
  html = await rewriteLinks(html, ctx);
  return injectHead(html, ctx, webview.cspSource);
}

/**
 * Hosted layout rules injected by the extension itself, independent of the
 * UI's own stylesheet. The !important values force the app to fill the
 * webview edge-to-edge even if a stale or missing app bundle would render
 * the browser-style "window card" (capped width, auto margins, page
 * backdrop). The app's .window class is Svelte-scoped, but the raw class
 * name is still present on the element, so the plain selector matches.
 */
function hostedLayoutStyle(): string {
  const css = [
    "html.vscode-host,html.vscode-host body,html.vscode-host #app{width:100%!important;height:100%!important;margin:0!important;padding:0!important;border:0!important;overflow:hidden!important}",
    "html.vscode-host body,html.vscode-host #app{background:var(--bg,#fff)!important}",
    "html.vscode-host .window{width:100%!important;height:100%!important;margin:0!important;border:none!important}",
  ].join("");
  return `<style>${css}</style>`;
}

/** Point local script sources at webview URIs and nonce every script tag. */
function rewriteScripts(html: string, ctx: RewriteCtx): string {
  return html.replace(/<script\b[^>]*>/g, (tag) => {
    let next = removeAttr(tag, "crossorigin");
    const src = getAttr(next, "src");
    if (src && isLocalRef(src)) {
      next = setAttr(next, "src", toWebviewUri(ctx, src).toString());
    }
    return setAttr(next, "nonce", ctx.nonce);
  });
}

/**
 * Rewrite <link> tags. Local stylesheets are inlined as <style> with their
 * url() references rewritten to webview URIs, so relative asset resolution
 * inside CSS cannot break. External links (fonts.googleapis.com) are left
 * untouched.
 */
async function rewriteLinks(html: string, ctx: RewriteCtx): Promise<string> {
  const matches = [...html.matchAll(/<link\b[^>]*>/g)];
  if (matches.length === 0) {
    return html;
  }
  const parts: string[] = [];
  let last = 0;
  for (const match of matches) {
    const start = match.index ?? 0;
    const end = start + match[0].length;
    parts.push(html.slice(last, start));
    parts.push(await rewriteLink(match[0], ctx));
    last = end;
  }
  parts.push(html.slice(last));
  return parts.join("");
}

async function rewriteLink(
  tag: string,
  ctx: RewriteCtx
): Promise<string> {
  const href = getAttr(tag, "href");
  if (!href || !isLocalRef(href)) {
    return tag; // External (fonts) and protocol links stay as-is.
  }
  const rel = getAttr(tag, "rel")?.toLowerCase() ?? "";
  if (rel.split(/\s+/).includes("stylesheet")) {
    return inlineStylesheet(tag, ctx, href);
  }
  return setAttr(tag, "href", toWebviewUri(ctx, href).toString());
}

/** Replace a local stylesheet link with an inlined, rewritten <style>. */
async function inlineStylesheet(
  tag: string,
  ctx: RewriteCtx,
  href: string
): Promise<string> {
  const file = resolveLocal(ctx.uiDir, href);
  let css: string;
  try {
    css = await fs.promises.readFile(file, "utf8");
  } catch {
    // Unreadable stylesheet: fall back to a plain webview URI link.
    return setAttr(tag, "href", toWebviewUri(ctx, href).toString());
  }
  css = rewriteCssUrls(css, ctx, path.dirname(file));
  css = css.replace(/<\/style/gi, "<\\/style"); // keep the block intact
  return `<style nonce="${ctx.nonce}">${css}</style>`;
}

/** Rewrite local url() references in CSS to webview resource URIs. */
function rewriteCssUrls(
  css: string,
  ctx: RewriteCtx,
  cssDir: string
): string {
  return css.replace(
    /url\(\s*(['"]?)([^'")]+)\1\s*\)/g,
    (match, _quote: string, ref: string) => {
      if (!isLocalRef(ref)) {
        return match;
      }
      const abs = path.resolve(cssDir, ref);
      if (!fs.existsSync(abs)) {
        return match;
      }
      const uri = ctx.webview.asWebviewUri(vscode.Uri.file(abs));
      return `url("${uri.toString()}")`;
    }
  );
}

/** Prepend the CSP meta tag and the bridge bootstrap script to <head>. */
function injectHead(
  html: string,
  ctx: RewriteCtx,
  cspSource: string
): string {
  const head = html.match(/<head\b[^>]*>/i);
  const injection = `${cspMeta(ctx, cspSource)}${hostedLayoutStyle()}${bridgeTag(ctx)}`;
  if (!head || head.index === undefined) {
    return `${injection}${html}`;
  }
  const at = head.index + head[0].length;
  return `${html.slice(0, at)}${injection}${html.slice(at)}`;
}

function cspMeta(ctx: RewriteCtx, cspSource: string): string {
  const policy = [
    "default-src 'none'",
    `img-src ${cspSource} https: data:`,
    `script-src 'nonce-${ctx.nonce}'`,
    `style-src ${cspSource} https://fonts.googleapis.com 'unsafe-inline'`,
    `font-src ${cspSource} https://fonts.gstatic.com`,
    "connect-src 'none'",
  ].join("; ");
  return `<meta http-equiv="Content-Security-Policy" content="${escapeHtml(policy)}">`;
}

/** The inline bootstrap script: acquire the api and relay host actions. */
function bridgeTag(ctx: RewriteCtx): string {
  const script = `"use strict";
(function () {
  if (typeof acquireVsCodeApi !== "function") { return; }
  var api = acquireVsCodeApi();
  window.parentHost = api;
  // acquireVsCodeApi is single-use; re-expose it so the web UI bridge can
  // call it later and reach the same api instance.
  window.acquireVsCodeApi = function () { return api; };
  // Host-injected actions are re-posted onto window for the web-ui bridge,
  // which listens for window "message" events.
  window.addEventListener("message", function (ev) {
    var msg = ev.data;
    if (!msg || typeof msg !== "object" || typeof msg.type !== "string") { return; }
    if (msg.type === "raggie-prompt" || msg.type === "raggie-open-setup") {
      window.dispatchEvent(new MessageEvent("message", { data: msg }));
    }
  });
})();`;
  return `<script nonce="${ctx.nonce}">${script}</script>`;
}

/** Inline fallback shown when the built web UI is missing. */
function errorHtml(details?: string): string {
  const tail = details
    ? `<p style="font-size: 12px; opacity: 0.8;">Details: ${escapeHtml(details)}</p>`
    : "";
  return `<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Raggie Code</title></head>
<body style="font-family: sans-serif; color: var(--vscode-foreground); background: var(--vscode-editor-background); padding: 12px; line-height: 1.5;">
  <h2 style="font-size: 14px; font-weight: 600;">Raggie chat UI is not built</h2>
  <p style="font-size: 13px;">The extension could not find the built web UI (web-ui/dist).</p>
  <p style="font-size: 13px;">Build the web UI with:</p>
  <pre style="background: var(--vscode-textCodeBlock-background); padding: 8px; font-size: 12px;">cd web-ui
pnpm install
pnpm build</pre>
  <p style="font-size: 12px; opacity: 0.8;">Then reload the window (Developer: Reload Window).</p>
  ${tail}
</body>
</html>`;
}

/** Map a path relative to the UI dir onto a webview resource URI. */
function toWebviewUri(ctx: RewriteCtx, ref: string): vscode.Uri {
  return ctx.webview.asWebviewUri(vscode.Uri.file(resolveLocal(ctx.uiDir, ref)));
}

/** Resolve a relative reference (query/hash stripped) inside the UI dir. */
function resolveLocal(uiDir: vscode.Uri, ref: string): string {
  const clean = ref.split("#")[0].split("?")[0];
  return path.resolve(uiDir.fsPath, clean);
}

/** True for relative references that can map to local files. */
function isLocalRef(ref: string): boolean {
  const value = ref.trim();
  return (
    value !== "" &&
    !/^[a-z][a-z0-9+.-]*:/i.test(value) &&
    !value.startsWith("/") &&
    !value.startsWith("#")
  );
}

function getAttr(tag: string, name: string): string | undefined {
  const match = new RegExp(
    `\\b${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s"'>]+))`,
    "i"
  ).exec(tag);
  if (!match) {
    return undefined;
  }
  return match[1] ?? match[2] ?? match[3];
}

function setAttr(tag: string, name: string, value: string): string {
  const re = new RegExp(`\\s${name}\\s*=\\s*("[^"]*"|'[^']*'|[^\\s>]+)`, "i");
  if (re.test(tag)) {
    return tag.replace(re, () => ` ${name}="${value}"`);
  }
  return tag.replace(/\s*\/?>$/, () => ` ${name}="${value}">`);
}

function removeAttr(tag: string, name: string): string {
  return tag.replace(
    new RegExp(`\\s+${name}(\\s*=\\s*("[^"]*"|'[^']*'|[^\\s>]+))?`, "i"),
    ""
  );
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export { VIEW_ID };
