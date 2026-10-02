<script lang="ts">
  // Wrapper for buttons whose click handler talks to the agent server
  // (JSON-RPC over fetch). While the handler's promise is pending, the
  // button shows an inline spinner, is disabled and marked aria-busy.
  // Errors are NOT caught here: callers keep their own error handling.
  import type { Snippet } from 'svelte';

  interface Props {
    onclick?: (e: MouseEvent) => unknown;
    disabled?: boolean;
    class?: string;
    title?: string;
    type?: 'button' | 'submit';
    children: Snippet;
  }

  let {
    onclick,
    disabled = false,
    class: klass = '',
    title,
    type = 'button',
    children,
  }: Props = $props();

  let loading = $state(false);

  function handleClick(e: MouseEvent) {
    if (disabled || loading) {
      e.preventDefault();
      return;
    }
    const result = onclick?.(e);
    if (result && typeof (result as Promise<unknown>).then === 'function') {
      loading = true;
      void (result as Promise<unknown>).finally(() => {
        loading = false;
      });
    }
  }
</script>

<button
  {type}
  {title}
  class="busy-btn {klass}"
  disabled={disabled || loading}
  aria-busy={loading}
  onclick={handleClick}
>
  {#if loading}<span class="busy-spinner" aria-hidden="true"></span>{/if}
  {@render children()}
</button>

<style>
  /* Small enough to sit inline next to any label; currentColor keeps it
     visible on primary and plain backgrounds alike. */
  .busy-spinner {
    display: inline-block;
    width: 10px;
    height: 10px;
    margin-right: var(--sp-2);
    vertical-align: -1px;
    border: 2px solid currentColor;
    border-top-color: transparent;
    border-radius: var(--radius-full);
    animation: busy-spin 0.7s linear infinite;
  }

  .busy-btn:disabled {
    cursor: default;
  }

  @keyframes busy-spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
