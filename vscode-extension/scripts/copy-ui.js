"use strict";
// Builds the web UI (separate codebase in ../web-ui) and mirrors its dist/
// output into vscode-extension/media/ui so the packaged .vsix bundles it.
// Usage: node scripts/copy-ui.js
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const extensionRoot = path.resolve(__dirname, "..");
const webUiDir = path.resolve(extensionRoot, "..", "web-ui");
const distDir = path.join(webUiDir, "dist");
const destDir = path.join(extensionRoot, "media", "ui");

function fail(message) {
  console.error(`error: ${message}`);
  process.exit(1);
}

if (!fs.existsSync(path.join(webUiDir, "package.json"))) {
  fail(`web-ui not found at ${webUiDir}`);
}

// Build the web UI. pnpm is the project's package manager; fall back to npm.
const usePnpm = spawnSync("pnpm", ["--version"], { shell: true }).status === 0;
const build = spawnSync(
  usePnpm ? "pnpm" : "npm",
  usePnpm ? ["build"] : ["run", "build"],
  { cwd: webUiDir, stdio: "inherit", shell: true }
);
if (build.status !== 0) {
  fail("web-ui build failed");
}

if (!fs.existsSync(path.join(distDir, "index.html"))) {
  fail(`${distDir}/index.html not found after build`);
}

// Mirror dist/ -> media/ui/ with an iterative copy (no recursion).
fs.rmSync(destDir, { recursive: true, force: true });
fs.mkdirSync(destDir, { recursive: true });

const stack = [[distDir, destDir]];
let copied = 0;
while (stack.length > 0) {
  const [srcDir, outDir] = stack.pop();
  for (const entry of fs.readdirSync(srcDir, { withFileTypes: true })) {
    const src = path.join(srcDir, entry.name);
    const out = path.join(outDir, entry.name);
    if (entry.isDirectory()) {
      fs.mkdirSync(out, { recursive: true });
      stack.push([src, out]);
    } else {
      fs.copyFileSync(src, out);
      copied += 1;
    }
  }
}
console.log(`copied ${copied} files to ${destDir}`);
