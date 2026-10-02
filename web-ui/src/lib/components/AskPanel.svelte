<script lang="ts">
  import { chatStore } from '../store.svelte';
  import BusyButton from './BusyButton.svelte';
  import type { Pending } from '../types';

  interface Props {
    pending: Pending & { kind: 'ask' };
  }

  let { pending }: Props = $props();

  let answer = $state('');
  // Indices of options picked so far (multi-select accumulates in the field).
  let picked = $state<string[]>([]);

  const options = $derived(pending.options ?? []);
  const allowMultiple = $derived(!!pending.allowMultiple);

  function submit() {
    const text = answer.trim();
    if (!text) return;
    answer = '';
    picked = [];
    // Return the notify() promise so the answer button shows a loader.
    return chatStore.respondAsk(text);
  }

  function onkey(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      submit();
    }
  }

  /**
   * Clicking an option answers it. Single-select asks (e.g. /thinkingMode)
   * submit immediately with the option's label; multi-select keeps
   * accumulating numbers into the answer field for one combined submit.
   */
  function pickOption(i: number) {
    const opt = options[i];
    if (!opt) return;
    if (!allowMultiple) {
      answer = '';
      picked = [];
      void chatStore.respondAsk(opt.label);
      return;
    }
    const n = String(i + 1);
    if (picked.includes(n)) return;
    picked = [...picked, n];
    answer = answer.trim()
      ? (allowMultiple ? `${answer.trim()}, ` : '') + answer.trim() && `${answer.trim()}, ${n}`
      : n;
  }
</script>

<div class="ask-panel">
  <div class="ask-label">Agent has a question:</div>
  <div class="ask-question">{pending.question}</div>
  {#if options.length > 0}
    <div class="ask-options">
      {#each options as opt, i}
        <button
          class="ask-option"
          class:picked={picked.includes(String(i + 1))}
          title={opt.description || opt.label}
          onclick={() => pickOption(i)}
        >
          <span class="ask-option-n">{i + 1}.</span> {opt.label}
          {#if opt.description}
            <span class="ask-opt-desc">{opt.description}</span>
          {/if}
        </button>
      {/each}
    </div>
  {/if}
  <input
    value={answer}
    oninput={(e) => (answer = e.currentTarget.value)}
    onkeydown={onkey}
    placeholder="Your answer"
    spellcheck="false"
  />
  <BusyButton class="ask-send" disabled={!answer.trim()} onclick={submit}>answer</BusyButton>
</div>

<style>
  .ask-panel {
    border: var(--border-w) solid var(--border);
    display: flex;
    flex-direction: column;
    gap: var(--sp-4);
    padding: var(--sp-7) var(--sp-6) var(--sp-6);
  }

  .ask-label {
    font-size: var(--fs-xl);
    font-weight: 500;
  }

  .ask-question {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: var(--lh-base);
    color: var(--fg-muted);
    white-space: pre-wrap;
    text-wrap: pretty;
  }

  .ask-options {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }

  .ask-option {
    text-align: left;
    font-size: var(--fs-md);
    font-family: var(--mono);
    border: var(--border-w) solid var(--border-soft);
    padding: var(--sp-3) var(--sp-4);
    background: var(--bg);
    cursor: pointer;
  }

  .ask-option:hover {
    background: var(--bg-hover);
    border-color: var(--fg-subtle);
  }

  .ask-option.picked {
    border-color: var(--fg-subtle);
    background: var(--bg-hover);
  }

  .ask-option-n {
    color: var(--success-fg);
  }

  .ask-opt-desc {
    color: var(--fg-subtle);
  }

  input {
    border: var(--border-w) solid var(--border-soft);
    padding: var(--sp-4) var(--sp-5);
    font-size: var(--fs-md);
    outline: none;
    background: var(--bg);
  }

  input:focus {
    border-color: var(--fg-subtle);
  }

  .ask-panel :global(.ask-send) {
    align-self: flex-start;
    height: var(--control-sm);
    padding: 0 var(--sp-6);
    font-size: var(--fs-md);
    border: var(--border-w) solid var(--border);
    background: var(--primary-bg);
    color: var(--primary-fg);
  }

  .ask-panel :global(.ask-send:disabled) {
    background: var(--bg-active);
    color: var(--fg-disabled);
    border-color: var(--border-disabled);
  }

  .ask-panel :global(.ask-send:hover:enabled) {
    background: var(--primary-bg-hover);
  }
</style>
