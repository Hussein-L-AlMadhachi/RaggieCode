import { friendlyError, notify, promptSse, resumeSse, rpc } from './api';
import { toast } from './toast.svelte';
import type {
  AgentMessage,
  ChatListItem,
  CommandInfo,
  ConfigError,
  Frame,
  HealthStats,
  McpStatus,
  Message,
  MessageSearchResult,
  Pending,
  PermissionOption,
  SessionUpdate,
  SetupRole,
  SetupStatus,
  SubagentMessage,
  SubagentUpdate,
  TextBlock,
  TodoList,
  ToolChild,
  ToolStatus,
  UserMessage,
} from './types';

/** Setup actions: add/remove/update keys, edit roles (mirrors `raggie setup`). */
export async function setupAddKey(provider: string, baseUrl: string, apiKey: string) {
  return rpc('setup/add_key', { provider, baseUrl, apiKey });
}

export async function setupRemoveKey(keyId: string) {
  return rpc('setup/remove_key', { keyId });
}

export async function setupUpdateKey(keyId: string, apiKey: string) {
  return rpc('setup/update_key', { keyId, apiKey });
}

export async function setupUpdateRole(
  role: string,
  model: string,
  baseUrl: string,
  provider: string,
  contextWindow: string,
  reasoningEffort: string,
  userAgent: string,
) {
  return rpc('setup/update_role', {
    role,
    model,
    baseUrl,
    provider,
    contextWindow: contextWindow === '' ? null : contextWindow,
    reasoningEffort,
    userAgent,
  });
}

/** MCP server management: list/add/remove/test the mcp_servers.json config. */
export async function mcpList(): Promise<McpStatus> {
  return rpc('mcp/list');
}

export async function mcpAdd(payload: {
  name: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  trust: boolean;
}) {
  return rpc('mcp/add', payload);
}

export async function mcpRemove(name: string) {
  return rpc('mcp/remove', { name });
}

export async function mcpTest(name: string) {
  return rpc('mcp/test', { name });
}

let nextMsgId = 1;

const HISTORY_PAGE = 30;

export function msgId(): string {
  return `m${++nextMsgId}`;
}

export function textFromContent(
  content: TextBlock | TextBlock[] | null | undefined,
): string {
  if (!content) return '';
  // The ACP schema sends a single content block for message chunks, but
  // tolerate arrays too (defensive; some ACP payloads use lists).
  const blocks = Array.isArray(content) ? content : [content];
  return blocks
    .filter((b) => b && b.type === 'text' && b.text)
    .map((b) => b.text)
    .join('');
}

/** Short relative timestamp like "now", "5m", "2h", "Mon", "Sep 14". */
export function relativeTime(iso: string): string {
  const t = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T'));
  if (Number.isNaN(t.getTime())) return '';
  const diff = Date.now() - t.getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return 'now';
  if (min < 60) return `${min}m`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) {
    return t.toLocaleDateString(undefined, { weekday: 'short' });
  }
  return t.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/**
 * Normalize the health-stats response so a shape change on the backend can
 * never leave the modal silently empty (e.g. legacy {stats: "text"}).
 */
export function normalizeHealth(result: any): HealthStats | null {
  if (!result || typeof result !== 'object') return null;
  return {
    healthy: !!result.healthy,
    functions: Array.isArray(result.functions) ? result.functions : [],
    objects: Array.isArray(result.objects) ? result.objects : [],
  };
}

class ChatStore {
  chats = $state<ChatListItem[]>([]);
  query = $state('');
  currentChatId = $state<string | null>(null);
  currentSessionId = $state<string | null>(null);
  messages = $state<Message[]>([]);
  busy = $state(false);
  /** True between a cancel request and the turn actually ending. */
  cancelling = $state(false);
  status = $state<string | null>(null);
  pending = $state<Pending | null>(null);
  draft = $state('');
  /** Last surfaced error. Shown to the user as a toast (no banner); kept
   *  so callers can avoid stacking duplicate error reports. */
  error = $state('');
  healthStats = $state<HealthStats | null>(null);
  healthUnread = $state(false);
  healthOpen = $state(false);
  healthExporting = $state(false);
  todo = $state<TodoList | null>(null);
  todoOpen = $state(false);
  commands = $state<CommandInfo[]>([]);
  commandMenuOpen = $state(false);
  composerFocus = $state(0);
  commandHint = $state<string | null>(null);
  pendingCommand = $state<CommandInfo | null>(null);
  historyHasMore = $state(false);
  historyCursor = $state<number | null>(null);
  loadingOlder = $state(false);
  // True while a chat is being opened (session bind + history load).
  openLoading = $state(false);
  // True while the chat list is being fetched from the backend.
  loadingChats = $state(false);
  /** FTS5 search hits over user messages (empty until a query runs). */
  messageResults = $state<MessageSearchResult[]>([]);
  /** Message id (backend row) to scroll to after render; consumed by MessageList. */
  scrollToMessageId = $state<number | null>(null);
  /** Set to ask MessageList to jump to the newest content (e.g. after
   *  approving a permission prompt or answering a question). */
  scrollToBottomPending = $state(false);
  /** True until we know the app is configured (keys + roles). */
  setupChecked = $state(false);
  setupComplete = $state(true);
  setupData = $state<SetupStatus | null>(null);
  /** Set when the user explicitly opens setup from the chat list button. */
  setupOpen = $state(false);
  /**
   * Set when the server reports a broken config file (bad roles.json, ...).
   * Any roles-consuming RPC can produce it, so it forces the setup page open
   * no matter where in the app the failure surfaced.
   */
  configError = $state<ConfigError | null>(null);
  /** Open subagent blocks (DispatchSubagent streaming), innermost last. */
  subagentStack: SubagentMessage[] = [];
  /** Interrupted work detected after opening a chat (dangling tool calls). */
  dangling = $state<{ count: number; tools: string[] } | null>(null);
  /** True after the user cancelled a turn, until they resume or send a
   * new message. Shows the resume banner even before the backend's
   * background wind-down has persisted the interrupted state. */
  interrupted = $state(false);

  get showSetup(): boolean {
    return this.setupChecked && (!this.setupComplete || this.setupOpen || !!this.configError);
  }

  /** Open the setup page from the settings icon (even if already complete). */
  openSetup() {
    this.setupOpen = true;
    // Return the status fetch so buttons can show a loading state.
    return this.loadSetupStatus();
  }

  closeSetup() {
    this.setupOpen = false;
  }

  /** Refresh the setup status (initial gate + after wizard actions). */
  /**
   * Adopt a structured config error carried by a failed RPC, forcing the
   * setup page open. Returns true when the error was a config error.
   */
  absorbConfigError(err: unknown): boolean {
    const signal = (err as { configError?: ConfigError } | null)?.configError;
    if (!signal) return false;
    this.configError = signal;
    this.setupComplete = false;
    this.setupChecked = true;
    this.setupOpen = true;
    return true;
  }

  async loadSetupStatus(force = false) {
    // When we already have a working session, do not force re-setup   unless
    // the caller needs a fresh read (e.g. after editing the active role's
    // model/effort from the chat footer).
    if (!force && this.currentSessionId) {
      this.setupChecked = true;
      this.setupComplete = true;
      return;
    }
    try {
      const result = await rpc('setup/status');
      this.setupData = result ?? null;
      this.configError = result?.configError ?? null;
      this.setupComplete = !this.configError && !!result?.setupComplete;
    } catch (err) {
      // A misconfigured roles.json is reported as a structured
      // roles_misconfigured signal   never swallow it: that would mark
      // setup as complete and lock the user out of the very page that
      // tells them what to fix.
      if (this.absorbConfigError(err)) {
        this.setupComplete = false;
        return;
      }
      // Permissive fallback: if the endpoint isn't available yet, don't
      // lock the UI out of the chat list.
      this.setupComplete = true;
    } finally {
      this.setupChecked = true;
    }
  }

  /** Update the running role's model and/or reasoning effort (persisted to
   * roles.json by the backend), then refresh setup status so the footer
   * label and effort options stay in sync. */
  async updateActiveRole(patch: { model?: string; reasoningEffort?: string }) {
    try {
      await rpc('setup/update_active_role', patch);
      toast('Updated');
      await this.loadSetupStatus(true);
    } catch (err) {
      this.failRpc(err);
    }
  }

  get mode(): 'list' | 'chat' {
    return this.currentSessionId ? 'chat' : 'list';
  }

  get title(): string {
    const chat = this.chats.find((c) => c.id === this.currentChatId);
    if (chat?.title) return chat.title;
    const firstUser = this.messages.find((m) => m.kind === 'user');
    if (firstUser) return firstUser.text.length > 40 ? firstUser.text.slice(0, 40) + '…' : firstUser.text;
    return 'New chat';
  }

  /** The role this agent instance runs as, resolved from setup/status. */
  get activeRole(): SetupRole | null {
    const name = this.setupData?.activeRole;
    if (!name) return null;
    return this.setupData?.roles?.find((r) => r.name === name) ?? null;
  }

  /** Provider-specific reasoning effort values for the active role, surfaced
   * by setup/status. Falls back to a single 'auto' option when the provider
   * is unknown or advertises no values. */
  get effortValues(): string[] {
    const provider = (this.setupData?.providers ?? []).find(
      (p) => p.name === this.activeRole?.provider,
    );
    const values = (provider?.reasoningEffortValues ?? []).filter((v) => !!v);
    return values.length > 0 ? values : ['auto'];
  }

  get canSend(): boolean {
    return !this.busy && !this.cancelling && this.pending === null && this.draft.trim().length > 0;
  }

  // -- chat management --------------------------------------------------

  async loadChats() {
    this.loadingChats = true;
    try {
      const result = await rpc('chats/list');
      this.chats = (result ?? []).map((c: any) => ({
        id: String(c.id),
        title: c.title || 'Untitled',
        updatedAt: c.updatedAt ?? '',
        preview: c.preview ?? '',
        previewRole: c.previewRole,
      }));
    } catch (err) {
      this.failRpc(err);
    } finally {
      this.loadingChats = false;
    }
  }

  filteredChats(): ChatListItem[] {
    const q = this.query.toLowerCase();
    return this.chats.filter(
      (c) => !q || (c.title + ' ' + (c.preview ?? '')).toLowerCase().includes(q),
    );
  }

  async openChat(id: string) {
    this.error = '';
    this.openLoading = true;
    try {
      const result = await rpc('chats/open', { chatId: id, cwd: '.' });
      await this.bindSession(result.sessionId, id);
    } catch (err) {
      this.failRpc(err);
    } finally {
      this.openLoading = false;
    }
  }

  /** Open a chat and deep-link to a specific message: loads older pages
   * until the message is in view, then scrolls to it once rendered. */
  async openChatToMessage(chatId: string, messageId: number) {
    await this.openChat(chatId);
    const find = (): Message | undefined =>
      this.messages.find((m) => (m as UserMessage | AgentMessage).mid === messageId);
    let target = find();
    let guard = 0;
    while (!target && this.canLoadOlder) {
      await this.loadOlder();
      target = find();
      guard += 1;
      if (guard > 200) break; // safety valve
    }
    if (target) {
      this.scrollToMessageId = messageId;
    }
  }

  async newChat() {
    this.error = '';
    this.openLoading = true;
    try {
      const result = await rpc('session/new', { cwd: '.' });
      await this.bindSession(result.sessionId, null);
    } catch (err) {
      this.failRpc(err);
    } finally {
      this.openLoading = false;
    }
  }

  /** Delete a chat by id. When it is the currently open chat, reset to
   * list mode (back() refreshes the list itself); otherwise refresh the
   * list directly. The search query is left untouched. */
  async deleteChat(id: string) {
    this.error = '';
    let deleted = false;
    try {
      await rpc('chats/delete', { chatId: id });
      deleted = true;
      toast('Chat deleted');
    } catch (err) {
      this.failRpc(err);
    } finally {
      if (deleted && id === this.currentChatId) {
        this.back();
      } else {
        await this.loadChats();
      }
    }
  }

  /** True when the error is 'unknown session'   the server process was
   * restarted and the browser still holds a stale sessionId. */
  private isStaleSession(err: unknown): boolean {
    return friendlyError(err).includes('unknown session');
  }

  /** Record an error and surface it as an error toast. */
  private fail(message: string) {
    this.error = message;
    if (message) toast(message, 'error');
  }

  /**
   * Report an RPC failure. A structured config error (broken roles.json)
   * takes over the UI and redirects to setup instead of a generic toast.
   */
  private failRpc(err: unknown) {
    if (this.absorbConfigError(err)) return;
    this.fail(friendlyError(err));
  }

  /** Re-bind to the current chat after a server restart (or start a new
   * one). Returns the fresh sessionId, or null on failure. */
  private async recoverSession(): Promise<string | null> {
    const chatId = this.currentChatId;
    try {
      if (chatId) {
        const result = await rpc('chats/open', { chatId, cwd: '.' });
        await this.bindSession(result.sessionId, chatId);
        return result.sessionId;
      }
      const result = await rpc('session/new', { cwd: '.' });
      await this.bindSession(result.sessionId, null);
      return result.sessionId;
    } catch (err) {
      if (!this.error) this.failRpc(err);
      return null;
    }
  }

  private async bindSession(sessionId: string, chatId: string | null) {
    this.currentSessionId = sessionId;
    this.currentChatId = chatId;
    this.messages = [];
    this.subagentStack = [];
    this.dangling = null;
    this.interrupted = false;
    this.draft = '';
    this.pending = null;
    this.status = null;
    this.busy = false;
    this.cancelling = false;
    this.healthStats = null;
    // don't clear query/messageResults here: the chat list relies on them
    this.scrollToMessageId = null;
    this.healthUnread = false;
    this.healthOpen = false;
    this.commandHint = null;
    this.pendingCommand = null;
    this.todo = null;
    await this.loadHistory(sessionId);
    await this.loadTodo();
    // Detect interrupted work from a previous turn so the UI can offer
    // a resume button (mirrors the terminal UI's startup behavior).
    this.checkDangling();
  }

  /** Map one backend history entry to a UI message. */
  private mapHistory(m: any): Message {
    if (m.kind === 'tool') {
      return {
        id: msgId(),
        kind: 'tool',
        toolCallId: m.toolCallId,
        title: m.title,
        status: m.status ?? 'completed',
        input: m.input,
        output: m.output,
      };
    }
    if (m.kind === 'subagent') {
      // Reconstructed subagent block from stored child-session messages:
      // same nested view as the live-streamed one, already done.
      return this.mapSubagentBlock(m);
    }
    if (m.role === 'user') {
      return { id: msgId(), kind: 'user', text: m.text, mid: m.id, handover: m.handover ?? false };
    }
    return { id: msgId(), kind: 'agent', text: m.text, mid: m.id };
  }

  /**
   * Convert one backend subagent block (possibly a nested tree) into a UI
   * SubagentMessage using an explicit stack of {raw, target} pairs   no
   * call-stack recursion. Each entry pairs a raw backend block with the UI
   * block its children are appended into; because every raw child is appended
   * to its target in raw order, sibling order is preserved across parents.
   */
  private mapSubagentBlock(raw: any): SubagentMessage {
    const makeBlock = (r: any): SubagentMessage => ({
      id: msgId(),
      kind: 'subagent',
      subagentSessionId: r.subagentSessionId ?? '',
      depth: r.depth ?? 1,
      role: r.role,
      prompt: r.prompt,
      resumed: r.resumed ?? false,
      done: r.done ?? false,
      errored: r.errored ?? false,
      text: r.text ?? '',
      children: [],
    });

    const top = makeBlock(raw);
    const stack: { raw: any; target: SubagentMessage }[] = [{ raw, target: top }];
    while (stack.length > 0) {
      const { raw: r, target } = stack.pop() as { raw: any; target: SubagentMessage };
      for (const c of r.children ?? []) {
        if (c.kind === 'subagent') {
          const block = makeBlock(c);
          target.children.push(block);
          stack.push({ raw: c, target: block });
        } else if (c.kind === 'tool') {
          target.children.push({
            id: msgId(),
            kind: 'tool' as const,
            toolCallId: c.toolCallId ?? msgId(),
            title: c.title ?? 'tool',
            status: (c.status ?? 'completed') as ToolStatus,
            input: c.input,
            output: c.output,
          });
        } else {
          target.children.push({ id: msgId(), kind: 'thought' as const, text: c.text ?? '' });
        }
      }
    }
    return top;
  }

  private async loadHistory(sessionId: string) {
    const history = await rpc('chats/history', { sessionId, limit: HISTORY_PAGE });
    const page = history?.messages ?? [];
    this.messages = page.map((m: any) => this.mapHistory(m));
    this.historyHasMore = !!history?.hasMore;
    this.historyCursor = history?.nextBefore ?? null;
  }

  /** Can the message list ask for an older page right now? */
  get canLoadOlder(): boolean {
    return this.historyHasMore && !this.loadingOlder && !this.busy && this.currentSessionId !== null;
  }

  /** Fetch the next page of older messages (prepended to the top). */
  async loadOlder(): Promise<boolean> {
    const sessionId = this.currentSessionId;
    if (!this.historyHasMore || this.loadingOlder || this.busy || !sessionId) return false;
    if (this.historyCursor === null) return false;
    this.loadingOlder = true;
    try {
      const history = await rpc('chats/history', {
        sessionId,
        beforeId: this.historyCursor,
        limit: HISTORY_PAGE,
      });
      const page = history?.messages ?? [];
      if (page.length === 0) {
        this.historyHasMore = false;
        return false;
      }
      const older = page.map((m: any) => this.mapHistory(m));
      this.messages = [...older, ...this.messages];
      this.historyHasMore = !!history?.hasMore;
      this.historyCursor = history?.nextBefore ?? null;
      return true;
    } catch (err) {
      this.failRpc(err);
      return false;
    } finally {
      this.loadingOlder = false;
    }
  }

  /** Fetch the active todo list (or clear it when none exists). */
  async loadTodo() {
    const sessionId = this.currentSessionId;
    if (!sessionId) {
      this.todo = null;
      return;
    }
    try {
      const result = await rpc('todo/active', { sessionId });
      if (result?.tasks?.length) {
        this.todo = result as TodoList;
      } else {
        this.todo = null;
      }
    } catch (err) {
      this.todo = null;
      if (this.isStaleSession(err)) {
        if (await this.recoverSession()) {
          await this.loadTodo();
          return;
        }
      }
      this.failRpc(err);
    }
  }

  /** Next task to execute: first in_progress, else first pending. */
  get nextTodoTask(): TodoList['tasks'][number] | null {
    const tasks = this.todo?.tasks ?? [];
    return tasks.find((t) => t.status === 'in_progress') ?? tasks.find((t) => t.status === 'pending') ?? null;
  }

  /** Full-text search over user messages (FTS5). */
  async searchMessages(text: string) {
    const q = text.trim();
    if (q.length < 2) {
      this.messageResults = [];
      return;
    }
    try {
      const result = await rpc('chats/search', { query: q, limit: 10 });
      this.messageResults = (result ?? []) as MessageSearchResult[];
    } catch (err) {
      this.messageResults = [];
    }
  }

  back() {
    this.currentSessionId = null;
    this.currentChatId = null;
    this.messages = [];
    this.subagentStack = [];
    this.draft = '';
    this.pending = null;
    this.status = null;
    this.busy = false;
    this.cancelling = false;
    this.interrupted = false;
    this.healthStats = null;
    this.healthUnread = false;
    this.healthOpen = false;
    this.commandHint = null;
    this.pendingCommand = null;
    this.todo = null;
    this.todoOpen = false;
    this.setupOpen = false;
    this.openLoading = false;
    this.messageResults = [];
    this.scrollToMessageId = null;
    this.historyHasMore = false;
    this.historyCursor = null;
    this.loadingOlder = false;
    // Re-entering the list: refresh titles/previews since the last turn.
    this.loadChats();
  }

  // -- prompting ----------------------------------------------------------

  async send() {
    const text = this.draft.trim();
    if (!text || !this.currentSessionId || this.busy) return;
    this.draft = '';
    this.error = '';
    this.interrupted = false;
    // Sending a new prompt supersedes any interrupted work: the resume offer
    // must disappear immediately, even though checkDangling() won't run until
    // the turn ends. If genuine leftover work remains after the turn, the
    // trailing checkDangling() re-shows the banner.
    this.dangling = null;
    this.commandHint = null;
    this.pendingCommand = null;
    await this.streamTurn(text);
  }

  private async streamTurn(text: string) {
    const sessionId = this.currentSessionId;
    if (!sessionId || this.busy) return;
    this.error = '';
    this.messages.push({ id: msgId(), kind: 'user', text });
    this.busy = true;
    await this.runTurn(
      () => promptSse(sessionId, text, (frame) => this.handleFrame(frame)),
      () => { this.draft = text; },
    );
  }

  /** Resume an interrupted turn (dangling tool calls, or a turn the user
   * cancelled). */
  async resumeWork() {
    const sessionId = this.currentSessionId;
    if (!sessionId || this.busy) return;
    this.error = '';
    this.interrupted = false;
    // Clear the dangling banner immediately: the agent is resuming now, so
    // the banner must disappear even though checkDangling() won't run until
    // the turn ends. If genuine leftover work remains after the turn, the
    // trailing checkDangling() re-shows it.
    this.dangling = null;
    this.busy = true;
    await this.runTurn(
      () => resumeSse(sessionId, (frame) => this.handleFrame(frame)),
      () => { this.dangling = null; },
    );
    // The turn may have finished the dangling work (or left more dangling
    // work behind)   refresh the resume banner either way.
    await this.checkDangling();
  }

  /** Shared turn lifecycle around a streaming rpc call. */
  private async runTurn(
    run: () => Promise<void>,
    onStaleRecover: () => void,
  ) {
    try {
      await run();
    } catch (err) {
      if (this.isStaleSession(err)) {
        if (await this.recoverSession()) {
          onStaleRecover();
          return;
        }
      }
      if (!this.error) this.failRpc(err);
    } finally {
      this.busy = false;
      this.cancelling = false;
      this.status = null;
      this.pending = null;
      this.subagentStack = [];
      this.loadChats();
      await this.loadTodo();
      // Refresh the interrupted-work banner: a cancelled or errored turn
      // may have left dangling tool calls that can be resumed right away.
      await this.checkDangling();
    }
  }

  /** Ask the backend whether the session has interrupted work (dangling
   * tool calls). Non-fatal: failure just means no resume button. */
  async checkDangling() {
    const sessionId = this.currentSessionId;
    if (!sessionId) {
      this.dangling = null;
      return;
    }
    try {
      const result = await rpc('session/dangling', { sessionId });
      this.dangling = result?.pending
        ? { count: result.count ?? 0, tools: result.tools ?? [] }
        : null;
    } catch {
      this.dangling = null;
    }
  }

  async cancel() {
    const sessionId = this.currentSessionId;
    if (this.cancelling || !sessionId) return;
    this.cancelling = true;
    // The turn was interrupted by the user: offer one-click resume right
    // away (the backend finishes persisting the interrupted state in the
    // background; resume waits for it server-side).
    this.interrupted = true;
    try {
      await notify('session/cancel', { sessionId });
      toast('Cancellation requested');
    } catch (err) {
      toast(friendlyError(err, 'Could not cancel.'), 'error');
    }
  }

  async respondPermission(outcome: 'allow' | 'allow_always' | 'reject') {
    const pending = this.pending;
    if (!pending || pending.kind !== 'perm') return;
    this.pending = null;
    this.scrollToBottomPending = true;
    try {
      await notify('session/respond_permission', { requestId: pending.requestId, outcome });
      toast(`Permission ${outcome === 'reject' ? 'denied' : 'granted'}`);
    } catch (err) {
      toast(friendlyError(err, 'Could not send the permission response.'), 'error');
    }
  }

  async respondAsk(answer: string) {
    const pending = this.pending;
    if (!pending || pending.kind !== 'ask') return;
    this.pending = null;
    this.scrollToBottomPending = true;
    try {
      await notify('session/respond_ask', { requestId: pending.requestId, answer });
      toast('Answer sent');
    } catch (err) {
      toast(friendlyError(err, 'Could not send the answer.'), 'error');
    }
  }

  // -- SSE frame handling -------------------------------------------------

  private handleFrame(frame: Frame) {
    if (frame.error !== undefined && frame.id !== undefined) {
      const data = (frame.error as any)?.data;
      const detail = typeof data === 'object' && data !== null ? data.detail : undefined;
      const message = detail
        ? `${frame.error?.message}: ${detail}`
        : (frame.error?.message ?? 'Agent error');
      this.fail(message);
      return;
    }
    if (!frame.method || !frame.params) return;

    if (frame.method === 'session/update') {
      this.handleUpdate(frame.params.update as SessionUpdate);
      // Keep the todo bar fresh while the agent works (cheap DB read).
      if (
        (frame.params.update as SessionUpdate).sessionUpdate?.startsWith('tool_call')
      ) {
        void this.loadTodo();
      }
    } else if (frame.method === 'session/status') {
      this.status = frame.params.status ?? null;
    } else if (frame.method === 'session/request_permission') {
      const options: PermissionOption[] = frame.params.options ?? [];
      this.pending = {
        kind: 'perm',
        requestId: frame.params.requestId,
        title: frame.params.toolCall?.title ?? 'Agent requests permission',
        detail: frame.params.detail ?? '',
        options,
      };
    } else if (frame.method === 'session/request_ask') {
      this.pending = {
        kind: 'ask',
        requestId: frame.params.requestId,
        question: frame.params.question ?? '',
        options: Array.isArray(frame.params.options) ? frame.params.options : undefined,
        allowMultiple: !!frame.params.allowMultiple,
      };
    } else if (frame.method === 'session/health_stats') {
      const normalized = normalizeHealth(frame.params.stats);
      if (normalized) {
        this.healthStats = normalized;
      }
      this.healthUnread = true;
    } else if (frame.method === 'session/notice') {
      const text = frame.params.text;
      if (text) {
        this.messages.push({ id: msgId(), kind: 'notice', text });
      }
    } else if (frame.method === 'session/handover') {
      const text = frame.params.text;
      if (text) {
        this.messages.push({ id: msgId(), kind: 'user', text, handover: true });
      }
    } else if (frame.method === 'session/subagent_update') {
      this.handleSubagentUpdate(frame.params as unknown as SubagentUpdate);
    }
  }

  /**
   * Live subagent activity, streamed while a DispatchSubagent tool call runs.
   * Each subagent session gets one message block; nested dispatches now appear
   * INSIDE the parent block's children, so the stack tracks the whole chain of
   * open blocks and the top of the stack is the innermost running dispatch.
   */
  private handleSubagentUpdate(u: SubagentUpdate) {
    const sid = u.subagentSessionId ?? '';
    if (!sid) return;

    if (u.phase === 'start') {
      const node: SubagentMessage = {
        id: msgId(),
        kind: 'subagent',
        subagentSessionId: sid,
        depth: u.depth ?? 1,
        role: u.role,
        prompt: u.prompt,
        resumed: u.resumed,
        done: false,
        errored: false,
        text: '',
        children: [],
      };
      const parent = this.subagentStack[this.subagentStack.length - 1];
      if (parent) {
        parent.children.push(node);
        // Store the reactive proxy (not the raw object) so later mutations render.
        this.subagentStack.push(parent.children[parent.children.length - 1] as SubagentMessage);
      } else {
        this.messages.push(node);
        // Store the reactive proxy (not the raw object) so later mutations render.
        this.subagentStack.push(this.messages[this.messages.length - 1] as SubagentMessage);
      }
      return;
    }

    // Later phases target the matching open block; dispatch is sequential, so
    // scanning the stack from the top is enough (no deep search needed).
    let node: SubagentMessage | undefined;
    for (let i = this.subagentStack.length - 1; i >= 0; i--) {
      if (this.subagentStack[i].subagentSessionId === sid) {
        node = this.subagentStack[i];
        break;
      }
    }
    if (!node) return;

    if (u.phase === 'end') {
      node.done = true;
      node.errored = !!u.errored;
      // Crash paths emit their message only in the end frame; adopt it when
      // nothing was streamed yet so the block is never left blank.
      if (!node.text && u.text) node.text = u.text;
      const idx = this.subagentStack.indexOf(node);
      if (idx >= 0) this.subagentStack.splice(idx, 1);
      return;
    }

    if (u.phase === 'chunk' || u.phase === 'error') {
      if (u.text) node.text += (node.text ? '\n\n' : '') + u.text;
      if (u.phase === 'error') node.errored = true;
      return;
    }

    if (u.phase === 'tool_call') {
      node.children.push({
        id: msgId(),
        kind: 'tool',
        toolCallId: u.toolCallId ?? msgId(),
        title: u.title ?? 'tool',
        status: 'in_progress',
        input: u.input,
      });
      return;
    }

    if (u.phase === 'tool_result') {
      const child = node.children.find(
        (c): c is ToolChild => c.kind === 'tool' && c.toolCallId === u.toolCallId,
      );
      if (child) {
        child.status = (u.status ?? 'completed') as ToolStatus;
        child.output = u.output;
      }
      return;
    }

    if (u.phase === 'thought') {
      const last = node.children[node.children.length - 1];
      if (last && last.kind === 'thought') {
        last.text = (last.text ?? '') + (u.text ?? '');
      } else {
        node.children.push({ id: msgId(), kind: 'thought', text: u.text ?? '' });
      }
    }
  }

  /** Open the health modal, always fetching fresh stats (the queries are
   * cheap indexed lookups). Any cached stats stay visible until the fresh
   * response arrives. Refused while the agent is busy: the queries read
   * the code index a running turn may be writing to. */
  async openHealth() {
    if (this.busy) return;
    this.healthOpen = true;
    this.healthUnread = false;
    await this.fetchHealth();
  }

  closeHealth() {
    this.healthOpen = false;
  }

  /** Download the full codebase health report (same content /health
   * writes to a .txt file) as a browser download. */
  async exportHealth() {
    if (this.healthExporting || !this.currentSessionId) return;
    this.healthExporting = true;
    try {
      // A stale-session failure triggers session recovery, then a fresh
      // attempt with the re-bound session id (retried via loop, not recursion).
      while (this.currentSessionId) {
        const sessionId = this.currentSessionId;
        try {
          const result = await rpc('health/report', { sessionId });
          const blob = new Blob([result?.text ?? ''], { type: 'text/plain;charset=utf-8' });
          const url = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = url;
          link.download = result?.filename ?? 'complexity_report.txt';
          document.body.appendChild(link);
          link.click();
          link.remove();
          URL.revokeObjectURL(url);
          toast('Report downloaded', 'success');
          return;
        } catch (err) {
          if (!this.isStaleSession(err) || !(await this.recoverSession())) {
            this.failRpc(err);
            return;
          }
        }
      }
    } finally {
      this.healthExporting = false;
    }
  }

  async loadCommands() {
    try {
      const result = await rpc('commands/list');
      this.commands = (result ?? []).map((c: any) => ({
        name: c.name,
        description: c.description ?? '',
        usage: c.usage ?? '',
        choices: c.choices ?? null,
        kind: c.kind ?? 'action',
      }));
    } catch (err) {
      this.failRpc(err);
    }
  }

  toggleCommandMenu() {
    this.commandMenuOpen = !this.commandMenuOpen;
  }

  /**
   * Write a command into the composer for the user to send manually.
   * - bare pick: fills "/reasoningEffort " and shows the usage example
   * - with a choice: fills "/reasoningEffort low" (from a menu option chip)
   * For choices-commands without a choice, the valid options are shown as
   * clickable chips so the user can complete the command.
   */
  insertCommand(name: string, choice?: string) {
    const command = this.commands.find((c) => c.name === name);
    this.draft = (this.draft.trim() ? this.draft.trimEnd() + ' ' : '') + name + (choice ? ` ${choice} ` : ' ');
    this.commandMenuOpen = false;
    this.composerFocus++;
    if (choice) {
      this.pendingCommand = null;
      this.commandHint = null;
    } else {
      this.pendingCommand = command?.choices?.length ? command : null;
      this.commandHint = command?.usage ?? null;
    }
  }

  /** Complete a pending choices-command with one of its options. */
  completeCommand(choice: string) {
    const pending = this.pendingCommand;
    if (!pending) return;
    this.draft = this.draft.trimEnd() + ' ' + choice + ' ';
    this.pendingCommand = null;
    this.composerFocus++;
  }

  /** Clear the command state once the user edits the text themselves. */
  clearCommandHint() {
    this.commandHint = null;
    this.pendingCommand = null;
  }

  async fetchHealth() {
    const sessionId = this.currentSessionId;
    if (!sessionId) return;
    try {
      const result = await rpc('health/stats', { sessionId });
      const normalized = normalizeHealth(result);
      if (normalized) {
        this.healthStats = normalized;
        this.healthUnread = false;
      } else {
        this.fail('Health stats payload not recognized - restart the server or rebuild the web UI.');
      }
    } catch (err) {
      if (this.isStaleSession(err)) {
        if (await this.recoverSession()) {
          await this.fetchHealth();
          return;
        }
      }
      this.failRpc(err);
    }
  }

  private handleUpdate(update: SessionUpdate) {
    const kind = update.sessionUpdate;
    if (kind === 'agent_message_chunk' || kind === 'agent_thought_chunk') {
      const target = kind === 'agent_message_chunk' ? 'agent' : 'thought';
      const text = textFromContent(update.content);
      if (!text) return;
      const last = this.messages[this.messages.length - 1];
      if (last && last.kind === target) {
        last.text += text;
      } else {
        this.messages.push({ id: msgId(), kind: target, text } as Message);
      }
    } else if (kind === 'tool_call' || kind === 'tool_call_update') {
      const toolCallId = update.toolCallId ?? '';
      if (!toolCallId) return;
      const output =
        typeof update.rawOutput === 'string' ? update.rawOutput : undefined;
      const input =
        update.rawInput !== undefined && update.rawInput !== null
          ? JSON.stringify(update.rawInput, null, 2)
          : undefined;
      const existing = this.messages.find(
        (m) => m.kind === 'tool' && m.toolCallId === toolCallId,
      );
      if (existing && existing.kind === 'tool') {
        existing.title = update.title ?? existing.title;
        existing.status = (update.status ?? existing.status) as ToolStatus;
        if (output) existing.output = output;
        if (input) existing.input = input;
      } else {
        this.messages.push({
          id: msgId(),
          kind: 'tool',
          toolCallId,
          title: update.title ?? 'tool',
          status: (update.status ?? 'in_progress') as ToolStatus,
          input,
          output,
        });
      }
    }
  }
}

export const chatStore = new ChatStore();
