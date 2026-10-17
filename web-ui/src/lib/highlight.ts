import hljs from 'highlight.js';
import DOMPurify from 'dompurify';

/**
 * Highlight a snippet and return sanitized HTML for use with `{@html}`.
 * Falls back to escaped plaintext when the language is not registered.
 */
export function highlightCode(code: string, language = 'bash'): string {
  const value = hljs.getLanguage(language)
    ? hljs.highlight(code, { language }).value
    : hljs.highlight(code, { language: 'plaintext' }).value;
  return DOMPurify.sanitize(value);
}
