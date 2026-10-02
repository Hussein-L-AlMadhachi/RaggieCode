<script lang="ts">
  import { chatStore } from '../store.svelte';
  import { theme, toggleTheme } from '../theme.svelte';
  import BusyButton from './BusyButton.svelte';
  import Loader from './Loader.svelte';
  import type { ChatListItem } from '../types';

  const PAGE_SIZE = 20;
  let visibleCount = $state(PAGE_SIZE);

  const chats = $derived(chatStore.filteredChats());
  const visible = $derived(chats.slice(0, visibleCount));
  const hasMore = $derived(visibleCount < chats.length);
  const allShown = $derived(visibleCount >= chats.length && chats.length > 0);

  function timeLabel(item: ChatListItem): string {
    return relative(item.updatedAt);
  }

  // Inline two-step delete confirm: first click arms the item ('confirm?'),
  // second click deletes; clicking elsewhere or Escape cancels.
  let confirmDeleteId = $state<string | null>(null);
  // Chat id whose open request is in flight (per-row spinner).
  let openingId = $state<string | null>(null);

  // Returns the delete promise on the confirming click so the button
  // can show a loading state; undefined when just arming the confirm.
  function deleteClick(id: string) {
    if (confirmDeleteId === id) {
      confirmDeleteId = null;
      return chatStore.deleteChat(id);
    } else {
      confirmDeleteId = id;
    }
  }

  async function rowClick(id: string) {
    confirmDeleteId = null;
    if (openingId !== null) return;
    openingId = id;
    try {
      await chatStore.openChat(id);
    } finally {
      openingId = null;
    }
  }

  function rowKey(e: KeyboardEvent, id: string) {
    if ((e.target as HTMLElement).closest('.item-delete')) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      rowClick(id);
    } else if (e.key === 'Escape') {
      confirmDeleteId = null;
    }
  }

  function relative(iso: string): string {
    const t = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T'));
    if (Number.isNaN(t.getTime())) return '';
    const diff = Date.now() - t.getTime();
    const min = Math.floor(diff / 60000);
    if (min < 1) return 'now';
    if (min < 60) return `${min}m`;
    const hours = Math.floor(min / 60);
    if (hours < 24) return `${hours}h`;
    if (hours < 24 * 7) {
      return t.toLocaleDateString(undefined, { weekday: 'short' });
    }
    return t.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
</script>

<div class="pane-header">
  <div class="pane-title">All Chats</div>
  <div class="header-actions">
    <BusyButton
      class="theme-toggle"
      title={theme.current === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
      onclick={() => toggleTheme()}
    >
      {theme.current === 'dark' ? 'light' : 'dark'}
    </BusyButton>
    <BusyButton class="settings" title="Raggie setup" onclick={() => chatStore.openSetup()}>
      setup
    </BusyButton>
    <BusyButton
      class="new-chat"
      onclick={() => {
        visibleCount = PAGE_SIZE;
        return chatStore.newChat();
      }}
    > New Chat </BusyButton>
  </div>
</div>

<input
  class="search"
  placeholder="Search chats"
  value={chatStore.query}
  oninput={(e) => {
    chatStore.query = e.currentTarget.value;
    void chatStore.searchMessages(e.currentTarget.value);
  }}
  spellcheck="false"
/>

{#if chatStore.messageResults.length > 0}
  <div class="search-results-header">matching messages</div>
  {#each chatStore.messageResults as r (r.messageId)}
    <BusyButton
      class="chat-item message-hit"
      onclick={() => chatStore.openChatToMessage(String(r.chatId), r.messageId)}
    >
      <div class="item-top">
        <span class="item-title">{r.title}</span>
        <span class="item-time">msg #{r.messageId}</span>
      </div>
      <div class="item-preview hit-snippet">
        <!-- Backend strips all other <...> sequences and only inserts
             <mark>/</mark>, so rendering this as HTML is safe. -->
        {@html r.snippet}
      </div>
    </BusyButton>
  {/each}
  <div class="results-divider"></div>
{/if}

<div class="chat-items">
  {#each visible as c (c.id)}
    <div
      class="chat-item"
      role="button"
      tabindex="0"
      onclick={() => rowClick(c.id)}
      onkeydown={(e) => rowKey(e, c.id)}
    >
      <div class="item-top">
        <span class="item-title">{c.title}</span>
        <span class="item-meta">
          {#if openingId === c.id}
            <span class="row-spinner" title="opening chat" role="img" aria-label="opening chat"></span>
          {:else}
            <span class="item-time">{timeLabel(c)}</span>
          {/if}
          <BusyButton
            class={'item-delete' + (confirmDeleteId === c.id ? ' confirm' : '')}
            title={confirmDeleteId === c.id ? 'Click again to confirm' : 'Delete chat'}
            onclick={(e) => {
              e.stopPropagation();
              return deleteClick(c.id);
            }}
          >
            {#if confirmDeleteId === c.id}
              delete?
            {:else}
              <svg
                class="trash"
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="M3 6h18" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                <path d="M10 11v6" />
                <path d="M14 11v6" />
              </svg>
            {/if}
          </BusyButton>
        </span>
      </div>
      <div class="item-preview">{c.preview}</div>
    </div>
  {/each}

  {#if chatStore.loadingChats && chats.length === 0}
    <div class="loading-chats"><Loader label="loading chats" /></div>
  {:else if chats.length === 0}
    <div class="no-results">No chats yet.</div>
  {/if}

  {#if hasMore}
    <button class="show-more" onclick={() => (visibleCount += PAGE_SIZE)}>Show more</button>
  {:else if allShown}
    <div class="all-shown">All chats shown</div>
  {/if}
</div>

<style>
  .pane-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--sp-8) var(--sp-11) var(--sp-5);
  }

  .pane-title {
    font-size: var(--fs-title);
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-4);
    flex-shrink: 0;
  }

  .header-actions :global(.theme-toggle) {
    height: var(--control-sm);
    padding: 0 var(--sp-6);
    white-space: nowrap;
    background: var(--bg);
    color: var(--fg-muted);
    border: var(--border-w) solid var(--border);
    font-size: var(--fs-md);
  }

  .header-actions :global(.theme-toggle:hover) {
    background: var(--bg-hover-alt);
    color: var(--fg);
  }

  .header-actions :global(.settings) {
    height: var(--control-sm);
    padding: 0 var(--sp-6);
    white-space: nowrap;
    background: var(--bg);
    color: var(--fg-muted);
    border: var(--border-w) solid var(--border);
    font-size: var(--fs-md);
  }

  .header-actions :global(.settings:hover) {
    background: var(--bg-hover-alt);
    color: var(--fg);
  }

  .header-actions :global(.new-chat) {
    height: var(--control-sm);
    padding: 0 var(--sp-6);
    white-space: nowrap;
    flex-shrink: 0;
    background: var(--primary-bg);
    color: var(--primary-fg);
    border: var(--border-w) solid var(--border);
    font-size: var(--fs-md);
  }

  .header-actions :global(.new-chat:hover) {
    background: var(--primary-bg-hover);
  }

  .search {
    margin: 0 var(--sp-11) var(--sp-5);
    padding: var(--sp-3) var(--sp-4);
    border: var(--border-w) solid var(--fg);
    font-size: var(--fs-md);
    outline: none;
    background: var(--bg);
  }

  .search:focus {
    border-color: var(--fg-subtle);
  }

  .search-results-header {
    padding: var(--sp-3) var(--sp-11);
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg-subtle);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .item-preview.hit-snippet :global(mark) {
    background: var(--primary-bg);
    color: var(--primary-fg);
    padding: 0 1px;
  }

  .results-divider {
    height: 1px;
    background: var(--fg-subtle);
    margin-top: var(--sp-2);
  }

  .chat-items {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    border-top: var(--border-w) solid var(--border);
  }

  .chat-item {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: var(--sp-3);
    width: 100%;
    padding: var(--sp-7) var(--sp-11);
    text-align: left;
    border: none;
    border-bottom: var(--border-w) solid var(--border-soft);
    background: none;
    cursor: pointer;
  }

  .chat-item:hover {
    background: var(--bg-hover);
  }

  /* The row is a div with role="button"; restore a visible focus ring for
     keyboard users (native buttons no longer apply). */
  .chat-item:focus-visible {
    outline: var(--border-w) solid var(--fg-subtle);
    outline-offset: -1px;
  }

  /* Message-hit rows are BusyButton roots: Svelte 5 does not apply this
     component's scoping class to child component elements, so the scoped
     .chat-item rules above cannot match them. Globalized copy (hover
     included, so hit rows keep the same row-hover feedback). */
  :global(.chat-item.message-hit) {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: var(--sp-3);
    width: 100%;
    padding: var(--sp-7) var(--sp-11);
    text-align: left;
    border: none;
    border-bottom: var(--border-w) solid var(--border-soft);
    background: none;
  }

  :global(.chat-item.message-hit:hover) {
    background: var(--bg-hover);
  }

  .item-meta {
    display: flex;
    align-items: baseline;
    gap: var(--sp-3);
    flex-shrink: 0;
  }

  .chat-items :global(.item-delete) {
    font-family: var(--mono);
    font-size: var(--fs-2xs);
    color: var(--warn-fg);
    background: none;
    border: var(--border-w) solid var(--border-soft);
    border-radius: var(--radius-sm);
    display: inline-flex;
    align-items: center;
    padding: var(--sp-1) var(--sp-3);
    cursor: pointer;
    visibility: hidden;
  }

  .chat-items :global(.item-delete svg) {
    display: block;
  }

  .chat-items :global(.item-delete:hover) {
    color: var(--danger-fg);
    background: var(--bg-hover);
  }

  /* Hover or keyboard focus reveals the delete affordance; the armed
     confirm state stays visible regardless. */
  .chat-items :global(.chat-item:hover .item-delete),
  .chat-items :global(.chat-item:focus-within .item-delete),
  .chat-items :global(.item-delete.confirm) {
    visibility: visible;
  }

  .chat-items :global(.item-delete.confirm) {
    color: var(--danger-fg);
    border-color: var(--danger-fg);
  }

  .item-top {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: var(--sp-6);
  }

  .item-title {
    font-size: var(--fs-lg);
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .item-time {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg-subtle);
    flex-shrink: 0;
  }

  /* Replaces the timestamp while that row's chat is being opened. */
  .row-spinner {
    flex-shrink: 0;
    width: 10px;
    height: 10px;
    border: 2px solid var(--border);
    border-top-color: var(--fg);
    border-radius: var(--radius-full);
    animation: row-spin 0.7s linear infinite;
  }

  @keyframes row-spin {
    to {
      transform: rotate(360deg);
    }
  }

  .item-preview {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: var(--lh-base);
    color: var(--fg-muted);
    overflow-wrap: anywhere;
    word-break: break-word;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .no-results {
    padding: var(--sp-14) var(--sp-11);
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--fg-subtle);
  }

  .loading-chats {
    display: flex;
    justify-content: center;
    padding: var(--sp-14) var(--sp-11);
    color: var(--fg-subtle);
  }

  .show-more {
    display: block;
    width: 100%;
    padding: var(--sp-6) var(--sp-11);
    background: none;
    border: none;
    border-top: var(--border-w) solid var(--border-soft);
    font-size: var(--fs-md);
    text-align: center;
  }

  .show-more:hover {
    background: var(--bg-hover);
  }

  .all-shown {
    padding: var(--sp-7) var(--sp-11);
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--fg-subtle);
    text-align: center;
    border-top: var(--border-w) solid var(--border-soft);
  }
</style>
