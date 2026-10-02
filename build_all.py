#!/usr/bin/env python3
"""Full build pipeline for raggiecode: web UI, Python package data, extension.

Steps:
  1. Install web-ui dependencies (pnpm) and build the Vite bundle.
  2. Sync ``web-ui/dist`` into ``src/acp_server/webui`` (reuses sync_webui.py)
     so the raggie wheel ships the UI.
  3. Mirror ``web-ui/dist`` into ``vscode-extension/media/ui``.
  4. Install extension dependencies (npm) and compile the TypeScript.
  5. Package the extension into ``raggie-code-<version>.vsix``.

Usage:
  python3 build_all.py               # full pipeline
  python3 build_all.py --no-install  # skip dependency installs
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB_UI = ROOT / "web-ui"
EXTENSION = ROOT / "vscode-extension"
WEBUI_DEST = ROOT / "src" / "acp_server" / "webui"
MEDIA_UI = EXTENSION / "media" / "ui"


def fail(message: str) -> None:
    print(f"error: {message}")
    sys.exit(1)


def run(command: list[str], cwd: Path, use_path_lookup: bool = True) -> None:
    pretty = " ".join(command)
    print(f"  [{cwd.relative_to(ROOT)}] $ {pretty}")
    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        fail(f"command failed with exit code {result.returncode}: {pretty}")


def mirror_dir(source: Path, dest: Path) -> int:
    """Replace dest with a copy of source. Iterative (no recursion)."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    return sum(1 for _ in dest.rglob("*") if _.is_file())


def ensure_webui_deps(no_install: bool) -> None:
    if shutil.which("pnpm") is None:
        fail("pnpm not found on PATH (needed to build web-ui)")
    node_modules = WEB_UI / "node_modules"
    if no_install and not node_modules.exists():
        fail("--no-install set but web-ui/node_modules is missing")
    if not no_install:
        run(["pnpm", "install", "--frozen-lockfile"], WEB_UI)


def build_webui() -> None:
    run(["pnpm", "build"], WEB_UI)
    if not (WEB_UI / "dist" / "index.html").is_file():
        fail("web-ui/dist/index.html not found after build")


def ensure_extension_deps(no_install: bool) -> None:
    node_modules = EXTENSION / "node_modules"
    if no_install and not node_modules.exists():
        fail("--no-install set but vscode-extension/node_modules is missing")
    if not no_install:
        # npm ci when a lockfile exists, plain install otherwise.
        if (EXTENSION / "package-lock.json").is_file():
            run(["npm", "ci"], EXTENSION)
        else:
            run(["npm", "install"], EXTENSION)


def compile_extension() -> None:
    # Invoke tsc through node: node_modules/.bin wrappers can lose their
    # executable bit and fail with "Permission denied".
    tsc = EXTENSION / "node_modules" / "typescript" / "bin" / "tsc"
    if not tsc.is_file():
        fail("typescript not installed in vscode-extension")
    run(["node", "node_modules/typescript/bin/tsc", "-p", "./"], EXTENSION)


def package_extension() -> Path:
    vsce_on_path = shutil.which("vsce")
    if vsce_on_path:
        run(["vsce", "package", "--no-dependencies"], EXTENSION)
    else:
        run(["npx", "--yes", "vsce", "package", "--no-dependencies"], EXTENSION)
    vsix_files = sorted(EXTENSION.glob("*.vsix"), key=lambda p: p.stat().st_mtime)
    if not vsix_files:
        fail("no .vsix produced by vsce package")
    return vsix_files[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="skip dependency installs (node_modules must already exist)",
    )
    args = parser.parse_args()

    print("[1/5] web-ui: install deps + build")
    ensure_webui_deps(args.no_install)
    build_webui()

    print("[2/5] sync web UI into src/acp_server/webui")
    # Reuse sync_webui so the package-data copy has a single source of truth.
    import sync_webui  # noqa: E402  (ROOT must be on sys.path; it is for scripts)

    sync_webui.main()

    print("[3/5] mirror web UI into vscode-extension/media/ui")
    count = mirror_dir(WEB_UI / "dist", MEDIA_UI)
    print(f"  copied {count} files to vscode-extension/media/ui")

    print("[4/5] vscode-extension: install deps + compile")
    ensure_extension_deps(args.no_install)
    compile_extension()

    print("[5/5] vscode-extension: package .vsix")
    vsix = package_extension()
    print(f"  packaged {vsix.relative_to(ROOT)}")

    print("build_all: done")
    print()
    print("Load the extension into VS Code:")
    print(f"  code --install-extension {vsix.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
