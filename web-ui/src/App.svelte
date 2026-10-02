<script lang="ts">
  import { chatStore } from './lib/store.svelte';
  import ChatList from './lib/components/ChatList.svelte';
  import ChatView from './lib/components/ChatView.svelte';
  import SetupPage from './lib/components/SetupPage.svelte';
  import ToastHost from './lib/components/ToastHost.svelte';

  // Check whether the agent is configured (API keys + roles). If not,
  // the setup wizard replaces the chat list until it completes.
  chatStore.loadSetupStatus();
  chatStore.loadChats();
  chatStore.loadCommands();
</script>

<div class="window">
  {#if chatStore.showSetup}
    <SetupPage />
  {:else if chatStore.mode === 'list'}
    <ChatList />
  {:else}
    <ChatView />
  {/if}

  <ToastHost />
</div>

<style>
  .window {
    display: flex;
    flex-direction: column;
    width: min(100vw, var(--page-max));
    height: 100vh;
    margin: auto;
    background: var(--bg);
    border: var(--border-w) solid var(--border);
    position: relative;
  }

  @media (max-width: 400px) {
    .window {
      border: none;
    }
  }

  /* Hosted in the VS Code webview: fill the iframe exactly   percentage
     sizes avoid the 100vw/100vh scrollbar drift that offsets the app, and
     the standalone "app window" card look (border, gray page backdrop)
     does not make sense inside a narrow panel. */
  :global(html.vscode-host) .window {
    width: 100%;
    height: 100%;
    margin: 0;
    border: none;
  }
</style>
