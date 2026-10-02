#!/usr/bin/env python3
"""Sync the built web UI into the acp_server package so pip ships it.

Run this after rebuilding the frontend (web-ui: `pnpm build`) and before
building a release wheel (`python -m build` / `pip wheel .`). It copies
``web-ui/dist`` into ``src/acp_server/webui``, which pyproject.toml packs as
package data. ``acp_server.http_transport.default_web_dist`` picks up the
bundled copy in installed environments; development checkouts keep using
``web-ui/dist`` directly.
"""

import shutil
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "web-ui" / "dist"
DEST = Path(__file__).resolve().parent / "src" / "acp_server" / "webui"


def main() -> None:
    if not (SOURCE / "index.html").is_file():
        print(f"error: {SOURCE}/index.html not found - run `pnpm install && pnpm build` in web-ui/ first")
        sys.exit(1)

    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST)
    files = sorted(p.relative_to(DEST.parent).as_posix() for p in DEST.rglob("*") if p.is_file())
    print(f"synced {len(files)} files to src/acp_server/webui:")
    for name in files:
        print(f"  {name}")


if __name__ == "__main__":
    main()
