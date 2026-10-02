import type { Frame } from './types';
import { begin, end } from './rpcBus.svelte';
import { transportPost, transportStream } from './bridge';

let nextId = 1;

/** Map low-level JS errors to plain, human-readable messages. */
export function friendlyError(err: unknown, fallback = 'Something went wrong.'): string {
  if (err instanceof Error) {
    err = String(err);
  }
  const raw = err ? String(err) : '';
  if (/typeerror|networkerror|failed to fetch|load failed|networkerror when attempting to fetch/i.test(raw)) {
    return 'Connection to the agent server was lost. Make sure the Raggie server is still running, then try again.';
  }
  if (/aborted/i.test(raw)) {
    return 'The request was cancelled.';
  }
  if (!raw) return fallback;
  // Drop technical prefixes but keep the useful text (e.g. "HTTP 404 for ...").
  const cleaned = raw.replace(/^(TypeError|RangeError|Error|DOMException|Exception):\s*/i, '');
  return cleaned || fallback;
}

/**
 * JSON-RPC request against the embedded ACP-over-HTTP endpoint.
 * Throws on error frames and network failures.
 */
export async function rpc(method: string, params?: unknown): Promise<any> {
  const id = nextId++;
  begin(id, method);
  try {
    const msg = await transportPost(
      JSON.stringify({ jsonrpc: '2.0', id, method, params: params ?? {} }),
    );
    if (msg.error) {
      // A structured config signal (e.g. roles_misconfigured) is preserved
      // on the thrown error so callers can redirect to setup instead of
      // showing a generic failure.
      const configError = msg.error.data?.configError;
      const detail = msg.error.data?.detail ?? msg.error.data;
      const err = new Error(
        detail ? `${msg.error.message}: ${detail}` : (msg.error.message ?? JSON.stringify(msg.error)),
      ) as Error & { configError?: unknown };
      if (configError) err.configError = configError;
      throw err;
    }
    return msg.result;
  } finally {
    end(id);
  }
}

/** JSON-RPC notification (no id, no response expected). */
export async function notify(method: string, params?: unknown): Promise<void> {
  await transportPost(
    JSON.stringify({ jsonrpc: '2.0', method, params: params ?? {} }),
  );
}

/**
 * Run an agent turn (prompt or resume) and consume its Server-Sent Events
 * stream. Calls onFrame for every notification frame and once for the final
 * JSON-RPC response. Resolves when the stream ends.
 */
async function sseTurn(
  method: string,
  params: Record<string, unknown>,
  onFrame: (frame: Frame) => void,
): Promise<void> {
  await transportStream<Frame>(
    JSON.stringify({ jsonrpc: '2.0', id: nextId++, method, params }),
    onFrame,
  );
}

export function promptSse(
  sessionId: string,
  text: string,
  onFrame: (frame: Frame) => void,
): Promise<void> {
  return sseTurn('session/prompt', {
    sessionId,
    prompt: [{ type: 'text', text }],
  }, onFrame);
}

/** Resume interrupted tool work; streams like a prompt turn. */
export function resumeSse(sessionId: string, onFrame: (frame: Frame) => void): Promise<void> {
  return sseTurn('session/resume', { sessionId }, onFrame);
}
