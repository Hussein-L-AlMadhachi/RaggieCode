<script lang="ts">
  import { chatStore } from '../store.svelte';

  const reply = $derived(chatStore.replies.find((r) => r.id === chatStore.replyModalId));
  let content = $state('');

  // Seed the local draft from the open reply's saved content (and whenever
  // the open reply changes).
  $effect(() => {
    content = reply?.content ?? '';
  });

  function onInput(e: Event) {
    const value = (e.currentTarget as HTMLTextAreaElement).value;
    content = value;
    if (reply) chatStore.setReplyContent(reply.id, value);
  }
</script>

{#if reply}
  <div
    class="backdrop"
    role="presentation"
    onclick={(e) => {
      if (e.target === e.currentTarget) chatStore.closeReplyModal();
    }}
    onkeydown={(e) => {
      if (e.key === 'Escape') chatStore.closeReplyModal();
    }}
  >
    <div class="modal" role="dialog" aria-modal="true" aria-label={`Reply to ${reply.label}`}>
      <div class="modal-header">
        <span class="modal-title">reply to {reply.label}</span>
        <button class="close" title="Cancel reply" onclick={() => chatStore.removeReply(reply.id)}>x</button>
      </div>
      <div class="modal-body">
        <div class="quote">
          {#if reply.contextAbove}<div class="quote-context">{reply.contextAbove}</div>{/if}
          <div class="quote-selected">{reply.quoteText}</div>
          {#if reply.contextBelow}<div class="quote-context">{reply.contextBelow}</div>{/if}
        </div>
        <label class="field-label" for="reply-input">your reply</label>
        <textarea
          id="reply-input"
          class="reply-input"
          value={content}
          oninput={onInput}
          placeholder="Add your reply / opinion (optional)"
          spellcheck="false"
        ></textarea>
        <div class="actions">
          <button class="btn solid" onclick={() => chatStore.closeReplyModal()}>done</button>
        </div>
      </div>
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.35);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10;
  }

  .modal {
    display: flex;
    flex-direction: column;
    width: var(--modal-md);
    max-width: 90vw;
    max-height: 85vh;
    background: var(--bg);
    border: var(--border-w) solid var(--border);
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--sp-5) var(--sp-6);
    border-bottom: var(--border-w) solid var(--border);
  }

  .modal-title {
    font-size: var(--fs-xl);
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .close {
    width: var(--checkbox);
    height: var(--checkbox);
    border: var(--border-w) solid var(--border);
    background: var(--bg);
    font-size: var(--fs-sm);
    line-height: 1;
    padding: 0;
    font-family: var(--mono);
  }

  .close:hover {
    background: var(--bg-hover-alt);
  }

  .modal-body {
    padding: var(--sp-6);
    display: flex;
    flex-direction: column;
    gap: var(--sp-4);
    overflow-y: auto;
  }

  .quote {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    border: var(--border-w) solid var(--border-soft);
    background: var(--bg-code);
    padding: var(--sp-4);
    font-family: var(--mono);
    font-size: var(--fs-xs);
    line-height: var(--lh-tight);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 240px;
    overflow-y: auto;
  }

  .quote-context {
    color: var(--fg-subtle);
  }

  .quote-selected {
    color: var(--fg);
    border-left: 3px solid var(--warn-fg);
    padding-left: var(--sp-4);
  }

  .field-label {
    font-family: var(--mono);
    font-size: var(--fs-2xs);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--fg-subtle);
  }

  .reply-input {
    width: 100%;
    min-height: 120px;
    border: var(--border-w) solid var(--border);
    padding: var(--sp-4) var(--sp-5);
    font-size: var(--fs-md);
    line-height: var(--lh-base);
    resize: vertical;
    outline: none;
    background: var(--bg);
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--sp-3);
  }

  .btn {
    height: var(--control-sm);
    padding: 0 var(--sp-4);
    font-size: var(--fs-md);
    border: var(--border-w) solid var(--border);
    cursor: pointer;
  }

  .btn.solid {
    background: var(--primary-bg);
    color: var(--primary-fg);
    border-color: var(--primary-bg);
  }

  .btn.solid:hover {
    background: var(--primary-bg-hover);
  }
</style>
