<script lang="ts">
  import { chatStore } from '../store.svelte';
  import Loader from './Loader.svelte';
  import BusyButton from './BusyButton.svelte';

  function severityClass(severity: string): string {
    const s = severity.toUpperCase();
    if (s === 'BLOATED' || s === 'LARGE') return 'sev-mild';
    if (s === 'HIGH') return 'sev-high';
    return 'sev-critical'; // VERY HIGH / VERY BLOATED
  }

  function sevShort(severity: string): string {
    return severity.replace('_', ' ');
  }
</script>

{#if chatStore.healthOpen}
  <div
    class="backdrop"
    role="presentation"
    onclick={(e) => {
      if (e.target === e.currentTarget) chatStore.closeHealth();
    }}
  >
    <div class="modal">
      <div class="modal-header">
        <span class="modal-title">Code health <span class="beta">(beta)</span></span>
        <button class="close" title="Close" onclick={() => chatStore.closeHealth()}>x</button>
      </div>
      <div class="modal-body">
        {#if chatStore.healthStats === null}
          <Loader label="loading health stats" />
        {:else if chatStore.healthStats.healthy}
          <div class="healthy">the codebase is healthy</div>
        {:else}
          {#if (chatStore.healthStats.functions ?? []).length > 0}
            <div class="section-title">top bloated functions</div>
            {#each chatStore.healthStats.functions as f, i (f.name + f.file)}
              <div class="row">
                <span class="index">{i + 1}.</span>
                <div class="main">
                  <div class="line-1">
                    <span class="name">{f.name}()</span>
                    <span class="sev {severityClass(f.severity)}">{sevShort(f.severity)}</span>
                  </div>
                  <div class="meta">{f.file}:{f.line}</div>
                </div>
              </div>
            {/each}
          {/if}

          {#if (chatStore.healthStats.objects ?? []).length > 0}
            <div class="section-title spaced">top bloated objects</div>
            {#each chatStore.healthStats.objects as o, i (o.name + o.file)}
              <div class="row">
                <span class="index">{i + 1}.</span>
                <div class="main">
                  <div class="line-1">
                    <span class="name">{o.name}</span>
                    <span class="sev {severityClass(o.severity)}">{sevShort(o.severity)}</span>
                  </div>
                  <div class="meta">{o.file}:{o.line}</div>
                  <div class="meta">
                    score {o.score.toFixed(2)} - methods {o.methods} - attributes {o.attributes}
                    - lines {o.lines}
                  </div>
                </div>
              </div>
            {/each}
          {/if}
        {/if}
      </div>
      <div class="modal-footer">
        <BusyButton
          class="export"
          onclick={() => chatStore.exportHealth()}
          disabled={chatStore.healthExporting}
        >
          {chatStore.healthExporting ? 'generating report...' : 'export codebase health report'}
        </BusyButton>
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
    max-height: 480px;
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

  .beta {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg-subtle);
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

  .healthy {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--success-fg);
  }

  .section-title {
    font-weight: 600;
    font-size: var(--fs-sm);
    color: var(--fg-muted);
    padding: var(--sp-8) auto;
  }

  .section-title.spaced {
    margin-top: var(--sp-6);
  }

  .row {
    display: flex;
    gap: var(--sp-4);
    padding: var(--sp-4) 0;
    border-bottom: var(--border-w) solid var(--border-soft);
  }

  .row:last-of-type {
    border-bottom: none;
  }

  .index {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--fg-subtle);
    flex-shrink: 0;
    padding-top: 1px;
  }

  .main {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
  }

  .line-1 {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--sp-4);
  }

  .name {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    font-weight: 500;
    color: var(--fg);
    word-break: break-all;
  }

  .meta {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    line-height: var(--lh-tight);
    color: var(--fg-subtle);
  }

  .sev {
    font-family: var(--mono);
    font-size: var(--fs-2xs);
    padding: 1px var(--sp-4);
    flex-shrink: 0;
    white-space: nowrap;
  }

  .sev-mild {
    color: var(--warn-fg);
    background: var(--warn-bg);
    border: var(--border-w) solid var(--warn-fg);
  }

  .sev-high {
    color: var(--danger-fg);
    background: var(--danger-bg);
    border: var(--border-w) solid var(--danger-fg);
  }

  .sev-critical {
    color: var(--danger-fg);
    background: var(--danger-bg);
    border: var(--border-w) solid var(--danger-fg);
  }

  .modal-footer {
    padding: var(--sp-5) var(--sp-6);
    border-top: var(--border-w) solid var(--border);
  }

  .modal-footer :global(.export) {
    font-family: var(--mono);
    width: 100%;
    height: var(--control-md);
    border: var(--border-w) solid var(--border);
    background: var(--primary-bg);
    color: var(--primary-fg);
    font-size: var(--fs-sm);
    padding: 0 var(--sp-5);
  }

  .modal-footer :global(.export:hover:enabled) {
    background: var(--primary-bg-hover);
  }

  .modal-footer :global(.export:disabled) {
    color: var(--fg-disabled);
    border-color: var(--border-disabled);
    background: var(--bg-active);
  }
</style>
