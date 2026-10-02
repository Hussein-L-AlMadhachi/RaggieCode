<script lang="ts">
  import { chatStore } from '../store.svelte';

  function pick(name: string) {
    chatStore.insertCommand(name);
  }
</script>

{#if chatStore.commandMenuOpen}
  <div
    class="menu-backdrop"
    role="presentation"
    onclick={(e) => {
      if (e.target === e.currentTarget) chatStore.commandMenuOpen = false;
    }}
  >
    <div class="menu">
      {#if chatStore.commands.length === 0}
        <div class="empty">No commands available.</div>
      {/if}
      {#each chatStore.commands as c (c.name)}
        <button class="cmd" onclick={() => pick(c.name)}>
          <span class="cmd-name">{c.name}</span>
          <span class="cmd-desc">
            {c.description}
            {#if c.kind === 'choices'}
              <span class="cmd-options">{(c.choices ?? []).join(' / ')}</span>
            {/if}
          </span>
        </button>
      {/each}
    </div>
  </div>
{/if}

<style>
  .menu-backdrop {
    position: absolute;
    inset: 0;
    z-index: 5;
  }

  .menu {
    position: absolute;
    bottom: 44px;
    left: var(--sp-5);
    right: var(--sp-5);
    max-height: 260px;
    overflow-y: auto;
    background: var(--bg);
    border: var(--border-w) solid var(--border);
  }

  .empty {
    padding: var(--sp-6);
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--fg-subtle);
  }

  .cmd {
    display: flex;
    align-items: baseline;
    gap: var(--sp-5);
    width: 100%;
    padding: var(--sp-3) var(--sp-5);
    text-align: left;
    background: none;
    border: none;
    border-bottom: var(--border-w) solid var(--border-soft);
  }

  .cmd:hover {
    background: var(--bg-hover);
  }

  .cmd-name {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    font-weight: 500;
    color: var(--fg);
    flex-shrink: 0;
    min-width: 90px;
  }

  .cmd-desc {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    line-height: var(--lh-tight);
    color: var(--fg-muted);
    text-wrap: pretty;
    flex: 1;
  }

  .cmd-desc :global(.cmd-options) {
    display: block;
    color: var(--fg-subtle);
    font-size: var(--fs-2xs);
  }
</style>
