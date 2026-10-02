<script lang="ts">
  import { chatStore } from '../store.svelte';
  import BusyButton from './BusyButton.svelte';
  import type { Pending } from '../types';

  interface Props {
    pending: Pending & { kind: 'perm' };
  }

  let { pending }: Props = $props();

  const options = $derived(pending.options);
  const detail = $derived(pending.detail ?? '');
</script>

    <div class="perm-panel">
      <div class="perm-title">{pending.title || 'Agent wants to:'}</div>
      {#if detail}
        <div class="perm-command">{detail}</div>
      {/if}
  <div class="perm-actions">
    {#each options as option (option.optionId)}
      <BusyButton
        class={option.optionId === 'reject' ? 'no' : option.optionId === 'allow_always' || option.optionId === 'always' ? 'always' : 'yes'}
        onclick={() => chatStore.respondPermission(option.optionId as 'allow' | 'allow_always' | 'reject')}
      >
        {option.name.toLowerCase()}
      </BusyButton>
    {/each}
  </div>
</div>

<style>
  .perm-panel {
    border: var(--border-w) solid var(--border);
    padding: var(--sp-8) var(--sp-10) var(--sp-11);
    display: flex;
    flex-direction: column;
    gap: var(--sp-8);
  }

  .perm-title {
    font-size: var(--fs-title);
  }

  .perm-command {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: var(--lh-base);
    background: var(--bg-code);
    padding: var(--sp-4);
    word-break: break-all;
  }

  .perm-actions {
    display: flex;
    gap: var(--sp-8);
    margin-top: var(--sp-5);
  }

  .perm-actions :global(button) {
    min-width: 70px;
    height: var(--control-sm);
    font-size: var(--fs-md);
    border: var(--border-w) solid var(--border);
  }

  .perm-actions :global(.yes) {
    background: var(--primary-bg);
    color: var(--primary-fg);
  }

  .perm-actions :global(.yes:hover) {
    background: var(--primary-bg-hover);
  }

  .perm-actions :global(.always) {
    background: var(--bg);
    color: var(--fg);
    border-color: var(--fg);
  }

  .perm-actions :global(.always:hover) {
    background: var(--fg);
    color: var(--primary-bg-hover);
  }

  .perm-actions :global(.no) {
    background: var(--border-soft);
    color: var(--fg);
  }

  .perm-actions :global(.no:hover) {
    background: var(--bg-hover-alt);
  }
</style>
