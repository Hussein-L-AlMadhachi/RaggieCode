<script lang="ts">
  import { chatStore } from '../store.svelte';
  import MessageList from './MessageList.svelte';
  import AskPanel from './AskPanel.svelte';
  import PermPanel from './PermPanel.svelte';
  import Composer from './Composer.svelte';
  import HealthModal from './HealthModal.svelte';
  import CommandMenu from './CommandMenu.svelte';
  import TodoBar from './TodoBar.svelte';
  import TodoModal from './TodoModal.svelte';
  import ConfirmModal from './ConfirmModal.svelte';
  import Loader from './Loader.svelte';
  import BusyButton from './BusyButton.svelte';
  import { theme, toggleTheme } from '../theme.svelte';

  // Which risky action is awaiting confirmation: cancelling the turn,
  // leaving the chat, or starting a new chat while the agent is still
  // receiving completions. null means no confirmation is open.
  let confirmMode: null | 'cancel' | 'back' | 'new' = $state(null);

  // Drop-up for editing the active role's model + reasoning effort.
  let infoOpen = $state(false);
  let modelDraft = $state('');

  function openInfo() {
    modelDraft = chatStore.activeRole?.model ?? '';
    infoOpen = true;
  }

  function closeInfo() {
    infoOpen = false;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') infoOpen = false;
  }

  async function applyModel() {
    const model = modelDraft.trim();
    infoOpen = false;
    if (!model || model === chatStore.activeRole?.model) return;
    await chatStore.updateActiveRole({ model });
  }

  async function applyEffort(effort: string) {
    infoOpen = false;
    if (effort === chatStore.activeRole?.reasoningEffort) return;
    await chatStore.updateActiveRole({ reasoningEffort: effort });
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="chat-header">
      <button
      class="back"
      onclick={() =>
        chatStore.busy || chatStore.cancelling
          ? (confirmMode = 'back')
          : chatStore.back()}
    >
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="square"
    >
      <polyline points="7.5,2.5 4,6 7.5,9.5" />
    </svg>
    <span>chats</span>
  </button>
  <span class="chat-title">{chatStore.title}</span>
  <BusyButton
    class="theme-toggle"
    title={theme.current === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
    onclick={() => toggleTheme()}
  >
    {theme.current === 'dark' ? 'light' : 'dark'}
  </BusyButton>
  {#if !chatStore.busy}
    <!-- Health queries read the code index, which a running turn may be
         writing to; hide the affordance while the agent works. -->
    <BusyButton
      class={'health' + (chatStore.healthUnread ? ' unread' : '')}
      title="Code health"
      onclick={() => chatStore.openHealth()}
    >
      health
    </BusyButton>
  {/if}
  <BusyButton
    class="new"
    title="New chat"
    onclick={() =>
      chatStore.busy || chatStore.cancelling
        ? (confirmMode = 'new')
        : chatStore.newChat()}
  >+</BusyButton>
</div>

<MessageList />

<div class="status-area">
  {#if chatStore.busy}
    <!-- status comes from the agent (indexing, handover, etc.); fall back
         to a generic busy label so the loader is always visible. -->
    <Loader label={chatStore.status ?? 'thinking...'} />
  {/if}
</div>

<TodoBar />

<div class="panel-area">
  {#if chatStore.pending?.kind === 'ask'}
    <AskPanel pending={chatStore.pending} />
  {:else if chatStore.pending?.kind === 'perm'}
    <PermPanel pending={chatStore.pending} />
  {:else}
    <Composer />
    {#if chatStore.pendingCommand}
      <div class="command-hint">
        <span class="hint-label">pick:</span>
        <span class="chips">
          {#each chatStore.pendingCommand.choices ?? [] as choice (choice)}
            <button
              class="chip"
              onclick={() => chatStore.completeCommand(choice)}
            >
              {choice}
            </button>
          {/each}
        </span>
      </div>
    {:else if chatStore.commandHint}
      <div class="command-hint">
        <span class="hint-label">example:</span>
        <span class="hint-usage">{chatStore.commandHint}</span>
      </div>
    {/if}
  {/if}
</div>

<div class="footer">
  <button class="slash" title="Commands" onclick={() => chatStore.toggleCommandMenu()}>/</button>
  <div class="footer-actions">
    {#if chatStore.activeRole}
      <div class="model-wrap">
        <button
          class="model-info"
          onclick={() => (infoOpen ? closeInfo() : openInfo())}
          title={`${chatStore.activeRole.model} · reasoning effort ${chatStore.activeRole.reasoningEffort}`}
        >
          <span class="model">{chatStore.activeRole.model}</span>
          <span class="effort">· {chatStore.activeRole.reasoningEffort}</span>
        </button>
        {#if infoOpen}
          <div class="pop-backdrop" role="presentation" onclick={closeInfo}></div>
          <div class="model-popover">
            <label class="pop-label" for="pop-model-input">model</label>
            <div class="pop-row">
              <input
                id="pop-model-input"
                class="pop-input"
                bind:value={modelDraft}
                onkeydown={(e) => {
                  if (e.key === 'Enter') applyModel();
                }}
              />
              <button class="pop-apply" onclick={applyModel}>apply</button>
            </div>
            <div class="pop-label">reasoning effort</div>
            <div class="pop-effort">
              {#each chatStore.effortValues as effort (effort)}
                <button
                  class="pop-effort-btn"
                  class:selected={effort === chatStore.activeRole.reasoningEffort}
                  onclick={() => applyEffort(effort)}
                >
                  {effort}
                </button>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {/if}
    {#if chatStore.busy}
      <BusyButton class="cancel" onclick={() => (confirmMode = 'cancel')}>
        {chatStore.cancelling ? 'cancelling...' : 'cancel'}
      </BusyButton>
    {:else}
      <button class="send" disabled={!chatStore.canSend} onclick={() => chatStore.send()}>
        send
      </button>
    {/if}
  </div>
</div>

<HealthModal />

<TodoModal />

<ConfirmModal
  open={confirmMode !== null}
  title={confirmMode === 'back' ? 'Leave this chat?' : confirmMode === 'new' ? 'Start a new chat?' : 'Cancel this turn?'}
  message={
    confirmMode === 'back'
      ? 'The agent is still working on this turn. Going back to the chat list will cut the connection and stop receiving its updates.'
      : confirmMode === 'new'
        ? 'The agent is still working on this turn. Starting a new chat will cut the connection and stop receiving its updates.'
        : 'The agent is still working. Cancelling will stop the current turn and its work will be interrupted.'
  }
  confirmLabel={confirmMode === 'back' ? 'leave chat' : confirmMode === 'new' ? 'new chat' : 'cancel turn'}
  cancelLabel={confirmMode === 'back' || confirmMode === 'new' ? 'stay here' : 'keep going'}
  onconfirm={() => {
    const mode = confirmMode;
    confirmMode = null;
    if (mode === 'back') {
      chatStore.back();
    } else if (mode === 'new') {
      chatStore.newChat();
    } else {
      chatStore.cancel();
    }
  }}
  oncancel={() => (confirmMode = null)}
/>

<CommandMenu />

<style>
  .chat-header {
    display: flex;
    align-items: center;
    gap: var(--sp-5);
    padding: var(--sp-6);
    border-bottom: var(--border-w) solid var(--border);
  }

  .back {
    height: var(--control-sm);
    padding: 0 var(--sp-4) 0 var(--sp-4);
    white-space: nowrap;
    border: 0;
    background: var(--bg);
    color: var(--fg);
    font-size: var(--fs-md);
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }

  .back:hover {
    background: var(--border-soft);
  }

  .chat-title {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-md);
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    padding: 0 var(--sp-8);
  }

  .chat-header :global(.theme-toggle) {
    height: var(--control-sm);
    padding: 0 var(--sp-4);
    white-space: nowrap;
    border: var(--border-w) solid var(--border);
    background: var(--bg);
    color: var(--fg-muted);
    font-size: var(--fs-sm);
    flex-shrink: 0;
  }

  .chat-header :global(.theme-toggle:hover) {
    background: var(--bg-hover-alt);
    color: var(--fg);
  }

  .chat-header :global(.health) {
    height: var(--control-sm);
    padding: 0 var(--sp-4);
    white-space: nowrap;
    border: var(--border-w) solid var(--border);
    background: var(--bg);
    color: var(--fg-muted);
    font-size: var(--fs-sm);
    flex-shrink: 0;
    position: relative;
  }

  .chat-header :global(.health:hover) {
    background: var(--bg-hover-alt);
    color: var(--fg);
  }

  .chat-header :global(.health.unread)::after {
    content: '';
    position: absolute;
    top: var(--sp-1);
    right: var(--sp-1);
    width: 5px;
    height: 5px;
    background: var(--warn-fg);
  }

  .chat-header :global(.new) {
    width: 24px;
    height: var(--control-sm);
    border: var(--border-w) solid var(--border);
    background: var(--primary-bg);
    color: var(--primary-fg);
    font-size: var(--fs-xl);
    line-height: 1;
    padding: 0;
    flex-shrink: 0;
  }

  .chat-header :global(.new:hover) {
    background: var(--primary-bg-hover);
  }

  .status-area {
    min-height: var(--sp-11);
    display: flex;
    align-items: center;
    padding: var(--sp-6) var(--sp-12);
  }

  .panel-area {
    padding: 0 var(--sp-5);
  }

  .command-hint {
    display: flex;
    align-items: baseline;
    gap: var(--sp-4);
    padding: var(--sp-4) var(--sp-1) var(--sp-1);
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }

  .chip {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    padding: var(--sp-1) var(--sp-4);
    background: var(--bg);
    color: var(--fg);
    border: var(--border-w) solid var(--border);
  }

  .chip:hover {
    background: var(--bg-hover-alt);
  }

  .hint-label {
    font-family: var(--mono);
    font-size: var(--fs-2xs);
    color: var(--fg-subtle);
    flex-shrink: 0;
  }

  .hint-usage {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    line-height: var(--lh-tight);
    color: var(--fg-muted);
    word-break: break-all;
  }

  .footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--sp-4) var(--sp-5) var(--sp-5);
  }

  .footer-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-5);
    min-width: 0;
  }

  .model-wrap {
    position: relative;
  }

  .model-info {
    display: flex;
    align-items: baseline;
    gap: var(--sp-2);
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg-muted);
    white-space: nowrap;
    overflow: hidden;
    min-width: 0;
    background: none;
    border: 0;
    padding: 0;
    cursor: pointer;
    text-align: inherit;
  }

  .model-info:hover,
  .model-info:hover .effort {
    color: var(--fg);
  }

  .model-info .model {
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 220px;
  }

  .model-info .effort {
    flex-shrink: 0;
    color: var(--fg-subtle);
  }

  .pop-backdrop {
    position: fixed;
    inset: 0;
    z-index: 50;
    background: transparent;
  }

  .model-popover {
    position: absolute;
    bottom: calc(100% + var(--sp-3));
    right: 0;
    z-index: 60;
    min-width: 220px;
    max-width: 320px;
    padding: var(--sp-4);
    background: var(--bg);
    border: var(--border-w) solid var(--border);
    box-shadow: 2px 2px 0 var(--border-soft);
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }

  .pop-label {
    font-family: var(--mono);
    font-size: var(--fs-2xs);
    color: var(--fg-subtle);
  }

  .pop-row {
    display: flex;
    gap: var(--sp-2);
  }

  .pop-input {
    flex: 1;
    min-width: 0;
    font-family: var(--mono);
    font-size: var(--fs-xs);
    padding: var(--sp-2) var(--sp-3);
    background: var(--bg);
    color: var(--fg);
    border: var(--border-w) solid var(--border);
  }

  .pop-apply {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    padding: 0 var(--sp-4);
    border: var(--border-w) solid var(--border);
    background: var(--primary-bg);
    color: var(--primary-fg);
    cursor: pointer;
  }

  .pop-apply:hover {
    background: var(--primary-bg-hover);
  }

  .pop-effort {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }

  .pop-effort-btn {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    padding: var(--sp-1) var(--sp-3);
    background: var(--bg);
    color: var(--fg-muted);
    border: var(--border-w) solid var(--border);
    cursor: pointer;
  }

  .pop-effort-btn:hover {
    background: var(--bg-hover);
    color: var(--fg);
  }

  .pop-effort-btn.selected {
    background: var(--primary-bg);
    color: var(--primary-fg);
    border-color: var(--primary-bg);
  }

  .slash {
    width: 24px;
    height: var(--control-sm);
    border: var(--border-w) solid var(--border);
    background: var(--bg);
    font-family: var(--mono);
    font-size: var(--fs-md);
    padding: 0;
  }

  .slash:hover {
    background: var(--bg-hover-alt);
  }

  .send,
  .footer :global(.cancel) {
    width: 68px;
    height: var(--control-sm);
    font-size: var(--fs-md);
    border: var(--border-w) solid var(--border);
  }

  .send {
    background: var(--primary-bg);
    color: var(--primary-fg);
  }

  .send:hover:enabled {
    background: var(--primary-bg-hover);
  }

  .send:disabled {
    background: var(--bg-active);
    color: var(--fg-disabled);
    border-color: var(--border-disabled);
  }

  .footer :global(.cancel) {
    background: var(--bg);
    color: var(--fg);
    border-color: var(--fg);
  }

  .footer :global(.cancel:hover) {
    background: var(--bg);
  }
</style>
