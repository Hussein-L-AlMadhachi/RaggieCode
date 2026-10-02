<script lang="ts">
  import { chatStore } from '../store.svelte';
  import type { TodoTask } from '../types';

  function statusClass(status: TodoTask['status']): string {
    if (status === 'in_progress') return 'st-progress';
    if (status === 'completed') return 'st-done';
    if (status === 'failed') return 'st-failed';
    if (status === 'cancelled') return 'st-cancelled';
    return 'st-pending';
  }

  function statusLabel(status: TodoTask['status']): string {
    return status === 'in_progress' ? 'in progress' : status;
  }

  function close() {
    chatStore.todoOpen = false;
  }
</script>

{#if chatStore.todoOpen}
  <div
    class="backdrop"
    role="presentation"
    onclick={(e) => {
      if (e.target === e.currentTarget) close();
    }}
  >
    <div class="modal">
      <div class="modal-header">
        <span class="modal-title">Todo list</span>
        <button class="close" title="Close" onclick={close}>x</button>
      </div>
      <div class="modal-body">
        {#if chatStore.todo === null}
          <div class="loading">No active todo list...</div>
        {:else}
          <div class="list-state">
            {chatStore.todo.status} - {chatStore.todo.tasks.filter((t) => t.status === 'completed').length}/{chatStore.todo.tasks.length} done
          </div>
          {#each chatStore.todo.tasks as task, i (task.id)}
            <div class="task">
              <div class="line-1">
                <span class="index">{i + 1}.</span>
                <span class="goal">{task.goal}</span>
                <span class="st {statusClass(task.status)}">{statusLabel(task.status)}</span>
              </div>
              {#if task.requirements}
                <div class="detail"><span class="meta-label">req:</span>{task.requirements}</div>
              {/if}
              {#if task.notes}
                <div class="detail"><span class="meta-label">notes:</span>{task.notes}</div>
              {/if}
            </div>
          {/each}
        {/if}
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
    width: min(var(--modal-md), calc(100vw - 40px));
    max-height: 60vh;
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
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: var(--sp-6);
  }

  .loading,
  .list-state {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg-subtle);
    padding-bottom: var(--sp-4);
  }

  .task {
    padding: var(--sp-3) 0;
    border-bottom: var(--border-w) solid var(--border-soft);
  }

  .task:last-of-type {
    border-bottom: none;
  }

  .line-1 {
    display: flex;
    align-items: baseline;
    gap: var(--sp-4);
  }

  .index {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--fg-subtle);
    flex-shrink: 0;
  }

  .goal {
    flex: 1;
    min-width: 0;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: var(--lh-base);
    color: var(--fg);
    word-break: break-word;
  }

  .st {
    font-family: var(--mono);
    font-size: var(--fs-2xs);
    padding: 1px var(--sp-4);
    flex-shrink: 0;
    white-space: nowrap;
  }

  .st-pending {
    color: var(--fg-muted);
    background: var(--bg-hover-alt);
    border: var(--border-w) solid var(--border-soft);
  }

  .st-progress {
    color: var(--warn-fg);
    background: var(--warn-bg);
    border: var(--border-w) solid var(--warn-fg);
  }

  .st-done {
    color: var(--success-fg);
    background: var(--success-bg);
    border: var(--border-w) solid var(--success-fg);
  }

  .st-failed {
    color: var(--danger-fg);
    background: var(--danger-bg);
    border: var(--border-w) solid var(--danger-fg);
  }

  .st-cancelled {
    color: var(--fg-subtle);
    background: var(--bg-hover);
    border: var(--border-w) solid var(--border-soft);
    text-decoration: line-through;
  }

  .detail {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    line-height: var(--lh-tight);
    color: var(--fg-muted);
    margin: var(--sp-1) 0 0 var(--sp-10);
  }

  .meta-label {
    color: var(--fg-subtle);
    margin-right: var(--sp-2);
  }
</style>
