/**
 * Host side of the webview <-> local server bridge.
 *
 * The web UI posts {type:'raggie-http'|'raggie-stream', id, body} messages
 * (JSON-RPC payloads); this module forwards them to the Raggie server on
 * http://127.0.0.1:<port>/ and streams the replies back into the webview:
 *   - 'raggie-http-result'   {id, ok, status, json}
 *   - 'raggie-stream-frame'  {id, frame}
 *   - 'raggie-stream-end'    {id, ok, status}
 * A 'raggie-cancel-stream' message aborts a running stream request.
 */

import { extractSseFrames } from "./sse";

export interface BridgeHostDeps {
  /** Verified port of this window's server, or undefined while not running. */
  readonly getPort: () => number | undefined;
  /** Deliver a reply message into the webview. */
  readonly postToUi: (message: unknown) => void;
}

interface BridgeMessage {
  type?: unknown;
  id?: unknown;
  body?: unknown;
}

/** Validated request fields extracted from a bridge message. */
interface RequestArgs {
  id: number;
  body: string;
}

export function createBridgeHost(
  deps: BridgeHostDeps
): (data: unknown) => void {
  const streams = new Map<number, AbortController>();

  return (data: unknown) => {
    const msg = data as BridgeMessage;
    if (!msg || typeof msg.type !== "string") {
      return;
    }
    switch (msg.type) {
      case "raggie-http":
        void forwardHttp(msg, deps);
        break;
      case "raggie-stream":
        void forwardStream(msg, deps, streams);
        break;
      case "raggie-cancel-stream":
        cancelStream(msg, streams);
        break;
      default:
        // Unknown message types are ignored.
        break;
    }
  };
}

/** Extract {id, body}, rejecting malformed messages. */
function asRequestArgs(msg: BridgeMessage): RequestArgs | undefined {
  if (typeof msg.id !== "number" || typeof msg.body !== "string") {
    return undefined;
  }
  return { id: msg.id, body: msg.body };
}

function serverUrl(port: number): string {
  return `http://127.0.0.1:${port}/`;
}

/**
 * Shown by the UI when a request is attempted without a verified server.
 * Never fall back to the configured port here: while this window's server is
 * starting/stopped/errored, that port may belong to another window's project
 * instance, and hitting it would surface that project's chats in this window.
 */
const NOT_RUNNING_MESSAGE =
  "Raggie server is not running for this workspace. Start it from the Raggie status bar item.";

/** Forward a one-shot JSON-RPC request and reply with the parsed result. */
async function forwardHttp(
  msg: BridgeMessage,
  deps: BridgeHostDeps
): Promise<void> {
  const args = asRequestArgs(msg);
  if (!args) {
    return;
  }
  const port = deps.getPort();
  if (port === undefined) {
    deps.postToUi({
      type: "raggie-http-result",
      id: args.id,
      ok: false,
      status: 0,
      json: { message: NOT_RUNNING_MESSAGE },
    });
    return;
  }
  try {
    const res = await fetch(serverUrl(port), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: args.body,
    });
    const text = await res.text();
    deps.postToUi({
      type: "raggie-http-result",
      id: args.id,
      ok: res.ok,
      status: res.status,
      json: parseJsonLoose(text),
    });
  } catch (err) {
    deps.postToUi({
      type: "raggie-http-result",
      id: args.id,
      ok: false,
      status: 0,
      json: { message: String(err) },
    });
  }
}

/** JSON.parse that tolerates empty bodies and non-JSON payloads. */
function parseJsonLoose(text: string): unknown {
  if (text === "") {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

/** Forward an SSE request, relaying every frame, then a stream-end. */
async function forwardStream(
  msg: BridgeMessage,
  deps: BridgeHostDeps,
  streams: Map<number, AbortController>
): Promise<void> {
  const args = asRequestArgs(msg);
  if (!args) {
    return;
  }
  const port = deps.getPort();
  if (port === undefined) {
    deps.postToUi({
      type: "raggie-stream-end",
      id: args.id,
      ok: false,
      status: 0,
    });
    return;
  }
  const controller = new AbortController();
  streams.set(args.id, controller);
  try {
    const res = await fetch(serverUrl(port), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: args.body,
      signal: controller.signal,
    });
    if (!res.ok || !res.body) {
      deps.postToUi({
        type: "raggie-stream-end",
        id: args.id,
        ok: false,
        status: res.status,
      });
      return;
    }
    await pumpSse(res.body, (frame) => {
      deps.postToUi({ type: "raggie-stream-frame", id: args.id, frame });
    });
    deps.postToUi({
      type: "raggie-stream-end",
      id: args.id,
      ok: true,
      status: res.status,
    });
  } catch {
    // Network failure or abort; the UI treats this as a failed request.
    deps.postToUi({
      type: "raggie-stream-end",
      id: args.id,
      ok: false,
      status: 0,
    });
  } finally {
    streams.delete(args.id);
  }
}

/** Abort the stream registered under id, if any. */
function cancelStream(
  msg: BridgeMessage,
  streams: Map<number, AbortController>
): void {
  if (typeof msg.id !== "number") {
    return;
  }
  const controller = streams.get(msg.id);
  streams.delete(msg.id);
  controller?.abort();
}

/**
 * Iteratively read an SSE body and emit each parsed data frame.
 * Uses a plain reader loop, no recursion.
 */
async function pumpSse(
  body: ReadableStream<Uint8Array>,
  onFrame: (frame: unknown) => void
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const { frames, rest } = extractSseFrames(buffer);
    buffer = rest;
    for (const frame of frames) {
      onFrame(frame);
    }
  }
}


