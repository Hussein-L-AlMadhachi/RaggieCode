// Transport layer for agent-server requests.
// Standalone browser: plain fetch('/') as before.
// VS Code webview: requests are forwarded to the extension host via
// postMessage, which performs the HTTP call (webviews cannot reach the local
// agent server directly).

interface VsCodeApi {
  postMessage(msg: unknown): void;
}

type Pending =
  | {
      kind: 'http';
      method: string;
      resolve: (json: any) => void;
      reject: (err: Error) => void;
    }
  | {
      kind: 'stream';
      method: string;
      onFrame: (frame: any) => void;
      resolve: () => void;
      reject: (err: Error) => void;
    };

let vscodeApi: VsCodeApi | undefined;
let nextMsgId = 0;
const pending = new Map<number, Pending>();
const hostHandlers: Array<(msg: any) => void> = [];
let listenerReady = false;

// Session id from the web UI's own URL (?sid=<hex>). Empty in vscode-host mode,
// where window.location.search is blank.
const SID =
  new URLSearchParams(window.location?.search ?? '').get('sid') ?? '';

function withSid(body: string): string {
  if (!SID) return body;
  try {
    const msg = JSON.parse(body) as Record<string, any>;
    msg.params = { ...(msg.params ?? {}), sid: SID };
    return JSON.stringify(msg);
  } catch {
    return body;
  }
}

const REPLY_TYPES = new Set([
  'raggie-http-result',
  'raggie-stream-frame',
  'raggie-stream-end',
]);

export function isVsCodeHost(): boolean {
  return typeof (window as any).acquireVsCodeApi === 'function';
}

// acquireVsCodeApi() throws when called twice, so the api is fetched once
// and cached.
export function getVsCodeApi(): VsCodeApi | undefined {
  if (!isVsCodeHost()) return undefined;
  if (!vscodeApi) {
    vscodeApi = (window as any).acquireVsCodeApi() as VsCodeApi;
  }
  return vscodeApi;
}

// Register a handler for messages pushed by the host (e.g. prompt injection).
// No-op in standalone mode since there is no host.
export function onHostMessage(handler: (msg: any) => void): void {
  if (!isVsCodeHost()) return;
  ensureListener();
  hostHandlers.push(handler);
}

// Send a JSON-RPC body and resolve with the parsed JSON response.
export function transportPost(body: string): Promise<any> {
  body = withSid(body);
  const api = getVsCodeApi();
  if (api) {
    ensureListener();
    const id = ++nextMsgId;
    return new Promise((resolve, reject) => {
      pending.set(id, { kind: 'http', method: methodOf(body), resolve, reject });
      api.postMessage({ type: 'raggie-http', id, body });
    });
  }
  return fetchPost(body);
}

// Send a JSON-RPC body whose response is an SSE stream. Calls onFrame for
// each parsed `data:` payload; resolves when the response frame (a frame
// carrying an id) arrives or the stream ends.
export function transportStream<T = unknown>(
  body: string,
  onFrame: (frame: T) => void,
): Promise<void> {
  body = withSid(body);
  const api = getVsCodeApi();
  if (api) {
    ensureListener();
    const id = ++nextMsgId;
    return new Promise((resolve, reject) => {
      pending.set(id, {
        kind: 'stream',
        method: methodOf(body),
        onFrame,
        resolve,
        reject,
      });
      api.postMessage({ type: 'raggie-stream', id, body });
    });
  }
  return fetchStream(body, onFrame);
}

function httpError(status: number, method: string, bodyText: string): Error {
  const err = new Error(`HTTP ${status} for ${method}`);
  (err as any).status = status;
  (err as any).bodyText = bodyText;
  return err;
}

// Best-effort extraction of the JSON-RPC method for error messages.
function methodOf(body: string): string {
  try {
    return (JSON.parse(body) as any).method ?? '';
  } catch {
    return '';
  }
}

// Single message listener dispatching both transport replies and
// host-initiated messages.
function ensureListener(): void {
  if (listenerReady) return;
  listenerReady = true;
  window.addEventListener('message', (ev: MessageEvent) => {
    const msg = ev.data as any;
    if (!msg || typeof msg !== 'object' || typeof msg.type !== 'string') return;
    const entry = typeof msg.id === 'number' ? pending.get(msg.id) : undefined;
    if (REPLY_TYPES.has(msg.type)) {
      if (entry) handleReply(msg, entry);
      // Stale or unknown reply ids are ignored.
      return;
    }
    for (const handler of hostHandlers) handler(msg);
  });
}

function handleReply(msg: any, entry: Pending): void {
  if (msg.type === 'raggie-http-result') {
    pending.delete(msg.id);
    if (entry.kind === 'http') {
      if (msg.ok) entry.resolve(msg.json);
      else entry.reject(httpError(msg.status, entry.method, ''));
    } else {
      entry.reject(new Error('Got http reply for a stream request'));
    }
    return;
  }
  if (msg.type === 'raggie-stream-frame') {
    if (entry.kind !== 'stream') return;
    entry.onFrame(msg.frame);
    // The response frame (carries an id) terminates the stream, mirroring
    // the standalone behavior. A later raggie-stream-end is then ignored.
    if ((msg.frame as any)?.id !== undefined) {
      pending.delete(msg.id);
      entry.resolve();
    }
    return;
  }
  // raggie-stream-end
  pending.delete(msg.id);
  if (entry.kind === 'stream') {
    if (msg.ok) entry.resolve();
    else entry.reject(httpError(msg.status, entry.method, ''));
  } else {
    entry.reject(new Error('Got stream end for an http request'));
  }
}

async function fetchPost(body: string): Promise<any> {
  const res = await fetch('/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
  });
  const text = await res.text();
  if (!res.ok) throw httpError(res.status, methodOf(body), text);
  // Notification responses (202) carry no body; nothing to parse there.
  if (!text.trim()) return undefined;
  return JSON.parse(text);
}

async function fetchStream<T>(
  body: string,
  onFrame: (frame: T) => void,
): Promise<void> {
  const res = await fetch('/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
  });
  if (!res.ok || !res.body) throw httpError(res.status, methodOf(body), '');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let done = false;

  while (!done) {
    const { value, done: streamDone } = await reader.read();
    if (streamDone) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const data = raw
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n');
      if (!data) continue;
      let frame: T | null = null;
      try {
        frame = JSON.parse(data) as T;
      } catch {
        // Ignore malformed frames.
      }
      if (!frame) continue;
      onFrame(frame);
      // The response frame (carries an id) terminates the stream.
      if ((frame as any).id !== undefined) {
        done = true;
        break;
      }
    }
  }

  if (!done) {
    // Server closed without a response frame (e.g. connection error).
    reader.cancel().catch(() => {});
  }
}
