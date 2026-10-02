"""ACP (Agent Client Protocol) server entry points for Raggie.

- ``run_stdio``: speaks JSON-RPC 2.0 over stdin/stdout (the standard ACP
  transport, used by editors such as Zed). All human-facing output is
  redirected to stderr so stdout stays a clean protocol channel.
- ``run_http``: serves the same ACP messages over HTTP POST; ``session/prompt``
  responses are streamed as Server-Sent Events.
"""

import asyncio
import sys
import uuid

import acp
from acp.core import AgentSideConnection
from acp.stdio import stdio_streams

import io_backend
from acp_server.agent import RaggieACPAgent


def run_stdio(role, debug=False, auto_approve=False, dev=False):
    io_backend.set_mode(io_backend.MODE_ACP, auto_approve=auto_approve)
    io_backend.set_debug(debug)
    if dev:
        from raggie_dirs import enable_dev_mode
        enable_dev_mode()
    agent = RaggieACPAgent(role, debug=debug)

    async def serve():
        # stdio_streams() binds sys.stdout at call time, so capture the
        # protocol streams BEFORE redirecting stdout to stderr.
        output_stream, input_stream = await stdio_streams()
        sys.stdout = sys.stderr
        conn = AgentSideConnection(agent, input_stream, output_stream, listening=False)
        try:
            await conn.listen()
        finally:
            await asyncio.shield(conn.close())

    asyncio.run(serve())


def run_http(role, port=8765, debug=False, auto_approve=False, host="127.0.0.1", dev=False):
    from acp_server.http_transport import serve_http

    io_backend.set_mode(io_backend.MODE_ACP, auto_approve=auto_approve)
    io_backend.set_debug(debug)
    if dev:
        from raggie_dirs import enable_dev_mode
        enable_dev_mode()
    _ensure_chat_db()
    agent = RaggieACPAgent(role, debug=debug)
    serve_http(agent, host=host, port=port, auto_approve=auto_approve)


def _ensure_chat_db():
    """Create the raggie data dir and chat DB before serving.

    Pre-session endpoints (chats/list, chats/search, todo queries) open the
    chat database directly. On a fresh project the .raggie data dir does not
    exist yet, so sqlite raises "unable to open database file" before any
    session is created. init_db() creates the dir and runs pending migrations.
    """
    from Agent.chat_history_db import init_db
    init_db()


def run_web(role, port=8765, debug=False, auto_approve=False, host="127.0.0.1", dev=False):
    """Run the ACP agent over HTTP and serve the built web UI from it."""
    from acp_server.http_transport import default_web_dist, serve_http

    io_backend.set_mode(io_backend.MODE_ACP, auto_approve=auto_approve)
    io_backend.set_debug(debug)
    if dev:
        from raggie_dirs import enable_dev_mode
        enable_dev_mode()
    _ensure_chat_db()
    web_dist = default_web_dist()
    if web_dist is None:
        print(
            "[raggie-web] no built web UI found (neither the bundled "
            "acp_server/webui copy nor web-ui/dist). In a source checkout run "
            "`pnpm install && pnpm build` in web-ui/ (the JSON-RPC API still "
            "works); in a pip install, reinstall a wheel built with "
            "`python sync_webui.py` first."
        )
    agent = RaggieACPAgent(role, debug=debug)

    # Short session id embedded in the web ui link. Requests that carry a
    # DIFFERENT sid are rejected (stale tab pointing at another instance);
    # requests without a sid (vs code extension, plain API clients) pass.
    sid = uuid.uuid4().hex[:8]

    # Announce the URL only after the server actually bound: when the
    # requested port is taken, serve_http falls back to the next free one.
    def announce(bound_port):
        print(f"\nraggie web ui: http://{host}:{bound_port}/?sid={sid}")

    serve_http(agent, host=host, port=port, auto_approve=auto_approve,
               web_dist=web_dist, on_bound=announce, sid=sid)
