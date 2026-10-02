/**
 * Pure SSE framing helpers, shared by the bridge host and unit tests.
 * Frames are separated by a blank line; only "data:" lines are delivered.
 */

export interface SseParseResult {
  frames: unknown[];
  /** Unparsed remainder (a partial frame waiting for its blank line). */
  rest: string;
}

/**
 * Split a decoded SSE text buffer into complete JSON frames.
 * Incomplete frames are returned in `rest` for the next chunk.
 * Malformed JSON and comment/keepalive-only frames are dropped.
 */
export function extractSseFrames(buffer: string): SseParseResult {
  const frames: unknown[] = [];
  let rest = buffer;

  let sep = rest.indexOf("\n\n");
  while (sep !== -1) {
    const frame = parseSseFrame(rest.slice(0, sep));
    if (frame !== undefined) {
      frames.push(frame);
    }
    rest = rest.slice(sep + 2);
    sep = rest.indexOf("\n\n");
  }

  return { frames, rest };
}

/** Parse one raw SSE frame; returns undefined when it carries no usable data. */
function parseSseFrame(raw: string): unknown | undefined {
  const data = raw
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).replace(/^ /, ""))
    .join("\n");
  if (!data) {
    return undefined;
  }
  try {
    return JSON.parse(data);
  } catch {
    return undefined;
  }
}
