<script lang="ts">
  import { onMount } from 'svelte';
  import { friendlyError } from '../api';
import { chatStore, mcpAdd, mcpList, mcpRemove, mcpTest, setupAddKey, setupRemoveKey, setupUpdateRole, setupUpdateKey } from '../store.svelte';
  import { toast } from '../toast.svelte';
  import type { McpServer, McpTestResult } from '../types';
  import BusyButton from './BusyButton.svelte';

  let provider = $state('');
  let baseUrl = $state('');
  let apiKey = $state('');
  let actionError = $state('');
  let saving = $state(false);
  let providerSuggestions = $state<Record<string, string>>({});

  /** key id currently being edited (new secret typed into a password field). */
  let editingKeyId = $state('');
  let editKeyValue = $state('');

  // Per-role editable drafts: name -> full role settings.
  type RoleDraft = {
    model: string;
    baseUrl: string;
    provider: string;
    contextWindow: string;
    reasoningEffort: string;
    userAgent: string;
  };
  let roleDrafts = $state<Record<string, RoleDraft>>({});

  // -- MCP servers ------------------------------------------------------
  let mcpPath = $state('');
  let mcpServers = $state<McpServer[]>([]);
  let mcpName = $state('');
  let mcpKind = $state('stdio');
  let mcpUrl = $state('');
  let mcpCommand = $state('');
  let mcpArgs = $state('');
  let mcpEnv = $state('');
  let mcpTrust = $state(false);
  let mcpFormError = $state('');
  let mcpTesting = $state('');
  let mcpResults = $state<Record<string, McpTestResult>>({});

  onMount(() => {
    loadMcp();
  });

  function syncRoleDrafts() {
    const next: Record<string, RoleDraft> = {};
    for (const role of chatStore.setupData?.roles ?? []) {
      next[role.name] = {
        model: role.model,
        baseUrl: role.baseUrl,
        provider: role.provider,
        contextWindow: String(role.contextWindow ?? ''),
        reasoningEffort: role.reasoningEffort || 'auto',
        userAgent: role.userAgent ?? '',
      };
    }
    roleDrafts = next;
  }

  $effect(() => {
    // Re-sync drafts + provider suggestions whenever status reloads.
    chatStore.setupData?.roles;
    chatStore.setupData?.providers;
    syncRoleDrafts();
    syncProviderSuggestions();
  });

  async function refresh() {
    await chatStore.loadSetupStatus();
    syncProviderSuggestions();
  }

  /** provider name -> suggested base URL, for autofill on select. */
  function syncProviderSuggestions() {
    const next: Record<string, string> = {};
    for (const p of chatStore.setupData?.providers ?? []) {
      if (p.baseUrl) next[p.name] = p.baseUrl;
    }
    providerSuggestions = next;
  }

  /** Provider select change: auto-fill the base URL with the provider's
   * default (kept editable so users can point at self-hosted endpoints). */
  function providerChanged() {
    const suggested = providerSuggestions[provider];
    if (suggested) {
      baseUrl = suggested;
    }
  }

  /** Known providers for the role dropdown   only providers the user has
   * keys for (matching the CLI, which only suggests what it can actually
   * authenticate with). */
  const keyProviders = $derived.by(() => {
    const names: string[] = [];
    for (const k of chatStore.setupData?.keys ?? []) {
      if (k.provider && !names.includes(k.provider)) names.push(k.provider);
    }
    return names;
  });

  /** Available providers for a role: providers the user has keys for,
   * plus the role's current provider so it can never become unselectable. */
  function roleProviderOptions(roleName: string): string[] {
    const role = chatStore.setupData?.roles?.find((r) => r.name === roleName);
    const names = [...keyProviders];
    if (role?.provider && !names.includes(role.provider)) {
      names.unshift(role.provider);
    }
    return names;
  }

  /** Reasoning effort options for a role, based on its *currently
   * selected* provider (from the draft, not the saved role). */
  function roleEffortValues(roleName: string): string[] {
    const draft = roleDrafts[roleName];
    const provider = (chatStore.setupData?.providers ?? []).find(
      (p) => p.name === draft?.provider,
    );
    return provider?.reasoningEffortValues ?? ['auto'];
  }

  /** Base URL options for a role, mirroring the CLI chooser: URLs from
   * your stored keys for the *currently selected* provider (from the
   * draft, not the saved role), plus the provider default. */
  function roleBaseUrlOptions(roleName: string): string[] {
    const draft = roleDrafts[roleName];
    if (!draft) return [];
    const providerName = draft.provider;
    const urls: string[] = [];
    const seen = new Set<string>();
    for (const k of chatStore.setupData?.keys ?? []) {
      if (k.provider === providerName && k.baseUrl && !seen.has(k.baseUrl)) {
        seen.add(k.baseUrl);
        urls.push(k.baseUrl);
      }
    }
    const providerDefault = providerSuggestions[providerName];
    if (providerDefault && !seen.has(providerDefault)) {
      seen.add(providerDefault);
      urls.push(providerDefault);
    }
    // Keep the role's saved endpoint selectable too (even if its key was
    // removed meanwhile), so saving doesn't silently change it.
    const savedUrl = chatStore.setupData?.roles?.find((r) => r.name === roleName)?.baseUrl ?? '';
    if (savedUrl && !seen.has(savedUrl)) {
      urls.unshift(savedUrl);
    }
    return urls;
  }

  /** Correct base URL for a provider: the matching key's URL if one
   * exists, otherwise the provider default. */
  function providerBaseUrl(providerName: string): string {
    if (keyBaseUrlAvailable(providerName)) return keyBaseUrl(providerName);
    return providerSuggestions[providerName] ?? '';
  }

  function keyBaseUrl(providerName: string): string {
    return (chatStore.setupData?.keys ?? []).find(
      (k) => k.provider === providerName,
    )?.baseUrl ?? '';
  }

  function keyBaseUrlAvailable(providerName: string): boolean {
    return (chatStore.setupData?.keys ?? []).some(
      (k) => k.provider === providerName && !!k.baseUrl,
    );
  }

  async function addKey(e: SubmitEvent) {
    e.preventDefault();
    actionError = '';
    if (!provider.trim() || !baseUrl.trim() || !apiKey.trim()) {
      actionError = 'Provider, base URL and API key are all required.';
      return;
    }
    saving = true;
    try {
      await setupAddKey(provider.trim(), baseUrl.trim(), apiKey.trim());
      provider = '';
      baseUrl = '';
      apiKey = '';
      await refresh();
      toast('API key added', 'success');
    } catch (err) {
      actionError = friendlyError(err);
      toast(actionError, 'error');
    } finally {
      saving = false;
    }
  }

  async function removeKey(keyId: string) {
    actionError = '';
    try {
      await setupRemoveKey(keyId);
      await refresh();
      toast('API key removed', 'success');
    } catch (err) {
      actionError = friendlyError(err);
      toast(actionError, 'error');
    }
  }

  function startKeyEdit(keyId: string) {
    editingKeyId = keyId;
    editKeyValue = '';
  }

  function cancelKeyEdit() {
    editingKeyId = '';
    editKeyValue = '';
  }

  async function confirmKeyEdit() {
    actionError = '';
    if (!editKeyValue.trim()) {
      actionError = 'Enter a new key value first.';
      return;
    }
    saving = true;
    try {
      await setupUpdateKey(editingKeyId, editKeyValue.trim());
      cancelKeyEdit();
      await refresh();
      toast('API key updated', 'success');
    } catch (err) {
      actionError = friendlyError(err);
      toast(actionError, 'error');
    } finally {
      saving = false;
    }
  }

  async function saveRole(name: string) {
    actionError = '';
    const draft = roleDrafts[name];
    // Base URL comes from the dropdown (key URLs + provider default).
    if (!draft?.model.trim() || !draft?.baseUrl.trim()) {
      actionError = `Role '${name}' needs both a model and base URL.`;
      return;
    }
    saving = true;
    try {
      await setupUpdateRole(
        name,
        draft.model.trim(),
        draft.baseUrl.trim(),
        draft.provider.trim(),
        draft.contextWindow.trim(),
        draft.reasoningEffort.trim() || 'auto',
        draft.userAgent.trim(),
      );
      await refresh();
      toast(`Role '${name}' updated`, 'success');
    } catch (err) {
      // A failed save usually means roles.json is structurally broken;
      // absorb the signal so the repair instructions stay on screen.
      if (!chatStore.absorbConfigError(err)) {
        actionError = friendlyError(err);
        toast(actionError, 'error');
      }
    } finally {
      saving = false;
    }
  }

  async function continueToApp() {
    await refresh();
    if (chatStore.setupComplete) {
      chatStore.closeSetup();
      await chatStore.loadChats();
      await chatStore.loadCommands();
    }
  }

  /** Load the MCP server list + config path (refreshed after each edit). */
  async function loadMcp() {
    try {
      const result = await mcpList();
      mcpPath = result?.path ?? '';
      mcpServers = result?.servers ?? [];
    } catch (err) {
      mcpFormError = friendlyError(err);
    }
  }

  /** Parse a textarea of `KEY=VALUE` lines into an env map (blank lines and
   * lines without a key are ignored). */
  function parseMcpEnv(text: string): Record<string, string> {
    const env: Record<string, string> = {};
    for (const raw of text.split('\n')) {
      const line = raw.trim();
      if (!line) continue;
      const eq = line.indexOf('=');
      if (eq <= 0) continue;
      const key = line.slice(0, eq).trim();
      const value = line.slice(eq + 1).trim();
      if (key) env[key] = value;
    }
    return env;
  }

  /** One-line target for a server: the URL, or `command arg1 arg2`. */
  function mcpTarget(server: McpServer): string {
    if (server.kind === 'http') return server.url;
    return [server.command, ...(server.args ?? [])].filter(Boolean).join(' ');
  }

  async function addMcp(e: SubmitEvent) {
    e.preventDefault();
    mcpFormError = '';
    const name = mcpName.trim();
    if (!name) {
      mcpFormError = 'Name is required.';
      return;
    }
    if (mcpKind === 'http' && !mcpUrl.trim()) {
      mcpFormError = 'A URL is required for an HTTP server.';
      return;
    }
    if (mcpKind === 'stdio' && !mcpCommand.trim()) {
      mcpFormError = 'A command is required for a stdio server.';
      return;
    }

    const payload: {
      name: string;
      command?: string;
      args?: string[];
      env?: Record<string, string>;
      url?: string;
      trust: boolean;
    } = { name, trust: mcpTrust };
    if (mcpKind === 'http') {
      payload.url = mcpUrl.trim();
    } else {
      payload.command = mcpCommand.trim();
      const args = mcpArgs.trim().split(/\s+/).filter(Boolean);
      if (args.length) payload.args = args;
      const env = parseMcpEnv(mcpEnv);
      if (Object.keys(env).length) payload.env = env;
    }

    saving = true;
    try {
      await mcpAdd(payload);
      mcpName = '';
      mcpKind = 'stdio';
      mcpUrl = '';
      mcpCommand = '';
      mcpArgs = '';
      mcpEnv = '';
      mcpTrust = false;
      await loadMcp();
      toast('MCP server added', 'success');
    } catch (err) {
      mcpFormError = friendlyError(err);
      toast(mcpFormError, 'error');
    } finally {
      saving = false;
    }
  }

  async function removeMcp(name: string) {
    mcpFormError = '';
    try {
      await mcpRemove(name);
      const next = { ...mcpResults };
      delete next[name];
      mcpResults = next;
      await loadMcp();
      toast('MCP server removed', 'success');
    } catch (err) {
      mcpFormError = friendlyError(err);
      toast(mcpFormError, 'error');
    }
  }

  async function testMcp(name: string) {
    mcpFormError = '';
    mcpTesting = name;
    try {
      const result = await mcpTest(name);
      mcpResults = { ...mcpResults, [name]: result as McpTestResult };
    } catch (err) {
      mcpResults = {
        ...mcpResults,
        [name]: { ok: false, tools: [], error: friendlyError(err) },
      };
    } finally {
      mcpTesting = '';
    }
  }
</script>

<div class="setup">
  <div class="setup-head">
    {#if chatStore.setupComplete}
      <BusyButton class="back" onclick={continueToApp}>back</BusyButton>
    {/if}
    <div class="setup-title">Setup Raggie</div>
  </div>

  <div class="setup-body">
    {#if chatStore.configError}
      <div class="section config-error">
        <div class="step">Configuration problem</div>
        <div class="config-path">{chatStore.configError.path}</div>
        <div class="config-message">{chatStore.configError.message}</div>
        {#if chatStore.configError.issues?.length}
          <ul class="config-issues">
            {#each chatStore.configError.issues as issue (issue.path)}
              <li>
                <span class="issue-path">{issue.path || '(root)'}</span>
                <span class="issue-msg">{issue.message}</span>
              </li>
            {/each}
          </ul>
        {/if}
        <ol class="config-instructions">
          {#each chatStore.configError.instructions ?? [] as line (line)}
            <li>{line}</li>
          {/each}
        </ol>
      </div>
    {/if}

    <div class="section">
      <div class="step">Step 1 - API keys</div>
      {#if (chatStore.setupData?.keys ?? []).length > 0}
        <div class="keys">
          {#each chatStore.setupData?.keys ?? [] as k (k.id)}
            <div class="key-block">
              <div class="key-row">
                <span class="key-provider">{k.provider || 'custom'}</span>
                <span class="key-url">{k.baseUrl}</span>
                <button class="key-set" onclick={() => startKeyEdit(k.id)}>set key</button>
                <BusyButton class="key-remove" onclick={() => removeKey(k.id)}>remove</BusyButton>
              </div>
              {#if editingKeyId === k.id}
                <div class="key-edit">
                  <label>
                    new key
                    <input
                      id="setup-edit-key"
                      name="apiKey"
                      bind:value={editKeyValue}
                      type="password"
                      autocomplete="off"
                    />
                  </label>
                  <BusyButton class="primary" onclick={confirmKeyEdit} disabled={saving}>
                    {saving ? 'saving...' : 'save key'}
                  </BusyButton>
                  <button class="key-remove" onclick={cancelKeyEdit}>cancel</button>
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {:else}
        <div class="empty">No API keys configured yet.</div>
      {/if}

      <form class="key-form" onsubmit={addKey}>
          <div class="field-row">
          <label>
            provider
            <select id="setup-key-provider" name="provider" bind:value={provider} onchange={providerChanged}>
              <option value="" disabled selected>choose</option>
              {#each chatStore.setupData?.providers ?? [] as p (p.name)}
                <option value={p.name}>{p.name}</option>
              {/each}
            </select>
          </label>
          <label>
            base url
            <input id="setup-key-base-url" name="baseUrl" bind:value={baseUrl} placeholder={providerSuggestions[provider] ?? 'https://...'} />
          </label>
        </div>
        <label>
          api key
          <input id="setup-key-api-key" name="apiKey" bind:value={apiKey} type="password" autocomplete="off" />
        </label>
        <div class="form-error" aria-live="polite">{actionError}</div>
        <div class="form-actions">
          <button class="primary" disabled={saving} type="submit">
            {saving ? 'saving...' : 'add key'}
          </button>
        </div>
      </form>
    </div>

    <div class="section">
      <div class="step">Step 2 - Agent roles</div>
      {#if !(chatStore.setupData?.roles ?? []).length}
        <div class="empty">
          {#if chatStore.configError}
            No usable roles could be read from the file above. Fix the reported problems
            there, then reload this page   the role editors appear once the file parses.
          {:else}
            No roles found. Add at least one role to
            <code>roles.json</code> in your config folder (the shape is:
            <code>&#123; "code": &#123; "model": "...", "base_url": "...", "provider": "..." &#125; &#125;</code>),
            or run <code>raggie setup</code> in a terminal once to seed the defaults.
          {/if}
        </div>
      {:else}
        {#each chatStore.setupData?.roles ?? [] as role (role.name)}
          <div class="role-row">
            <div class="role-name">{role.name}</div>
            <div class="role-fields">
              <label>
                model
                <input
                  id={`setup-role-${role.name}-model`}
                  name="model"
                  value={roleDrafts[role.name]?.model ?? ''}
                  oninput={(e) => {
                    const d = roleDrafts[role.name];
                    if (d) d.model = e.currentTarget.value;
                  }}
                />
              </label>
              <label>
                provider
                <select
                  id={`setup-role-${role.name}-provider`}
                  name="provider"
                  value={roleDrafts[role.name]?.provider ?? ''}
                  onchange={(e) => {
                    const d = roleDrafts[role.name];
                    if (!d) return;
                    d.provider = e.currentTarget.value;
                    // Auto-select the base URL matching the provider
                    // (key URL if it exists, provider default otherwise).
                    const correct = providerBaseUrl(d.provider);
                    if (correct) d.baseUrl = correct;
                  }}
                >
                  {#each roleProviderOptions(role.name) as p (p)}
                    <option value={p}>{p}</option>
                  {/each}
                </select>
              </label>
            </div>
            <div class="role-fields wide-row">
              <label>
                base url
                <select
                  id={`setup-role-${role.name}-url`}
                  name="baseUrl"
                  value={roleDrafts[role.name]?.baseUrl ?? role.baseUrl}
                  onchange={(e) => {
                    const d = roleDrafts[role.name];
                    if (d) d.baseUrl = e.currentTarget.value;
                  }}
                >
                  {#each roleBaseUrlOptions(role.name) as url, i (url)}
                    <option value={url}>{url}</option>
                  {/each}
                </select>
              </label>
            </div>
            <div class="role-fields">
              <label>
                context window
                <input
                  id={`setup-role-${role.name}-ctx`}
                  name="contextWindow"
                  value={roleDrafts[role.name]?.contextWindow ?? ''}
                  oninput={(e) => {
                    const d = roleDrafts[role.name];
                    if (d) d.contextWindow = e.currentTarget.value;
                  }}
                />
              </label>
              <label>
                reasoning effort
                <select
                  id={`setup-role-${role.name}-effort`}
                  name="reasoningEffort"
                  value={roleDrafts[role.name]?.reasoningEffort ?? 'auto'}
                  onchange={(e) => {
                    const d = roleDrafts[role.name];
                    if (d) d.reasoningEffort = e.currentTarget.value;
                  }}
                >
                  {#each roleEffortValues(role.name) as v (v)}
                    <option value={v}>{v}</option>
                  {/each}
                </select>
              </label>
            </div>
            <details class="role-advanced">
              <summary>advanced settings</summary>
              <label>
                user agent
                <input
                  id={`setup-role-${role.name}-ua`}
                  name="userAgent"
                  value={roleDrafts[role.name]?.userAgent ?? ''}
                  placeholder="default: raggie/<version>"
                  oninput={(e) => {
                    const d = roleDrafts[role.name];
                    if (d) d.userAgent = e.currentTarget.value;
                  }}
                />
              </label>
              <span class="hint">
                Optional. Sent as the User-Agent header on every provider
                request. Leave blank for the default.
              </span>
            </details>
            <BusyButton
              class="save-role"
              onclick={() => saveRole(role.name)}
              disabled={saving}
            >
              save
            </BusyButton>
          </div>
        {/each}
      {/if}
    </div>

    <div class="section">
      <div class="step">MCP servers (optional)</div>
      {#if mcpPath}
        <div class="hint mcp-path">{mcpPath}</div>
      {/if}

      {#if mcpServers.length > 0}
        <div class="keys">
          {#each mcpServers as server (server.name)}
            <div class="key-block">
              <div class="key-row">
                <span class="key-provider">{server.name}</span>
                <span class="mcp-kind">{server.kind}</span>
                {#if server.trust}
                  <span class="mcp-badge">trusted</span>
                {/if}
                <span class="key-url">{mcpTarget(server)}</span>
                <button
                  class="key-set"
                  onclick={() => testMcp(server.name)}
                  disabled={mcpTesting === server.name}
                >
                  {mcpTesting === server.name ? 'testing...' : 'test'}
                </button>
                <BusyButton class="key-remove" onclick={() => removeMcp(server.name)}>
                  remove
                </BusyButton>
              </div>
              {#if mcpResults[server.name]}
                <div class="mcp-result">
                  {#if mcpResults[server.name].ok}
                    <span class="mcp-ok">
                      connected{mcpResults[server.name].tools.length
                        ? ` - ${mcpResults[server.name].tools.join(', ')}`
                        : ' - no tools'}
                    </span>
                  {:else}
                    <span class="mcp-fail">
                      {mcpResults[server.name].error || 'failed to connect'}
                    </span>
                  {/if}
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {:else}
        <div class="empty">No MCP servers configured yet.</div>
      {/if}

      <form class="key-form" onsubmit={addMcp}>
        <div class="field-row mcp-row">
          <label>
            name
            <input id="setup-mcp-name" name="name" bind:value={mcpName} placeholder="my-server" />
          </label>
          <label>
            transport
            <select id="setup-mcp-kind" name="kind" bind:value={mcpKind}>
              <option value="stdio">stdio</option>
              <option value="http">http</option>
            </select>
          </label>
        </div>
        {#if mcpKind === 'http'}
          <label>
            url
            <input id="setup-mcp-url" name="url" bind:value={mcpUrl} placeholder="https://..." />
          </label>
        {:else}
          <div class="field-row">
            <label>
              command
              <input id="setup-mcp-command" name="command" bind:value={mcpCommand} placeholder="npx" />
            </label>
            <label>
              args
              <input id="setup-mcp-args" name="args" bind:value={mcpArgs} placeholder="-y @modelcontextprotocol/server-filesystem" />
            </label>
          </div>
          <label>
            env
            <textarea
              id="setup-mcp-env"
              name="env"
              bind:value={mcpEnv}
              rows="3"
              placeholder="KEY=VALUE"
            ></textarea>
          </label>
        {/if}
        <label class="mcp-trust">
          <input type="checkbox" name="trust" bind:checked={mcpTrust} />
          trust this server
        </label>
        <div class="form-error" aria-live="polite">{mcpFormError}</div>
        <div class="form-actions">
          <button class="primary" disabled={saving} type="submit">
            {saving ? 'saving...' : 'add server'}
          </button>
        </div>
      </form>
      <div class="hint restart-hint">Changes take effect after restarting Raggie.</div>
    </div>
  </div>
</div>

<style>
  .setup {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    background: var(--bg);
  }

  /* Fixed title bar: outside the scroll area below, so it stays put while
     the sections scroll. Mirrors the chat header   same padding, height and
     bottom rule   so both pages share the same shell. */
  .setup-head {
    display: flex;
    align-items: center;
    gap: var(--sp-10);
    padding: var(--sp-6);
    /* Same outer height as the chat header: control row + vertical padding
       + the bottom rule (border-box, so the border is included here). */
    height: calc(var(--control-sm) + 2 * var(--sp-6) + var(--border-w));
    border-bottom: var(--border-w) solid var(--border);
    flex: 0 0 auto;
  }

  .setup-title {
    font-size: var(--fs-title);
    font-weight: 600;
    line-height: 1;
  }

  /* Back button (leaves the setup page for the chat list). Inline control
     sized like the other small actions on this page, with extra side
     padding so the label is not crammed against its border. */
  .setup :global(.back) {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    height: var(--control-sm);
    padding: 0 var(--sp-6);
    border: var(--border-w) solid var(--border);
    background: var(--bg);
    color: var(--fg-muted);
    white-space: nowrap;
  }

  .setup :global(.back:hover:enabled) {
    background: var(--bg-hover-alt);
    color: var(--fg);
  }

  .setup-body {
    flex: 1;
    /* The body is the scroll container now (the head above stays fixed),
       so it must be allowed to shrink below its content. Without this the
       flex item grows to fit every section and the page stops scrolling. */
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: var(--sp-12);
    /* Page padding lives here (not on .setup) so the header's bottom rule
       can span the full width like the chat header's does. */
    padding: var(--sp-14) var(--sp-12);
  }

  .section {
    border: var(--border-w) solid var(--border);
    padding: var(--sp-8);
  }

  .step {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--fg);
    margin-bottom: var(--sp-6);
  }

  .empty {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--fg-muted);
    padding: var(--sp-4) 0 var(--sp-4);
  }

  .empty code {
    color: var(--fg);
  }

  .config-error {
    border-color: var(--danger-fg);
  }

  .config-path {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--danger-fg);
    word-break: break-all;
    margin-bottom: var(--sp-3);
  }

  .config-message {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--fg);
    margin-bottom: var(--sp-5);
  }

  .config-issues,
  .config-instructions {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    margin: 0 0 var(--sp-6);
    padding-left: var(--sp-8);
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg);
  }

  .issue-path {
    color: var(--warn-fg);
    margin-right: var(--sp-3);
  }

  .issue-msg {
    color: var(--fg-muted);
  }

  .keys {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
    margin-bottom: var(--sp-6);
  }

  .key-block {
    border-bottom: var(--border-w) solid var(--border-soft);
    padding-bottom: var(--sp-3);
  }

  .key-row {
    display: flex;
    align-items: baseline;
    gap: var(--sp-5);
    padding: var(--sp-3) 0;
  }

  .key-provider {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--warn-fg);
    white-space: nowrap;
  }

  .key-url {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg);
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .key-set {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    height: var(--control-sm);
    padding: 0 var(--sp-3);
    border: var(--border-w) solid var(--border);
    background: var(--bg);
  }

  .key-set:hover {
    background: var(--bg-hover-alt);
  }

  .key-edit {
    display: flex;
    align-items: flex-end;
    gap: var(--sp-5);
    padding: var(--sp-4) 0 var(--sp-4);
  }

  .setup :global(.key-remove) {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    height: var(--control-sm);
    padding: 0 var(--sp-3);
    border: var(--border-w) solid var(--border);
    background: var(--bg);
    color: var(--fg-muted);
  }

  .setup :global(.key-remove:hover) {
    color: var(--danger-fg);
    border-color: var(--danger-fg);
  }

  .key-form {
    display: flex;
    flex-direction: column;
    gap: var(--sp-5);
    padding-top: var(--sp-4);
  }

  .field-row {
    display: flex;
    gap: var(--sp-6);
  }

  /* The provider select stays content-sized; the base-url label flexes
     to take the remaining row width (and stretches its input). */
  .field-row label:first-child {
    flex: 0 0 auto;
  }

  .field-row label:nth-child(2),
  .field-row label:last-child {
    flex: 1;
    min-width: 0;
  }

  .field-row input {
    width: 100%;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg);
  }

  input,
  select {
    height: var(--control-md);
    padding: 0 var(--sp-4);
    border: var(--border-w) solid var(--border);
    background: var(--bg);
    font-family: var(--mono);
    font-size: var(--fs-sm);
  }

  .form-error {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--danger-fg);
    min-height: 14px;
  }

  .form-actions {
    display: flex;
    gap: var(--sp-5);
  }

  .setup :global(.primary) {
    height: var(--control-md);
    padding: 0 var(--sp-7);
    background: var(--primary-bg);
    color: var(--primary-fg);
    border: var(--border-w) solid var(--primary-bg);
    font-size: var(--fs-md);
  }

  .setup :global(.primary:hover:enabled) {
    background: var(--primary-bg-hover);
  }

  .role-row {
    display: flex;
    flex-direction: column;
    gap: var(--sp-4);
    padding: var(--sp-5) 0;
    border-bottom: var(--border-w) solid var(--border-soft);
  }

  .role-name {
    font-family: var(--mono);
    font-size: var(--fs-md);
    font-weight: 500;
  }

  .role-fields {
    display: flex;
    gap: var(--sp-6);
    margin-bottom: var(--sp-4);
  }

  .role-fields label {
    flex: 1;
    min-width: 0;
  }

  /* Full-width rows (base url)   the label and its control span the row. */
  .wide-row label,
  .role-fields input,
  .role-fields select {
    width: 100%;
  }

  /* Collapsible advanced settings block inside each role row. */
  .role-advanced {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
    margin-bottom: var(--sp-4);
  }

  .role-advanced summary {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--fg-muted);
    cursor: pointer;
  }

  .role-advanced input {
    width: 100%;
  }

  .hint {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg-muted);
  }

  /* The restart notice sits below the MCP form; give it breathing room
     from the form actions above it. */
  .restart-hint {
    margin-top: var(--sp-6);
  }

  /* Filled primary look and the same dimensions as the other primary
     actions (add key) so the setup controls read consistently. */
  .setup :global(.save-role) {
    align-self: flex-start;
    height: var(--control-md);
    padding: 0 var(--sp-7);
    font-size: var(--fs-md);
    background: var(--primary-bg);
    color: var(--primary-fg);
    border: var(--border-w) solid var(--primary-bg);
  }

  .setup :global(.save-role:hover:enabled) {
    background: var(--primary-bg-hover);
  }

  .mcp-path {
    word-break: break-all;
    margin-bottom: var(--sp-6);
  }

  /* The name field flexes; the transport select stays content-sized. */
  .mcp-row label:first-child {
    flex: 1;
    min-width: 0;
  }

  .mcp-row label:last-child {
    flex: 0 0 auto;
  }

  .mcp-kind {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg-muted);
    white-space: nowrap;
  }

  .mcp-badge {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--fg-muted);
    border: var(--border-w) solid var(--border);
    padding: 0 var(--sp-3);
    white-space: nowrap;
  }

  .mcp-result {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    padding-bottom: var(--sp-3);
    word-break: break-word;
  }

  .mcp-ok {
    color: var(--fg-muted);
  }

  .mcp-fail {
    color: var(--danger-fg);
  }

  /* Inline checkbox row: the shared label/input sizing assumes a stacked
     field, so keep the box compact and put the text beside it. */
  .mcp-trust {
    flex-direction: row;
    align-items: center;
    gap: var(--sp-3);
  }

  .mcp-trust input {
    width: auto;
    height: auto;
    padding: 0;
  }

  /* Multiline env editor: the shared input/select sizing does not fit a
     textarea, so give it its own box. */
  textarea {
    padding: var(--sp-3) var(--sp-4);
    border: var(--border-w) solid var(--border);
    background: var(--bg);
    font-family: var(--mono);
    font-size: var(--fs-sm);
    resize: vertical;
  }

  .key-set:disabled {
    cursor: default;
    opacity: 0.6;
  }
</style>
