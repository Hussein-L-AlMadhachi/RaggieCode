<script lang="ts">
  import { chatStore } from '../store.svelte';
</script>

{#if chatStore.todo?.tasks?.length}
  <button class="todo-bar" onclick={() => (chatStore.todoOpen = true)}>
    <span class="todo-label">todo</span>
    <span class="todo-prefix">next:</span>
    <span class="todo-next">{chatStore.nextTodoTask?.goal ?? 'all tasks handled'}</span>
    <span class="todo-count">
      {chatStore.todo.tasks.filter((t) => t.status === 'completed').length}/{chatStore.todo.tasks.length}
    </span>
  </button>
{/if}

<style>
  .todo-bar {
    display: flex;
    align-items: center;
    gap: var(--sp-4);
    width: calc(100% - var(--sp-10));
    margin: 0 var(--sp-5) var(--sp-2);
    padding: var(--sp-2) var(--sp-5);
    border: var(--border-w) solid var(--border-soft);
    background: var(--bg);
    text-align: left;
  }

  .todo-bar:hover {
    background: var(--bg-hover-alt);
  }

  .todo-label {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg-subtle);
    flex-shrink: 0;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding-right: var(--sp-4);
    border-right: var(--border-w) solid var(--border-soft);
  }

  .todo-prefix {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg-subtle);
    flex-shrink: 0;
  }

  .todo-next {
    flex: 1;
    min-width: 0;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: var(--lh-base);
    color: var(--fg);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .todo-count {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg-muted);
    flex-shrink: 0;
  }
</style>
