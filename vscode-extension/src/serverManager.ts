import * as vscode from "vscode";
import { spawn, type ChildProcess } from "node:child_process";
import {
  ensureVenv,
  isDefaultPythonPath,
  isVenvPlatform,
} from "./venvManager";
import * as net from "node:net";
import * as path from "node:path";
import * as http from "node:http";

/** Lifecycle states surfaced through onStateChange. */
export type ServerState = "stopped" | "starting" | "running" | "error";

const READY_TIMEOUT_MS = 30_000;
const POLL_INTERVAL_MS = 300;
const PROBE_TIMEOUT_MS = 1_500;
const KILL_GRACE_MS = 3_000;
const LOG_RING_SIZE = 200;

/** What the raggie server's /identity endpoint reports about itself. */
export interface Identity {
  raggie: boolean;
  cwd?: string;
  port?: number;
  /** True when any HTTP process (raggie or not) answered on the port. */
  answered?: boolean;
}

function parseIdentity(body: string): Identity {
  try {
    const payload = JSON.parse(body) as {
      service?: unknown;
      cwd?: unknown;
      port?: unknown;
    };
    if (payload.service !== "raggie-acp") {
      return { raggie: false, answered: true };
    }
    return {
      raggie: true,
      cwd: typeof payload.cwd === "string" ? payload.cwd : undefined,
      port: typeof payload.port === "number" ? payload.port : undefined,
      answered: true,
    };
  } catch {
    // HTTP body that is not JSON: a non-raggie server is listening.
    return { raggie: false, answered: true };
  }
}

/**
 * Ask the server listening on `port` what it is. Resolves
 * { raggie: false } for anything that is not a raggie server with an
 * /identity endpoint (including no listener at all).
 */
async function probeIdentity(port: number, timeoutMs: number): Promise<Identity> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value: Identity) => {
      if (!settled) {
        settled = true;
        req.destroy();
        resolve(value);
      }
    };

    // The tsconfig lib is ES2022 without DOM, so the typed global fetch is not
    // guaranteed; probe with node:http instead.
    const req = http.get(
      { host: "127.0.0.1", port, path: "/identity", timeout: timeoutMs },
      (res) => {
        let body = "";
        res.setEncoding("utf8");
        res.on("data", (chunk: string) => {
          body += chunk;
        });
        res.on("end", () => finish(parseIdentity(body)));
        res.on("error", () => finish({ raggie: false }));
      }
    );
    req.on("timeout", () => finish({ raggie: false }));
    req.on("error", () => finish({ raggie: false }));
  });
}

/** Compare absolute paths; case-insensitive on win32, case-sensitive elsewhere. */
export function isSamePath(a: string, b: string): boolean {
  const normalize = (p: string) => {
    const resolved = path.resolve(p);
    return process.platform === "win32" ? resolved.toLowerCase() : resolved;
  };
  return normalize(a) === normalize(b);
}

/**
 * Grab a free ephemeral port by briefly binding to port 0 on loopback.
 * Iterative: a single promise, no recursion.
 */
function pickFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    let found = 0;
    server.once("error", (err: Error) => {
      server.close();
      reject(err);
    });
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      if (addr && typeof addr === "object") {
        found = addr.port;
      }
      server.close(() => {
        if (found > 0) {
          resolve(found);
        } else {
          reject(new Error("could not pick a free port"));
        }
      });
    });
  });
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Owns the lifecycle of the `raggie` CLI server process for the workspace.
 * Emits state transitions and (once per incident) an error message built from
 * the most recent log lines.
 */
export class RaggieServerManager {
  private state: ServerState = "stopped";
  private child: ChildProcess | null = null;
  /** True when the running server was already up before start() (not ours). */
  private external = false;
  /** Actual port the running server answers on; undefined until bound. */
  private boundPort?: number;
  /** Incremented on start/stop so stale async loops become no-ops. */
  private generation = 0;
  private logs: string[] = [];
  private errorSurfaced = false;

  private readonly stateEmitter = new vscode.EventEmitter<ServerState>();
  private readonly errorEmitter = new vscode.EventEmitter<string>();

  /** Fires on every lifecycle transition: stopped/starting/running/error. */
  readonly onStateChange = this.stateEmitter.event;
  /** Fires at most once per incident with a message including recent logs. */
  readonly onError = this.errorEmitter.event;

  constructor(
    private readonly output: vscode.OutputChannel,
    private readonly getCwd: () => string | undefined
  ) {}

  get current(): ServerState {
    return this.state;
  }

  /**
   * Verified port of THIS window's raggie server while running, otherwise
   * undefined. Deliberately no configured-port fallback: while starting,
   * stopped, or errored, the configured port may belong to another window's
   * project instance, and silently hitting it would surface that project's
   * chats in this window. Callers must handle undefined (not running here).
   */
  get port(): number | undefined {
    return this.isState("running") ? this.boundPort : undefined;
  }

  async start(): Promise<void> {
    if (this.state === "starting" || this.state === "running") {
      return;
    }

    const config = vscode.workspace.getConfiguration("raggie");
    const configuredPort = config.get<number>("server.port", 8765);
    const expectedCwd = this.getCwd();

    this.generation++;
    const gen = this.generation;
    this.errorSurfaced = false;
    this.logs = [];

    // Identify whatever is on the configured port. A raggie server for THIS
    // window's project (e.g. after a VS Code window reload) can be reused;
    // anything else must be left alone and we spawn our own server elsewhere.
    const identity = await probeIdentity(configuredPort, PROBE_TIMEOUT_MS);
    if (gen !== this.generation) {
      return;
    }
    if (
      identity.raggie &&
      expectedCwd !== undefined &&
      identity.cwd !== undefined &&
      isSamePath(identity.cwd, expectedCwd)
    ) {
      this.external = true;
      this.boundPort = identity.port ?? configuredPort;
      this.setState("running");
      return;
    }

    let spawnPort = configuredPort;
    if (identity.raggie) {
      spawnPort = await pickFreePort();
      if (gen !== this.generation) {
        return;
      }
      this.appendLog(
        `[raggie] port ${configuredPort} is used by a different project's raggie server (cwd: ${
          identity.cwd ?? "<unknown>"
        }); starting on a separate port`
      );
    } else if (identity.answered) {
      // Something non-raggie answered on the port; never attach to it.
      spawnPort = await pickFreePort();
      if (gen !== this.generation) {
        return;
      }
      this.appendLog(
        `[raggie] port ${configuredPort} is used by a non-raggie process; starting on a separate port`
      );
    }

    let pythonPath = config.get<string>("server.pythonPath", "raggie");
    const role = config.get<string>("server.role", "code");
    const extraArgs = config.get<string[]>("server.args", []);

    // On Linux/BSD, when the pythonPath was left at its default, bootstrap
    // (once) and use the dedicated stdlib venv instead of PATH resolution.
    if (isVenvPlatform() && isDefaultPythonPath(config)) {
      try {
        pythonPath = await ensureVenv(this.output);
      } catch (err) {
        this.fail(`Failed to prepare the Raggie Python environment: ${String(err)}`);
        return;
      }
      if (gen !== this.generation) {
        return;
      }
    }
    const args = [
      role,
      ".",
      "--web",
      "--acp-port",
      String(spawnPort),
      ...extraArgs,
    ];

    this.appendLog(
      `[raggie] starting: ${pythonPath} ${args.join(" ")} (cwd: ${expectedCwd ?? "<none>"})`
    );

    const child = spawn(pythonPath, args, {
      cwd: expectedCwd,
      // Plain spawn resolves commands via PATH when no path separator is
      // present, and executes the file directly when one is.
    });
    this.child = child;
    this.external = false;
    this.setState("starting");

    // Capture the bound port the child announces on stdout so the readiness
    // poll can also verify the child itself when serve_http had to fall back
    // from the requested port (e.g. another window's server owns it).
    let announcedPort: number | undefined;
    const announceRe = /raggie web ui: http:\/\/127\.0\.0\.1:(\d+)\//;
    child.stdout?.on("data", (chunk: Buffer) => {
      const text = String(chunk);
      this.appendLog(text);
      if (announcedPort === undefined) {
        const match = announceRe.exec(text);
        if (match) {
          announcedPort = Number(match[1]);
        }
      }
    });
    child.stderr?.on("data", (chunk: Buffer) => this.appendLog(String(chunk)));

    child.on("error", (err: Error) => {
      if (gen !== this.generation) {
        return;
      }
      this.appendLog(`[raggie] failed to spawn: ${err.message}`);
      this.fail(`Failed to start the Raggie server: ${err.message}`);
    });

    child.on("exit", (code: number | null, signal: string | null) => {
      if (gen !== this.generation) {
        return;
      }
      this.appendLog(`[raggie] exited (code: ${code}, signal: ${signal})`);
      if (this.state === "starting" || this.state === "running") {
        this.fail(
          `The Raggie server exited unexpectedly (code: ${code}, signal: ${signal}).`
        );
      }
    });

    // Iterative readiness poll, no recursion. Only trust a raggie server
    // whose identity matches this window's project directory. The child may
    // have fallen back to a different port than the one we requested, so the
    // announced port is probed as well.
    const deadline = Date.now() + READY_TIMEOUT_MS;
    while (gen === this.generation && Date.now() < deadline) {
      const candidates =
        announcedPort !== undefined && announcedPort !== spawnPort
          ? [spawnPort, announcedPort]
          : [spawnPort];
      let readyPort: number | undefined;
      let readyIdentity: Identity | undefined;
      for (const candidate of candidates) {
        const identity = await probeIdentity(candidate, PROBE_TIMEOUT_MS);
        if (gen !== this.generation) {
          return;
        }
        if (
          identity.raggie &&
          expectedCwd !== undefined &&
          identity.cwd !== undefined &&
          isSamePath(identity.cwd, expectedCwd)
        ) {
          readyPort = candidate;
          readyIdentity = identity;
          break;
        }
      }
      if (readyIdentity && readyPort !== undefined) {
        // If our child already died but a raggie server for this same project
        // answers on the port, the listener is an external process; remember
        // that so stop() does not kill it.
        if (child.exitCode !== null || child.signalCode !== null) {
          this.external = true;
          this.child = null;
        }
        this.boundPort = readyIdentity.port ?? readyPort;
        this.setState("running");
        return;
      }
      if (child.exitCode !== null || child.signalCode !== null) {
        break;
      }
      await sleep(POLL_INTERVAL_MS);
    }

    if (gen !== this.generation) {
      return;
    }
    if (this.isState("starting")) {
      // Server never became ready; take our child down and report.
      void this.killChild(child);
      this.child = null;
      this.fail(
        `The Raggie server did not become ready on port ${spawnPort} within ${
          READY_TIMEOUT_MS / 1000
        }s.`
      );
    }
  }

  async stop(): Promise<void> {
    this.generation++;
    const child = this.child;
    const wasExternal = this.external;
    this.child = null;
    this.external = false;
    this.boundPort = undefined;
    this.errorSurfaced = false;

    if (!child || wasExternal || child.exitCode !== null) {
      if (wasExternal && child) {
        this.appendLog("[raggie] leaving external server running");
      }
      this.setState("stopped");
      return;
    }

    this.appendLog("[raggie] stopping server");
    // Stopped first so the exit handler does not fire an error for this kill.
    this.setState("stopped");
    await this.killChild(child);
  }

  async restart(): Promise<void> {
    await this.stop();
    await this.start();
  }

  /** Last LOG_RING_SIZE lines of combined stdout/stderr. */
  getRecentLogs(): string {
    return this.logs.join("\n");
  }

  dispose(): void {
    this.generation++;
    const child = this.child;
    this.child = null;
    if (child && !this.external && child.exitCode === null) {
      void this.killChild(child);
    }
    this.external = false;
    this.boundPort = undefined;
    this.stateEmitter.dispose();
    this.errorEmitter.dispose();
  }

  private setState(state: ServerState): void {
    this.state = state;
    this.stateEmitter.fire(state);
  }

  /** Report an error exactly once per incident (reset on start/stop). */
  private fail(message: string): void {
    this.setState("error");
    if (this.errorSurfaced) {
      return;
    }
    this.errorSurfaced = true;
    const logs = this.getRecentLogs();
    this.errorEmitter.fire(logs ? `${message}\n${logs}` : message);
  }

  /** State check via method so TS does not narrow this.state in loops. */
  private isState(state: ServerState): boolean {
    return this.state === state;
  }

  private appendLog(chunk: string): void {
    for (const line of chunk.split(/\r?\n/)) {
      if (line.length === 0) {
        continue;
      }
      this.logs.push(line);
      if (this.logs.length > LOG_RING_SIZE) {
        this.logs.splice(0, this.logs.length - LOG_RING_SIZE);
      }
      this.output.appendLine(line);
    }
  }

  /** SIGTERM, then SIGKILL after a grace period on unix; taskkill on win32. */
  private async killChild(child: ChildProcess): Promise<void> {
    if (child.exitCode !== null || child.signalCode !== null) {
      return;
    }
    if (process.platform === "win32") {
      if (child.pid !== undefined) {
        spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"]);
      }
      return;
    }

    child.kill("SIGTERM");
    // Iterative grace-period wait, no recursion.
    const deadline = Date.now() + KILL_GRACE_MS;
    while (
      child.exitCode === null &&
      child.signalCode === null &&
      Date.now() < deadline
    ) {
      await sleep(100);
    }
    if (child.exitCode === null && child.signalCode === null) {
      child.kill("SIGKILL");
    }
  }
}
