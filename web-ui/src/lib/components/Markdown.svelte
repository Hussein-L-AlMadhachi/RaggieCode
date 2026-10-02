<script lang="ts">
  import { marked } from 'marked';
  import hljs from 'highlight.js';
  // Token colors come from app.css (both themes); the packaged github.css
  // hardcodes light-mode colors that become invisible on dark backgrounds.
  import DOMPurify from 'dompurify';

  interface Props {
    text: string;
  }

  let { text }: Props = $props();

  // LLM output uses single newlines as line breaks far more often than
  // strict markdown allows.
  marked.use({
    breaks: true,
    gfm: true,
    // Syntax highlighting for fenced code blocks.
    renderer: {
      // marked v18 passes the token object ({ text, lang, ... }).
      code({ text, lang }: { text: string; lang?: string }) {
        const language = (lang ?? '').trim().split(/\s+/)[0];
        const highlighted =
          language && hljs.getLanguage(language)
            ? hljs.highlight(text, { language }).value
            : hljs.highlight(text, { language: 'plaintext' }).value;
        const cls = language ? `language-${language} ` : '';
        return `<pre><code class="${cls}hljs">${highlighted}</code></pre>`;
      },
    },
  });

  // Markdown originates from the LLM, so the generated HTML must be
  // sanitized before insertion (XSS surface). `class` attributes are kept
  // by default, which preserves the highlight.js token classes.
  const safe = $derived(DOMPurify.sanitize(marked.parse(text) as string));

  // Mixed-direction messages (e.g. Arabic + English) need per-element
  // direction instead of one global direction: each block gets dir="auto"
  // so it picks its direction from its own first strong character.
  // Code blocks are deliberately excluded   source code stays LTR.
  const AUTO_DIR_TAGS = new Set([
    'P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'LI',
    'UL', 'OL', 'BLOCKQUOTE', 'TD', 'TH', 'DD', 'DT', 'FIGCAPTION',
  ]);

  function withPerElementDir(html: string): string {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const stack: Element[] = Array.from(doc.body.children);
    while (stack.length > 0) {
      const el = stack.pop()!;
      if (AUTO_DIR_TAGS.has(el.tagName) && !el.hasAttribute('dir')) {
        el.setAttribute('dir', 'auto');
      }
      stack.push(...el.children);
    }
    return doc.body.innerHTML;
  }

  const html = $derived(withPerElementDir(safe));
</script>

<div class="md">{@html html}</div>

<style>
  /* The HTML is injected via {@html}, so Svelte scoped CSS can't reach it  
     all selectors below must use :global(). */
  .md :global(*) {
    margin: 0;
  }

  .md :global(p),
  .md :global(ul),
  .md :global(ol),
  .md :global(blockquote),
  .md :global(pre),
  .md :global(table),
  .md :global(h1),
  .md :global(h2),
  .md :global(h3),
  .md :global(h4),
  .md :global(h5),
  .md :global(h6) {
    margin: var(--sp-4) 0;
  }

  .md :global(p:first-child),
  .md :global(ul:first-child),
  .md :global(ol:first-child),
  .md :global(pre:first-child),
  .md :global(h1:first-child),
  .md :global(h2:first-child),
  .md :global(h3:first-child) {
    margin-top: 0;
  }

  .md :global(p:last-child),
  .md :global(ul:last-child),
  .md :global(ol:last-child),
  .md :global(pre:last-child),
  .md :global(table:last-child) {
    margin-bottom: 0;
  }

  .md :global(h1),
  .md :global(h2),
  .md :global(h3),
  .md :global(h4),
  .md :global(h5),
  .md :global(h6) {
    font-size: var(--fs-md);
    font-weight: 600;
    color: var(--fg);
  }

  .md :global(ul),
  .md :global(ol) {
    padding-inline-start: var(--sp-10);
  }

  .md :global(li) {
    margin: var(--sp-1) 0;
  }

  .md :global(code) {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    background: var(--bg-code);
    padding: var(--sp-1) var(--sp-2);
  }

  .md :global(pre) {
    background: var(--bg-code);
    border: var(--border-w) solid var(--border-soft);
    padding: var(--sp-4);
    overflow-x: auto;
  }

  .md :global(pre code) {
    background: none;
    padding: 0;
    font-size: var(--fs-xs);
    line-height: var(--lh-base);
    white-space: pre;
  }

  .md :global(blockquote) {
    border-inline-start: 2px solid var(--border-soft);
    padding-inline-start: var(--sp-5);
    color: var(--fg-muted);
  }

  .md :global(a) {
    color: var(--fg);
    text-decoration: underline;
  }

  .md :global(a:hover) {
    color: var(--fg-muted);
  }

  .md :global(table) {
    border-collapse: collapse;
    font-family: var(--mono);
    font-size: var(--fs-xs);
    display: block;
    overflow-x: auto;
    white-space: nowrap;
  }

  .md :global(th),
  .md :global(td) {
    border: var(--border-w) solid var(--border-soft);
    padding: var(--sp-2) var(--sp-4);
    text-align: start;
  }

  .md :global(th) {
    background: var(--bg-code);
    font-weight: 500;
  }

  .md :global(hr) {
    border: none;
    border-top: var(--border-w) solid var(--border-soft);
    margin: var(--sp-5) 0;
  }

  .md :global(img) {
    max-width: 100%;
  }
</style>
