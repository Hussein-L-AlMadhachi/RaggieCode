export type Role = 'user' | 'agent';

export interface ChatListItem {
  id: string;
  title: string;
  updatedAt: string;
  preview?: string;
  previewRole?: Role;
}

export type ToolStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

export interface UserMessage {
  id: string;
  kind: 'user';
  text: string;
  /** Backend message id (DB row), for search + deep links. */
  mid?: number;
  /** True for agent-generated handover prompts (gets a dedicated label). */
  handover?: boolean;
}

export interface AgentMessage {
  id: string;
  kind: 'agent';
  text: string;
  /** Backend message id (DB row), for search + deep links. */
  mid?: number;
}

export interface ThoughtMessage {
  id: string;
  kind: 'thought';
  text: string;
}

/** Command-handler output surfaced from the backend (e.g. /help, /skills). */
export interface NoticeMessage {
  id: string;
  kind: 'notice';
  text: string;
}

export interface ToolMessage {
  id: string;
  kind: 'tool';
  toolCallId: string;
  title: string;
  status: ToolStatus;
  /** Pretty JSON of the tool call parameters. */
  input?: string;
  output?: string;
}

/** One piece of live work shown inside a subagent block (tool call or thought). */
export interface ToolChild {
  id: string;
  kind: 'tool';
  toolCallId: string;
  title: string;
  status?: ToolStatus;
  input?: string;
  output?: string;
}

export interface ThoughtChild {
  id: string;
  kind: 'thought';
  text?: string;
}

/** Children of a subagent block: tool rows, thought rows, or nested
 * subagent blocks (a subagent that dispatched its own subagent). */
export type SubagentChild = ToolChild | ThoughtChild | SubagentMessage;

/** Streaming block for a DispatchSubagent run (one per subagent session). */
export interface SubagentMessage {
  id: string;
  kind: 'subagent';
  subagentSessionId: string;
  /** Nesting level: 1 = dispatched by the main agent, 2 = a subagent's subagent. */
  depth: number;
  role?: string;
  /** The prompt handed to the subagent (shown right-aligned). */
  prompt?: string;
  resumed?: boolean;
  done: boolean;
  errored: boolean;
  /** Accumulated subagent response (markdown), streamed live. */
  text: string;
  children: SubagentChild[];
}

/** Backend frame for one subagent event (method session/subagent_update). */
export interface SubagentUpdate {
  sessionId?: string;
  phase: 'start' | 'chunk' | 'thought' | 'tool_call' | 'tool_result' | 'error' | 'end';
  subagentSessionId: string;
  depth?: number;
  role?: string;
  prompt?: string;
  resumed?: boolean;
  text?: string;
  title?: string;
  toolCallId?: string;
  status?: ToolStatus;
  input?: string;
  output?: string;
  errored?: boolean;
}

export type Message =
  | UserMessage
  | AgentMessage
  | ThoughtMessage
  | NoticeMessage
  | ToolMessage
  | SubagentMessage;

export interface PermissionOption {
  optionId: string;
  name: string;
  kind: string;
}

/** Predefined answer choice for an AskUser question. */
export interface AskOption {
  label: string;
  description?: string;
}

export type Pending =
  | { kind: 'perm'; requestId: string; title: string; detail?: string; options: PermissionOption[] }
  | {
      kind: 'ask';
      requestId: string;
      question: string;
      /** Predefined options (label/description) shown as clickable choices. */
      options?: AskOption[];
      /** Whether several options may be selected together. */
      allowMultiple?: boolean;
    };

export interface TextBlock {
  type: string;
  text?: string;
}

/** Raw ACP session-update payload (one frame of the SSE stream). */
export interface SessionUpdate {
  sessionUpdate: string;
  toolCallId?: string;
  title?: string;
  status?: ToolStatus;
  content?: TextBlock | TextBlock[] | null;
  rawOutput?: unknown;
  rawInput?: unknown;
}

export interface CommandInfo {
  name: string;
  description: string;
  usage?: string;
  choices?: string[] | null;
  kind?: 'action' | 'choices' | 'input';
}

export interface HealthStatFunction {
  name: string;
  file: string;
  line: number;
  score: number;
  severity: string;
}

export interface HealthStatObject {
  name: string;
  file: string;
  line: number;
  severity: string;
  score: number;
  methods: number;
  attributes: number;
  lines: number;
}

export interface HealthStats {
  healthy: boolean;
  functions: HealthStatFunction[];
  objects: HealthStatObject[];
}

export interface TodoTask {
  id: number;
  goal: string;
  requirements?: string | null;
  notes?: string | null;
  context?: string | null;
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled';
  orderIndex: number;
}

export interface TodoList {
  id: number;
  status: 'pending' | 'approved';
  tasks: TodoTask[];
}

export interface SetupKey {
  id: string;
  provider: string;
  baseUrl: string;
  masked: string;
}

export interface SetupRole {
  name: string;
  model: string;
  baseUrl: string;
  provider: string;
  contextWindow: number | string;
  reasoningEffort: string;
  userAgent: string;
}

export interface SetupProvider {
  name: string;
  baseUrl: string;
  reasoningEffortValues: string[];
}

/** A single validation problem found in a config file. */
export interface ConfigIssue {
  /** Dotted/bracketed location inside the file, e.g. "code.model". */
  path: string;
  message: string;
}

/**
 * Structured signal emitted by the server when a config file cannot be used.
 * The web UI reacts by forcing the setup page open and rendering `issues`.
 */
export interface ConfigError {
  kind: string;
  path: string;
  message: string;
  issues: ConfigIssue[];
  instructions: string[];
}

export interface SetupStatus {
  setupComplete: boolean;
  setupRequired?: boolean;
  configError?: ConfigError | null;
  keys: SetupKey[] | null;
  roles: SetupRole[] | null;
  providers?: SetupProvider[] | null;
  /** Role name this agent instance runs as (used to show model + effort). */
  activeRole?: string;
}

/** One configured MCP server (mcp/list). */
export interface McpServer {
  name: string;
  kind: 'stdio' | 'http' | 'unknown';
  command: string;
  args: string[];
  env: Record<string, string>;
  url: string;
  trust: boolean;
}

/** mcp/list payload: config file path + the configured servers. */
export interface McpStatus {
  path: string;
  servers: McpServer[];
}

/** Result of a live MCP connection test (mcp/test). */
export interface McpTestResult {
  ok: boolean;
  tools: string[];
  error?: string;
}

/** A full-text search hit over user messages. */
export interface MessageSearchResult {
  chatId: number;
  title: string;
  messageId: number;
  snippet: string;
  updatedAt: string;
}

/** SSE frame: either a notification (method+params) or the final response. */
export interface Frame {
  method?: string;
  params?: any;
  id?: number | string;
  result?: any;
  error?: any;
}
