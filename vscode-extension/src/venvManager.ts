import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";

/** Python interpreters tried in order when bootstrapping the venv. */
const PYTHON_CANDIDATES = ["python3", "python"];

/** Platforms where the stdlib-venv bootstrap applies: Linux and the BSDs. */
const VENV_PLATFORMS: ReadonlySet<string> = new Set([
  "linux",
  "freebsd",
  "openbsd",
  "netbsd",
  "dragonfly",
]);

/** True only on the supported venv platforms; darwin and win32 excluded. */
export function isVenvPlatform(): boolean {
  return VENV_PLATFORMS.has(process.platform);
}

/** Location of the dedicated raggie virtual environment. */
export function venvDir(): string {
  return path.join(os.homedir(), ".config", "raggie", "venv");
}

/** Unix venv layout entrypoint for the Raggie CLI (no Scripts branch: win32 excluded). */
export function venvRaggiePath(): string {
  return path.join(venvDir(), "bin", "raggie");
}

/** hasCommand pattern from extension.ts, scoped to this module. */
function commandAvailable(cmd: string): Promise<boolean> {
  return new Promise((resolve) => {
    const child = spawn(cmd, ["--version"], { stdio: "ignore" });
    child.on("error", () => resolve(false));
    child.on("exit", (code: number | null) => resolve(code === 0));
  });
}

/** First available interpreter from PYTHON_CANDIDATES, else undefined. */
export async function discoverPython(): Promise<string | undefined> {
  for (const candidate of PYTHON_CANDIDATES) {
    if (await commandAvailable(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

/**
 * Spawn a child with stdout/stderr piped to the OutputChannel (same pattern
 * as pipInstallRaggieCode) while also collecting the text so callers can
 * inspect it for known failure hints.
 */
function spawnLogged(
  cmd: string,
  args: string[],
  output: vscode.OutputChannel
): Promise<{ code: number | null; text: string }> {
  return new Promise((resolve, reject) => {
    output.appendLine(`[raggie] running: ${cmd} ${args.join(" ")}`);
    const child = spawn(cmd, args);
    let text = "";
    child.stdout?.on("data", (chunk: Buffer) => {
      output.append(String(chunk));
      text += String(chunk);
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      output.append(String(chunk));
      text += String(chunk);
    });
    child.on("error", (err: Error) => reject(err));
    child.on("exit", (code: number | null) => resolve({ code, text }));
  });
}

/**
 * True when raggie.server.pythonPath was left at its default (never set in
 * settings). Only then may the server start swap in the venv entrypoint.
 */
export function isDefaultPythonPath(
  config: vscode.WorkspaceConfiguration
): boolean {
  const inspect = config.inspect<string>("server.pythonPath");
  return (
    inspect?.globalValue === undefined &&
    inspect?.workspaceValue === undefined &&
    inspect?.workspaceFolderValue === undefined
  );
}

/**
 * Ensure the stdlib venv at ~/.config/raggie/venv exists with raggiecode
 * installed, and return the venv raggie entrypoint path.
 */
export async function ensureVenv(
  output: vscode.OutputChannel
): Promise<string> {
  const entrypoint = venvRaggiePath();
  if (fs.existsSync(entrypoint)) {
    return entrypoint;
  }

  const python = await discoverPython();
  if (!python) {
    throw new Error(
      "Raggie needs Python to set up its environment, but neither python3 nor python was found on PATH. Please install Python and restart VS Code."
    );
  }

  // `python -m venv` does not create missing parent directories.
  fs.mkdirSync(path.dirname(venvDir()), { recursive: true });

  const venv = await spawnLogged(python, ["-m", "venv", venvDir()], output);
  if (venv.code !== 0) {
    if (/ensurepip|no module named venv/i.test(venv.text)) {
      throw new Error(
        "Creating the Raggie Python environment failed because ensurepip or the venv module is missing. On Debian/Ubuntu, install the python3-venv package; on OpenBSD and other BSDs, install the python ensurepip package. Then reload VS Code and try again."
      );
    }
    throw new Error(
      `Creating the Raggie Python environment failed (python -m venv exited with code ${venv.code}).`
    );
  }

  const pip = await spawnLogged(
    path.join(venvDir(), "bin", "python"),
    ["-m", "pip", "install", "raggiecode"],
    output
  );
  if (pip.code !== 0) {
    throw new Error(
      `Installing Raggie Code into its environment failed (pip exited with code ${pip.code}). See the Raggie Server output for details.`
    );
  }

  return entrypoint;
}
