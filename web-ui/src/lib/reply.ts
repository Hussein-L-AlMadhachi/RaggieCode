import type { Message, Reply, ToolMessage } from './types';

/** Input keys that mark a tool call as touching a file/directory. */
const PATH_KEYS = ['file_path', 'directory_path', 'path'];

export interface ReplyContext {
  above: string;
  below: string;
}

/**
 * Compact one-line summary for a tool call (name + target path) so the reply
 * chip has a short label for tool replies.
 */
export function toolSummaryLine(m: ToolMessage): string {
  const name = m.title.split('   ')[0].trim() || m.title;
  let path = '';
  if (m.input) {
    try {
      const obj = JSON.parse(m.input);
      if (obj && typeof obj === 'object') {
        for (const key of PATH_KEYS) {
          const v = (obj as Record<string, unknown>)[key];
          if (typeof v === 'string' && v.trim()) {
            path = v.trim();
            break;
          }
        }
      }
    } catch {
      // Not JSON: fall back to the bare name.
    }
  }
  return path ? `${name} ${path}` : name;
}

/** Short human label for the composer chip. */
export function replyLabel(m: Message): string {
  switch (m.kind) {
    case 'user':
      return 'you';
    case 'agent':
      return 'agent';
    case 'tool':
      return `tool · ${toolSummaryLine(m)}`;
    default:
      return m.kind;
  }
}

/**
 * Build the context window around a native text selection from the text
 * before and after the selection within the same message/tool-call block.
 * Up to `window` lines are taken from each side.
 */
export function contextFromParts(
  beforeText: string,
  afterText: string,
  window = 3,
): ReplyContext {
  const above = beforeText.split(/\r?\n/).slice(-window).join('\n');
  const below = afterText.split(/\r?\n/).slice(0, window).join('\n');
  return { above, below };
}

/**
 * Render one reply as the quotation block the agent receives: context lines
 * above, the selected text, context lines below, then the user's opinion
 * (if any) appended after the closing tag.
 */
export function buildReplyBlock(reply: Reply): string {
  const lines: string[] = ['<QuotationReply>'];
  if (reply.contextAbove) lines.push(reply.contextAbove);
  lines.push(`<selected-by-user>${reply.quoteText}</selected-by-user>`);
  if (reply.contextBelow) lines.push(reply.contextBelow);
  lines.push('</QuotationReply>');
  const content = reply.content.trim();
  if (content) {
    lines.push('');
    lines.push(content);
  }
  return lines.join('\n');
}

/** Compose the outgoing prompt: the draft followed by each reply block. */
export function buildPrompt(draft: string, replies: Reply[]): string {
  const parts: string[] = [];
  const text = draft.trim();
  if (text) parts.push(text);
  for (const reply of replies) parts.push(buildReplyBlock(reply));
  return parts.join('\n\n');
}
