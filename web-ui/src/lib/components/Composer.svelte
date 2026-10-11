<script lang="ts">
  import { chatStore } from '../store.svelte';

  let textarea = $state<HTMLTextAreaElement>();

  // Focus the composer whenever a command is inserted from the menu
  // (composerFocus is bumped by insertCommand).
  $effect(() => {
    chatStore.composerFocus;
    textarea?.focus();
  });
</script>

{#if chatStore.replies.length > 0}
  <div class="reply-markers">
    {#each chatStore.replies as reply (reply.id)}
      <span class="reply-marker">
        <button
          class="marker-label"
          title="Edit reply"
          onclick={() => chatStore.openReplyModal(reply.id)}
        >
          {reply.label}
        </button>
        <button
          class="marker-remove"
          title="Remove reply"
          aria-label="Remove reply"
          onclick={() => chatStore.removeReply(reply.id)}
        >×</button>
      </span>
    {/each}
  </div>
{/if}

<textarea
  bind:this={textarea}
  value={chatStore.draft}
  oninput={(e) => {
    chatStore.clearCommandHint();
    chatStore.draft = e.currentTarget.value;
  }}
  onkeydown={(e) => {
    // Ctrl/Cmd+Enter submits; plain Enter inserts a newline so prompts can
    // contain code without accidentally sending.
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.shiftKey) {
      e.preventDefault();
      chatStore.send();
    }
  }}
  placeholder="Message the agent… (ctrl+enter to send)"
  spellcheck="false"
  dir="auto"
></textarea>

<style>
  .reply-markers {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2);
    padding: var(--sp-3) var(--sp-1);
  }

  .reply-marker {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    border: var(--border-w) dashed var(--border);
    background: var(--bg-code);
    padding: var(--sp-1) var(--sp-2);
    font-family: var(--mono);
    font-size: var(--fs-xs);
    max-width: 100%;
  }

  .marker-label {
    background: none;
    border: none;
    padding: 0;
    color: var(--fg);
    cursor: pointer;
    max-width: 240px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .marker-label:hover {
    color: var(--fg-muted);
  }

  .marker-remove {
    background: none;
    border: none;
    padding: 0 var(--sp-1);
    color: var(--fg-muted);
    cursor: pointer;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: 1;
  }

  .marker-remove:hover {
    color: var(--danger-fg);
  }

  textarea {
    display: block;
    width: 100%;
    height: 112px;
    border: var(--border-w) solid var(--border);
    padding: var(--sp-6) var(--sp-6);
    font-size: var(--fs-md);
    line-height: var(--lh-base);
    resize: none;
    outline: none;
    background: var(--bg);
  }
</style>
