<script lang="ts">
  import { tick } from 'svelte';
  import { chatStore } from '../store.svelte';
  import type { Message, SubagentMessage, ToolMessage } from '../types';
  import Markdown from './Markdown.svelte';
  import Loader from './Loader.svelte';

  let container: HTMLDivElement | undefined = $state();

  const messages = $derived(chatStore.messages);

  // True while the view is pinned near the bottom. New generated content keeps
  // scrolling down only while pinned; scrolling up unpins it and scrolling
  // back to the bottom re-pins it.
  let stickToBottom = $state(true);

  type ScrollContentNode = {
    text?: string;
    output?: string;
    children?: ScrollContentNode[];
  };

  // A cheap aggregate of the whole (nested) message tree. It changes whenever
  // text/tool output grows or new messages/subagent children are added, so
  // the auto-scroll effect below re-runs on nested subagent updates   not just
  // on top-level message appends.
  function scrollSignature(nodes: ScrollContentNode[]): number {
    let sig = 0;
    const stack: ScrollContentNode[] = [...nodes];
    while (stack.length > 0) {
      const node = stack.pop();
      if (!node) continue;
      sig += 1;
      if (node.text) sig += node.text.length;
      if (node.output) sig += node.output.length;
      if (node.children) stack.push(...node.children);
    }
    return sig;
  }

  $effect(() => {
    // Deeply read the message tree so this re-runs when nested subagent
    // content grows, not just on top-level message appends.
    scrollSignature(messages);
    if (stickToBottom && container) {
      container.scrollTop = container.scrollHeight;
    }
  });

  function isNearBottom(el: HTMLDivElement): boolean {
    return el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  // Jump to a specific message when opening a chat from search results.
  $effect(() => {
    const target = chatStore.scrollToMessageId;
    if (!target || !container) return;
    void (async () => {
      await tick();
      const el = container?.querySelector(`[data-mid="${CSS.escape(String(target))}"]`);
      if (el) {
        // inline: 'nearest' keeps scrollIntoView from panning every scrollable
        // ancestor (including the page) horizontally.
        el.scrollIntoView({ block: 'center', inline: 'nearest' });
      }
      chatStore.scrollToMessageId = null;
    })();
  });

  // After approving a permission prompt or answering a question, the panel
  // collapses back to the composer; jump to the newest content and re-enable
  // auto-scroll so the resumed turn keeps following along.
  $effect(() => {
    if (!chatStore.scrollToBottomPending) return;
    chatStore.scrollToBottomPending = false;
    stickToBottom = true;
    void tick().then(() => {
      if (container) container.scrollTop = container.scrollHeight;
    });
  });

  let fetchLock = false;

  // Tool calls whose full input is expanded (classified JSON is summarized
  // one line per field by default so big fields like WriteFile "content"
  // don't flood the view.
  let expandedInputs = $state<string[]>([]);

  function toggleToolInput(toolCallId: string) {
    if (expandedInputs.includes(toolCallId)) {
      expandedInputs = expandedInputs.filter((id: string) => id !== toolCallId);
    } else {
      expandedInputs = [...expandedInputs, toolCallId];
    }
  }

  const FIELD_PREVIEW_CHARS = 120;

  interface ToolInputRow { k: string; v: string; }

  /** One compact line per tool parameter; oversized values are cut short. */
  function toolInputRows(rawInput: string): ToolInputRow[] {
    let obj: unknown;
    try {
      obj = JSON.parse(rawInput);
    } catch {
      return [{ k: '', v: rawInput as string }];
    }
    if (!obj || typeof obj !== 'object') {
      return [{ k: '', v: String(obj) }];
    }
    return Object.entries(obj as Record<string, unknown>).map(([k, v]) => {
      let text = typeof v === 'string' ? v : JSON.stringify(v);
      if (text.includes('\n')) text = text.replace(/\r?\n/g, ' ');
      if (text.length > FIELD_PREVIEW_CHARS) {
        const rest = text.length - FIELD_PREVIEW_CHARS;
        text = text.slice(0, FIELD_PREVIEW_CHARS).trimEnd() + ` …(+${rest} chars)`;
      }
      return { k, v: text };
    });
  }

  // Input keys that mark a tool call as touching a file/directory.
  const PATH_KEYS = ['file_path', 'directory_path', 'path'];

  interface ToolSummary { name: string; path: string; }

  /**
   * Compact summary for file-operation tool calls (writes, edits, reads,
   * listings...): tool name + the path it targets. Every other tool keeps
   * the full one-line title. The details stay expandable as before.
   */
  function toolSummary(title: string, rawInput?: string): ToolSummary {
    // Backend titles look like "ToolName   key: value key: value ...";
    // the name is everything before the triple-space separator.
    const name = title.split('   ')[0].trim() || title;
    let path = '';
    if (rawInput) {
      try {
        const obj = JSON.parse(rawInput);
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
        // Not JSON: fall back to the plain name.
      }
    }
    return { name, path };
  }

  function isTool(m: Message): m is ToolMessage {
    return m.kind === 'tool';
  }

  async function onScroll() {
    const el = container;
    if (!el) return;
    // Track whether the user is near the bottom so auto-scroll pauses while
    // they read history and resumes once they return to the end.
    stickToBottom = isNearBottom(el);
    if (fetchLock) return;
    if (el.scrollTop > 40) return;
    if (!chatStore.canLoadOlder) return;

    fetchLock = true;
    const oldHeight = el.scrollHeight;
    const oldTop = el.scrollTop;
    const loaded = await chatStore.loadOlder();
    if (loaded) {
      // Wait for Svelte to render the prepended page, then anchor the view
      // on the same content the user was looking at.
      await tick();
      if (container) {
        container.scrollTop = container.scrollHeight - oldHeight + oldTop;
      }
    }
    fetchLock = false;
  }
</script>

{#if messages.length === 0}
  {#if chatStore.openLoading}
    <!-- Chat is opening (session bind + history). Centered so it's impossible to miss. -->
    <div class="empty">
      <Loader label="opening chat..." size={18} />
    </div>
  {:else}
    <div class="empty">
      <div class="empty-title">Welcome to Raggie Code</div>
      <div class="empty-desc">
        Describe a task. Raggie Code will start working on it
      </div>
    </div>
  {/if}
{:else}
  <div class="messages" bind:this={container} onscroll={onScroll}>
    {#snippet subagentBlock(block: SubagentMessage)}
      <!-- One subagent block; re-renders itself for nested dispatches so
           subagent-of-subagent runs appear as boxes inside their parent. -->
      <div class="subagent" class:done={block.done} class:errored={block.errored}>
        <div class="subagent-head">
          <span class="subagent-badge">subagent · depth {block.depth}</span>
          {#if block.resumed}<span class="subagent-flag">resumed</span>{/if}
          {#if block.role}<span class="subagent-flag">{block.role}</span>{/if}
          <span class="subagent-state" class:running={!block.done}>
            {block.done ? (block.errored ? '[x] failed' : '[ok] done') : '[..] working'}
          </span>
        </div>
        {#if block.prompt}
          <pre class="subagent-prompt">{block.prompt}</pre>
        {/if}
        {#each block.children as c (c.id)}
          {#if c.kind === 'subagent'}
            {@render subagentBlock(c)}
          {:else if c.kind === 'tool'}
            <!-- Closed by default: the summary row (status + title) stays
                 visible; click to inspect input/output. -->
            {@const ts = toolSummary(c.title, c.input)}
            <details class="tool" class:failed={c.status === 'failed'}>
              <summary>
                <span class="tool-status">
                  {c.status === 'completed' ? '[ok]' : c.status === 'failed' ? '[x]' : '[..]'}
                </span>
                <span class="tool-title">{ts.name}</span>
                {#if ts.path}<span class="tool-path">{ts.path}</span>{/if}
              </summary>
              {#if c.input}
                <div class="io-label">input</div>
                <div class="tool-input tool-input-rows">
                  {#each toolInputRows(c.input) as row (row.k)}
                    <div class="io-row">{#if row.k}<span class="io-key">{row.k}:</span> {/if}{row.v}</div>
                  {/each}
                </div>
              {/if}
              {#if c.output}
                <div class="io-label">output</div>
                <pre class="tool-output">{c.output}</pre>
              {/if}
            </details>
          {:else}
            <div class="subagent-thought">{c.text}</div>
          {/if}
        {/each}
        {#if block.text}
          <div class="doc-view subagent-doc"><Markdown text={block.text} /></div>
        {/if}
      </div>
    {/snippet}
    {#if chatStore.historyHasMore}
      <div class="older">
        {#if chatStore.loadingOlder}
          <Loader label="loading older messages" size={12} />
        {:else}
          <button class="older-btn" onclick={onScroll}>load older messages</button>
        {/if}
      </div>
    {/if}
    {#each messages as m (m.id)}
      {#if m.kind === 'user'}
        {#if m.handover}
          <span
            class="handover-label handover-tip-host"
            data-tip="model context window was filling up so a handover was initiated"
          >agent task handover initiated</span>
          <div class="doc-view" data-mid={m.mid}><Markdown text={m.text} /></div>
        {:else}
          <pre class="user" data-mid={m.mid} dir="auto">{m.text}</pre>
        {/if}
      {:else if m.kind === 'notice'}
        <div class="notice">{m.text}</div>
      {:else if m.kind === 'thought'}
        <div class="thought"><Markdown text={m.text} /></div>
      {:else if isTool(m)}
        <!-- Closed by default: only the summary row (status + title) shows;
             click a tool call when you need to investigate its details. -->
        {@const ts = toolSummary(m.title, m.input)}
        <details class="tool" class:failed={m.status === 'failed'}>
          <summary>
            <span class="tool-status">
              {m.status === 'completed' ? '[ok]' : m.status === 'failed' ? '[x]' : '[..]'}
            </span>
            <span class="tool-title">{ts.name}</span>
            {#if ts.path}<span class="tool-path">{ts.path}</span>{/if}
          </summary>
          {#if m.input}
            <div class="io-label">input</div>
            {#if expandedInputs.includes(m.toolCallId)}
              <pre class="tool-input">{m.input}</pre>
            {:else}
              <div class="tool-input tool-input-rows">
                {#each toolInputRows(m.input) as row (row.k)}
                  <div class="io-row">{#if row.k}<span class="io-key">{row.k}:</span> {/if}{row.v}</div>
                {/each}
              </div>
            {/if}
            <button
              class="io-toggle"
              onclick={() => toggleToolInput(m.toolCallId)}
            >{expandedInputs.includes(m.toolCallId) ? 'view formatted' : 'view raw'}</button>
          {/if}
          {#if m.output}
            <div class="io-label">output</div>
            <pre class="tool-output">{m.output}</pre>
          {/if}
        </details>
      {:else if m.kind === 'subagent'}
        {@render subagentBlock(m)}
      {:else}
        <div class="agent" data-mid={m.mid}><Markdown text={m.text} /></div>
      {/if}
    {/each}
    {#if chatStore.dangling || chatStore.interrupted}
      <!-- Interrupted-work banner: shows when a prior turn left dangling tool
           calls, or right after the user cancelled a turn (the backend keeps
           persisting the interrupted state in the background); clicking
           streams a resume turn (like the terminal UI does). -->
      <button class="resume" onclick={() => chatStore.resumeWork()}>
        <span class="resume-label">your agent got interrupted</span>
        <span class="resume-cta">resume work</span>
      </button>
    {/if}
  </div>
{/if}

<style>
  .empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: var(--sp-4);
    padding: 0 var(--sp-11);
  }

  .empty-title {
    font-family: var(--mono);
    font-size: var(--fs-title);
  }

  .empty-desc {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: var(--lh-base);
    color: var(--fg-muted);
  }

  .messages {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    padding: var(--sp-14) var(--sp-11) var(--sp-6);
    display: flex;
    flex-direction: column;
    gap: var(--sp-11);
  }

  .older {
    margin: -16px 0 var(--sp-3);
    text-align: center;
  }

  .older-btn {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg);
    background: none;
    border: none;
    padding: var(--sp-1) var(--sp-5);
  }

  .older-btn:hover {
    color: var(--fg-muted);
    background: var(--bg-hover);
  }

  /* Interrupted-work banner: shows when a prior turn left dangling tool
     calls; clicking streams a resume turn (like the terminal UI does). */
  .resume {
    display: flex;
    align-items: center;
    gap: var(--sp-8);
    padding: var(--sp-1) var(--sp-3);
    background: var(--bg);
    border: var(--border-w) dashed var(--warn-fg);
    color: var(--fg-muted);
    font-size: var(--fs-xs);
  }

  .resume:hover {
    background: var(--bg-hover-alt);
  }

  .resume-label {
    font-family: var(--mono);
    font-size: var(--fs-xs);
  }

  .resume-cta {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    font-weight: 700;
    color: var(--warn-fg);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    white-space: nowrap;
  }

  .handover-label {
    align-self: center;
    font-family: var(--mono);
    font-size: var(--fs-2xs);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--fg-muted);
    background: var(--bg-code);
    border: var(--border-w) solid var(--border-soft);
    border-radius: var(--radius-full);
    padding: var(--sp-1) var(--sp-5);
    margin-top: var(--sp-10);
  }

  .handover-tip-host {
    position: relative;
    cursor: help;
  }

  .handover-tip-host::after {
    content: attr(data-tip);
    position: absolute;
    top: calc(100% + var(--sp-3));
    left: 50%;
    transform: translateX(-50%);
    z-index: 5;
    font-family: var(--mono);
    font-size: var(--fs-2xs);
    line-height: var(--lh-tight);
    letter-spacing: 0;
    text-transform: none;
    color: var(--fg-muted);
    background: var(--bg-code);
    border: var(--border-w) solid var(--border-soft);
    border-radius: var(--radius-md);
    padding: var(--sp-2) var(--sp-4);
    max-width: 280px;
    text-align: center;
    white-space: normal;
    opacity: 0;
    visibility: hidden;
    transition: opacity 120ms ease;
    pointer-events: none;
  }

  .handover-tip-host:hover::after {
    width: 280px;
    opacity: 1;
    visibility: visible;
  }

  /* Agent-generated handover document: full-width markdown, mute the raw
     instruction prompt look by reusing the agent text styling. */
  .doc-view {
    align-self: stretch;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: var(--lh-base);
    color: var(--fg);
    text-wrap: pretty;
    min-width: 0;
    max-width: 100%;
    overflow-wrap: anywhere;
    word-break: break-word;
    background: var(--bg-code);
    border: var(--border-w) solid var(--border-soft);
    border-radius: var(--radius-md);
    padding: var(--sp-6) var(--sp-7);
  }

  .user {
    align-self: flex-end;
    font-family: var(--sans);
    max-width: 70%;
    background: var(--bubble-bg);
    color: var(--bubble-fg);
    font-size: var(--fs-md);
    line-height: var(--lh-base);
    padding: var(--sp-4) var(--sp-5);
    text-wrap: pretty;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .notice {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    line-height: var(--lh-base);
    color: var(--fg-muted);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
    max-width: 100%;
    background: var(--bg-code);
    border: var(--border-w) solid var(--border-soft);
    padding: var(--sp-4) var(--sp-5);
  }

  .agent {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: var(--lh-base);
    color: var(--fg);
    text-wrap: pretty;
    min-width: 0;
    max-width: 100%;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .thought {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    line-height: var(--lh-base);
    color: var(--fg-subtle);
    text-wrap: pretty;
    border-left: 5px solid var(--border-soft);
    padding-left: var(--sp-5);
    min-width: 0;
  }

  .thought :global(.md) {
    color: var(--fg-subtle);
  }

  .tool {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: var(--lh-base);
    color: var(--fg);
    border: var(--border-w) dotted var(--border);
    padding: var(--sp-4) var(--sp-5);
    background-color: var(--bg);
  }

  .tool summary {
    cursor: pointer;
    list-style: none;
    white-space: pre-wrap;
    word-break: break-all;
  }

  .tool summary::-webkit-details-marker {
    display: none;
  }

  .tool summary::before {
    content: '>';
    display: inline-block;
    font-size: var(--fs-2xs);
    font-weight: 700;
    color: var(--success-fg);
    margin-right: var(--sp-3);
    transition: transform 120ms ease;
  }

  .tool[open] summary::before {
    transform: rotate(90deg);
  }

  .tool-status {
    color: var(--success-fg);
    margin-right: var(--sp-3);
    -webkit-user-select: none;
    -moz-user-select: none;
    -ms-user-select: none;
    user-select: none;
  }

  .tool-path {
    color: var(--fg-subtle);
    margin-left: var(--sp-3);
  }

  .tool.failed .tool-title {
    color: var(--danger-fg);
  }

  .tool.failed .tool-status {
    color: var(--danger-fg);
  }

  .tool.failed summary::before {
    color: var(--danger-fg);
  }

  .io-label {
    margin: var(--sp-4) 0 var(--sp-1);
    font-family: var(--mono);
    font-size: var(--fs-2xs);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--fg-subtle);
  }

  .tool-input {
    margin: 0;
    padding: var(--sp-4);
    background: var(--bg-code);
    font-family: var(--mono);
    font-size: var(--fs-xs);
    line-height: var(--lh-tight);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 240px;
    overflow-y: auto;
  }

  .tool-input-rows {
    max-height: none;
  }

  .io-row {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    line-height: var(--lh-tight);
    color: var(--fg);
    overflow-wrap: anywhere;
    word-break: break-word;
    padding-bottom: var(--sp-3);
  }

  .io-key {
    color: var(--fg-subtle);
  }

  .io-toggle {
    margin: var(--sp-4);
    font-family: var(--mono);
    font-size: var(--fs-2xs);
    color: var(--fg);
    background: none;
    border: var(--border-w) solid var(--border-soft);
    border-radius: var(--radius-sm);
    padding: var(--sp-1) var(--sp-4);
    cursor: pointer;
  }

  .io-toggle:hover {
    color: var(--fg-muted);
    background: var(--bg-hover);
  }

  .tool-output {
    margin: var(--sp-3) 0 0;
    padding: var(--sp-4);
    background: var(--bg-code);
    font-family: var(--mono);
    font-size: var(--fs-xs);
    line-height: var(--lh-tight);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 160px;
    overflow-y: auto;
  }

  /* --- streaming subagent block -----------------------------------------
     A nested MessageList-like panel: tinted background + colored left edge
     so it reads as "inside" the parent turn; deeper dispatches indent more.
     The prompt is shown as a right-aligned box and the response renders as
     markdown inside a .doc-view panel (slightly different color). */
  .subagent {
    align-self: flex-start;
    max-width: 100%;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--sp-4);
    background: var(--bg-hover);
    border: var(--border-w) solid var(--border-soft);
    border-left: 5px solid var(--subagent-accent);
    border-radius: var(--radius-md);
    padding: var(--sp-5) var(--sp-6);
  }

  .subagent.done {
    border-left-color: var(--success-fg);
  }

  /* Nested dispatch: a subagent block inside a subagent block gets a
     slightly stronger inset so the tree reads depth-first. */
  .subagent .subagent {
    margin-top: var(--sp-3);
  }

  .subagent.errored {
    border-left-color: var(--danger-fg);
  }

  .subagent-head {
    display: flex;
    align-items: center;
    gap: var(--sp-4);
    font-family: var(--mono);
    font-size: var(--fs-2xs);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--fg-subtle);
  }

  .subagent-badge {
    color: var(--fg);
    font-weight: 700;
  }

  .subagent-state {
    color: var(--success-fg);
  }

  .subagent-state.running {
    color: var(--warn-fg);
  }

  .subagent.errored .subagent-state {
    color: var(--danger-fg);
  }

  /* The prompt handed to the subagent: right-aligned, dashed border so it
     reads as "sent to someone else" rather than a regular user message. */
  .subagent-prompt {
    align-self: flex-end;
    max-width: 80%;
    margin: 0;
    font-family: var(--sans);
    font-size: var(--fs-md);
    line-height: var(--lh-base);
    color: var(--fg-muted);
    background: var(--bg-code);
    border: var(--border-w) dashed var(--subagent-prompt-border);
    border-radius: var(--radius-md);
    padding: var(--sp-4) var(--sp-5);
    text-wrap: pretty;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .subagent-thought {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    line-height: var(--lh-tight);
    color: var(--fg-subtle);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
    border-left: 3px solid var(--border-soft);
    padding-left: var(--sp-4);
  }

  /* Same .doc-view panel, one shade off so it reads as subagent output. */
  .subagent-doc {
    background: var(--bg);
  }
</style>
