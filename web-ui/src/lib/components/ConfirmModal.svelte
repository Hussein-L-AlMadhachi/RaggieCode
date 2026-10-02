<script lang="ts">
  // Generic confirmation modal: shows a question and waits for the user to
  // confirm or dismiss. Callers pass `open`, the copy, and onconfirm/oncancel
  // callbacks. Clicking the backdrop or Escape also dismisses.
  let {
    open = false,
    title = 'Are you sure?',
    message = '',
    confirmLabel = 'confirm',
    cancelLabel = 'keep',
    onconfirm,
    oncancel,
  }: {
    open?: boolean;
    title?: string;
    message?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    onconfirm?: () => void;
    oncancel?: () => void;
  } = $props();

  function dismiss() {
    oncancel?.();
  }

  function confirm() {
    onconfirm?.();
  }
</script>

{#if open}
  <div
    class="backdrop"
    role="presentation"
    onclick={(e) => {
      if (e.target === e.currentTarget) dismiss();
    }}
    onkeydown={(e) => {
      if (e.key === 'Escape') dismiss();
    }}
  >
    <div class="modal" role="dialog" aria-modal="true" aria-label={title}>
      <div class="modal-header">
        <span class="modal-title">{title}</span>
        <button class="close" title="Close" onclick={dismiss}>x</button>
      </div>
      <div class="modal-body">
        <p class="message">{message}</p>
        <div class="actions">
          <button class="btn ghost" onclick={dismiss}>{cancelLabel}</button>
          <button class="btn solid" onclick={confirm}>{confirmLabel}</button>
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
    width: var(--modal-sm);
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
  }

  .message {
    margin: 0 0 var(--sp-5);
    font-size: var(--fs-md);
    color: var(--fg);
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

  .btn.ghost {
    background: var(--bg);
    color: var(--fg);
  }

  .btn.ghost:hover {
    background: var(--bg-hover-alt);
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
