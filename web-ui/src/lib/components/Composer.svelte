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
