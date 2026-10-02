<script lang="ts">
  // Shared loading indicator: a visible spinner plus an optional label.
  // Used everywhere the app shows a busy state so it never goes unnoticed.
  let { label = 'loading', size = 14 }: { label?: string; size?: number } = $props();
</script>

<span class="loader" style="--loader-size:{size}px">
  <div class="spinner" style="width:{size}px;height:{size}px"></div>
  {#if label}
    <span class="label">{label}</span>
  {/if}
</span>

<style>
  .loader {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-4);
    min-width: 0;
  }

  .spinner {
    flex-shrink: 0;
    border: 3px solid var(--border);
    border-color: var(--primary-bg);
    display: inline-block;
    animation: loader-spin 0.7s linear infinite;
  }

  .loader span:last-child {
    font-family: var(--mono);
    font-size: var(--fs-sm);
  }

  @keyframes loader-spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
