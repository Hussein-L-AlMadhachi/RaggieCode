<script lang="ts">
  // Fixed bottom-right stack of transient notifications. Pure CSS, no
  // animation library. Non-blocking: the host ignores pointer events; each
  // toast is announced via role="status" and dismissed via its close
  // button (or auto-dismiss).
  import { toasts, dismiss, type ToastKind } from '../toast.svelte';

  const kindIcon: Record<ToastKind, string> = {
    info: 'i',
    success: '✓',
    error: '!',
  };

  function close(t: { id: number }) {
    dismiss(t.id);
  }
</script>

{#if toasts.length > 0}
  <div class="host">
    {#each toasts as t (t.id)}
      <!-- role="status" is a live region, so it must stay non-interactive;
           dismissal goes through the close button. -->
      <div class="toast {t.kind}" role="status">
        <span class="icon">{kindIcon[t.kind]}</span>
        <span class="message">{t.message}</span>
        <button
          class="close"
          aria-label="Dismiss"
          onclick={() => close(t)}
        >×</button>
      </div>
    {/each}
  </div>
{/if}

<style>
  .host {
    position: absolute;
    right: var(--sp-5);
    bottom: var(--sp-8);
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
    align-items: flex-end;
    /* The stack itself is click-through; each toast opts back in. */
    pointer-events: none;
    z-index: 100;
  }

  .toast {
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: var(--sp-4);
    max-width: 340px;
    padding: var(--sp-4) var(--sp-5);
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: var(--lh-tight);
    color: var(--fg);
    background: var(--bg);
    border: var(--border-w) solid var(--border);
    border-left-width: 3px;
    border-radius: var(--radius-sm);
    box-shadow: 2px 2px 0 var(--border-soft);
    cursor: pointer;
    animation: toast-in 160ms ease-out;
  }

  .icon {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    font-size: var(--fs-2xs);
    font-family: var(--sans);
    color: var(--primary-fg);
    background: var(--primary-bg);
    border-radius: var(--radius-full);
  }

  .toast.success {
    border-left-color: var(--success-fg);
  }
  .toast.success .icon {
    background: var(--success-bg);
    color: var(--success-fg);
  }

  .toast.error {
    border-left-color: var(--danger-fg);
  }
  .toast.error .icon {
    background: var(--danger-bg);
    color: var(--danger-fg);
  }

  .message {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .close {
    flex-shrink: 0;
    padding: 0 var(--sp-2);
    border: none;
    background: none;
    color: var(--fg-muted);
    font-size: var(--fs-md);
    line-height: 1;
  }

  .close:hover {
    color: var(--fg);
  }

  @keyframes toast-in {
    from {
      opacity: 0;
      transform: translateY(6px);
    }
    to {
      transform: translateY(0);
    }
  }
</style>
