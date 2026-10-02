"""ACP over HTTP transport with web UI support.

JSON-RPC 2.0 messages are POSTed to ``/``. Regular requests get a single
JSON-RPC response; ``session/prompt`` responds with a Server-Sent Events
stream: one ``data:`` frame per ``session/update`` notification, followed by
a final frame carrying the JSON-RPC response.

When a web UI is served (``web_dist``), the transport also serves the built
frontend as static files and supports interactive mid-turn flows: permission
requests and free-form agent questions are pushed to the browser as SSE
frames and answered via ``session/respond_permission`` /
``session/respond_ask``. ``chats/list`` / ``chats/open`` / ``chats/history``
are web-only extensions on top of ACP for chat management.
"""

import asyncio
import errno
import json
import os
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from typing import Optional

from acp import schema
from acp.exceptions import RequestError
from pydantic import BaseModel, ConfigDict, Field

_REQUESTS = {
    "initialize": (schema.InitializeRequest, "initialize"),
    "authenticate": (schema.AuthenticateRequest, "authenticate"),
    "session/new": (schema.NewSessionRequest, "new_session"),
    "session/prompt": (schema.PromptRequest, "prompt"),
    # Web UI extensions (not part of the ACP protocol).
    "chats/list": (None, "list_chats"),
    "chats/open": (None, "open_session"),
    "chats/delete": (None, "delete_chat"),
    "chats/history": (None, "chat_history"),
    "chats/search": (None, "search_messages"),
    "health/stats": (None, "health_stats"),
    "health/report": (None, "health_report"),
    "commands/list": (None, "commands_list"),
    "todo/active": (None, "active_todo"),
    "setup/status": (None, "setup_status"),
    "setup/add_key": (None, "setup_add_key"),
    "setup/remove_key": (None, "setup_remove_key"),
    "setup/update_role": (None, "setup_update_role"),
    "setup/update_active_role": (None, "update_active_role"),
    "setup/update_key": (None, "setup_update_key"),
    "mcp/list": (None, "mcp_list"),
    "mcp/add": (None, "mcp_add"),
    "mcp/remove": (None, "mcp_remove"),
    "mcp/test": (None, "mcp_test"),
    "session/dangling": (None, "has_dangling"),
}

_NOTIFICATIONS = {
    "session/cancel": (schema.CancelNotification, "cancel"),
}

# Responds are handled inline (they resolve a pending hub request, they are
# not agent calls).
_RESPOND_METHODS = ("session/respond_permission", "session/respond_ask")

# Pushed into the open SSE stream by session/cancel so the stream handler can
# end the client turn immediately, while the prompt future keeps running in
# the executor until the worker thread stops at its next cancel_event
# boundary.
CANCEL_SENTINEL = object()

# SSE keepalive comment interval; long silent stretches (uninterruptible tool
# runs, subagents) must not let idle proxies reap the connection.
_KEEPALIVE_INTERVAL = 15.0

_MIME_TYPES = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".ttf": "font/ttf",
    ".json": "application/json",
    ".map": "application/json",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".woff2": "font/woff2",
}


class _OpenSessionParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True, coerce_numbers_to_str=True)
    chat_id: str = Field(alias="chatId")
    cwd: str = "."


class _ChatDeleteParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True, coerce_numbers_to_str=True)
    chat_id: str = Field(alias="chatId")


class _ChatHistoryParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True, coerce_numbers_to_str=True)
    session_id: str = Field(alias="sessionId")
    before_id: Optional[int] = Field(default=None, alias="beforeId")
    limit: Optional[int] = None


class _ChatSearchParams(BaseModel):
    query: str
    limit: Optional[int] = None


class _SetupKeyParams(BaseModel):
    provider: str
    base_url: str = Field(alias="baseUrl")
    api_key: str = Field(alias="apiKey")


class _SetupRemoveKeyParams(BaseModel):
    key_id: str = Field(alias="keyId")


class _SetupUpdateKeyParams(BaseModel):
    key_id: str = Field(alias="keyId")
    api_key: str = Field(alias="apiKey")


class _SetupRoleParams(BaseModel):
    role: str
    model: Optional[str] = None
    base_url: Optional[str] = Field(default=None, alias="baseUrl")
    provider: Optional[str] = None
    context_window: Optional[int] = Field(default=None, alias="contextWindow")
    reasoning_effort: Optional[str] = Field(default=None, alias="reasoningEffort")
    user_agent: Optional[str] = Field(default=None, alias="userAgent")


class _SetupActiveRoleParams(BaseModel):
    model: Optional[str] = None
    reasoning_effort: Optional[str] = Field(default=None, alias="reasoningEffort")


class _McpAddParams(BaseModel):
    name: str
    command: Optional[str] = None
    args: Optional[list[str]] = None
    env: Optional[dict[str, str]] = None
    url: Optional[str] = None
    trust: bool = False


class _McpNameParams(BaseModel):
    name: str


def _model_kwargs(model, params):
    """Validate JSON-RPC params into a model and return snake_case kwargs,
    mirroring how the ACP SDK invokes agent methods."""
    obj = model.model_validate(params or {})
    kwargs = {k: getattr(obj, k) for k in model.model_fields if k != "field_meta"}
    meta = getattr(obj, "field_meta", None)
    if meta:
        kwargs.update(meta)
    return kwargs


def _dump(model):
    return model.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_unset=True)


def default_web_dist():
    """Locate the built web UI.

    Checks, in order:
    1. The copy bundled inside the installed package (``acp_server/webui``),
       populated by ``sync_webui.py`` before ``python -m build`` so pip
       installs ship the UI.
    2. A development checkout's ``web-ui/dist`` (built by ``pnpm build``).

    Returns None when no build exists.
    """
    bundled = Path(__file__).resolve().parent / "webui"
    if (bundled / "index.html").is_file():
        return bundled
    dev = Path(__file__).resolve().parents[2] / "web-ui" / "dist"
    if (dev / "index.html").is_file():
        return dev
    return None


class _HttpClientHub:
    """Client shim for HTTP mode.

    ``session_update`` routes pydantic ACP updates into the SSE queue of the
    in-flight prompt for that session. ``session_status`` and the
    ``request_permission`` / ``request_ask`` methods push plain dict frames
    that the SSE handler forwards verbatim. Interactive requests block on an
    asyncio.Event until the browser answers via ``session/respond_*`` or the
    pending is cancelled.
    """

    def __init__(self, auto_approve=False):
        self.streams = {}
        self.pendings = {}
        # In-flight turn futures per session (set by _handle_stream), so a
        # follow-up prompt/resume can wait for a still-winding-down turn
        # instead of racing it.
        self.turns = {}
        self.auto_approve = auto_approve

    def _put(self, session_id, frame):
        stream = self.streams.get(session_id)
        if stream is not None:
            stream.put(frame)

    async def session_update(self, session_id, update, **kwargs):
        self._put(session_id, update)

    async def session_status(self, session_id, status, **kwargs):
        self._put(session_id, {
            "method": "session/status",
            "params": {"sessionId": session_id, "status": status},
        })

    async def health_stats(self, session_id, stats, **kwargs):
        self._put(session_id, {
            "method": "session/health_stats",
            "params": {"sessionId": session_id, "stats": stats},
        })

    async def session_notice(self, session_id, text, **kwargs):
        self._put(session_id, {
            "method": "session/notice",
            "params": {"sessionId": session_id, "text": text},
        })

    async def session_handover(self, session_id, text, **kwargs):
        """Deliver the agent-written handover document to the browser the
        moment a context-window handover happens."""
        self._put(session_id, {
            "method": "session/handover",
            "params": {"sessionId": session_id, "text": text},
        })

    async def subagent_event(self, session_id, payload, **kwargs):
        """Stream live subagent work (dispatch bridge) to the browser."""
        self._put(session_id, {
            "method": "session/subagent_update",
            "params": {"sessionId": session_id, **payload},
        })

    async def _request(self, session_id, method, params, outcome_key):
        # Nobody can answer when there is no live SSE stream for the session
        # (browser tab reloaded or closed): fail fast instead of blocking the
        # agent worker forever on a frame no client will ever see.
        if self.streams.get(session_id) is None:
            return None
        request_id = uuid.uuid4().hex
        pending = {
            "event": asyncio.Event(),
            "outcome": None,
            "kind": outcome_key,
            "session_id": session_id,
        }
        self.pendings[request_id] = pending
        self._put(session_id, {
            "method": method,
            "params": {"sessionId": session_id, "requestId": request_id, **params},
        })
        try:
            await pending["event"].wait()
        finally:
            self.pendings.pop(request_id, None)
        return pending["outcome"]

    async def request_permission(self, session_id, tool_call, options, detail="", **kwargs):
        if self.auto_approve:
            return schema.RequestPermissionResponse(
                outcome=schema.AllowedOutcome(option_id="allow", outcome="selected")
            )
        outcome = await self._request(
            session_id,
            "session/request_permission",
            {
                "toolCall": _dump(tool_call),
                "options": [_dump(o) for o in options],
                "detail": detail,
            },
            "permission",
        )
        if outcome == "allow":
            return schema.RequestPermissionResponse(
                outcome=schema.AllowedOutcome(option_id="allow", outcome="selected")
            )
        if outcome in ("always", "allow_always"):
            # The browser echoes back the option_id ("allow_always"); accept
            # the shorthand "always" too for robustness.
            return schema.RequestPermissionResponse(
                outcome=schema.AllowedOutcome(option_id="allow_always", outcome="selected")
            )
        return schema.RequestPermissionResponse(
            outcome=schema.DeniedOutcome(outcome="cancelled")
        )

    async def request_ask(self, session_id, question, options=None, allow_multiple=False, **kwargs):
        if self.auto_approve and self.streams.get(session_id) is None:
            return ""
        outcome = await self._request(
            session_id, "session/request_ask",
            {
                "question": question,
                "options": list(options or []),
                "allowMultiple": bool(allow_multiple),
            },
            "ask",
        )
        return outcome if isinstance(outcome, str) else ""

    async def cancel_pendings(self, session_id, outcome="cancelled"):
        for pending in self.pendings.values():
            if pending["session_id"] != session_id:
                continue
            if pending["outcome"] is None:
                pending["outcome"] = outcome
            pending["event"].set()

    async def resolve(self, request_id, outcome):
        """Answer a pending interactive request (called on the server loop)."""
        pending = self.pendings.get(request_id)
        if pending is not None and pending["outcome"] is None:
            pending["outcome"] = outcome
            pending["event"].set()


class _AcpHttpServer:
    def __init__(self, agent, auto_approve=False, web_dist=None, sid=None):
        self.agent = agent
        self.hub = _HttpClientHub(auto_approve=auto_approve)
        self.web_dist = Path(web_dist).resolve() if web_dist else None
        # Session id of the web ui link this server was launched with
        # (run_web). None for run_http / tests: no sid validation at all.
        self.sid = sid
        # Actually bound port, set by serve_http after a successful bind.
        self.bound_port = None
        self.agent.on_connect(self.hub)
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self.loop.run_forever, daemon=True)

    def start(self):
        self.loop_thread.start()

    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)


def _make_handler(server):
    agent = server.agent

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            pass

        # -- static files ------------------------------------------------

        def do_GET(self):
            if urlparse(self.path).path == "/identity":
                # Lets clients (e.g. the vs code extension) verify this
                # server belongs to their project: raggie chdirs to the
                # project dir before starting, so cwd identifies it.
                body = json.dumps({
                    "service": "raggie-acp",
                    "pid": os.getpid(),
                    "cwd": os.path.realpath(os.getcwd()),
                    "port": server.bound_port,
                }).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionError, OSError):
                    pass
                return
            if server.web_dist is None:
                self._respond_plain(404, "Not found")
                return
            dist = server.web_dist
            if not (dist / "index.html").is_file():
                self._respond_plain(
                    503,
                    "raggie web ui is not built yet.\n"
                    "Run: pnpm install && pnpm build  (inside web-ui/)",
                )
                return

            path = unquote(urlparse(self.path).path)
            if path in ("/", ""):
                file_path = dist / "index.html"
            else:
                file_path = (dist / path.lstrip("/")).resolve()
                if not file_path.is_relative_to(dist):
                    self._respond_plain(403, "Forbidden")
                    return
            if not file_path.is_file():
                self._respond_plain(404, "Not found")
                return
            mime = _MIME_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
            try:
                body = file_path.read_bytes()
            except OSError:
                self._respond_plain(404, "Not found")
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", mime)
                # index.html references hashed asset names; without this header a
                # browser can keep serving a stale bundle after a rebuild.
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionError, OSError):
                # Download aborted (e.g. navigation); nothing to deliver.
                pass

        def _respond_plain(self, code, text):
            body = text.encode()
            try:
                self.send_response(code)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionError, OSError):
                pass

        # -- JSON-RPC ----------------------------------------------------

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                message = json.loads(self.rfile.read(length))
            except (ValueError, TypeError):
                self._send_json(None, error={"code": -32700, "message": "Parse error"})
                return

            method = message.get("method")
            params = message.get("params") or {}
            msg_id = message.get("id")

            # Reject requests stamped with a sid that does not match this
            # instance (stale browser tab pointing at the wrong server).
            # A request without a sid is always allowed: the vs code
            # extension and plain API clients never send one. Runs before
            # every dispatch so a stale tab can neither prompt nor cancel.
            if server.sid is not None:
                req_sid = params.get("sid")
                if req_sid and req_sid != server.sid:
                    if msg_id is not None:
                        self._send_json(msg_id, error={"code": -32001, "message": "This tab belongs to a different raggie agent instance. Reopen the web ui link."})
                    else:
                        self._send_202()
                    return

            # Browser clients don't send MCP config; the agent wires its own.
            if method == "session/new" and "mcpServers" not in params:
                params["mcpServers"] = []

            if method == "session/prompt" and msg_id is not None:
                self._handle_stream(msg_id, params, method)
                return

            if method == "session/resume" and msg_id is not None:
                # Same SSE streaming contract as a prompt, but resumes the
                # interrupted turn instead of starting a new one.
                self._handle_stream(msg_id, params, method)
                return

            if method in _RESPOND_METHODS and msg_id is None:
                self._handle_respond(method, params)
                return

            if method in _REQUESTS and msg_id is not None:
                model, attr = _REQUESTS[method]
                self._handle_request(msg_id, method, model, attr, params)
                return

            if method in _NOTIFICATIONS and msg_id is None:
                model, attr = _NOTIFICATIONS[method]
                try:
                    kwargs = _model_kwargs(model, params)
                except Exception:
                    self._send_202()
                    return
                if method == "session/cancel":
                    session_id = params.get("sessionId")
                    server.submit(server.hub.cancel_pendings(session_id))
                    server.submit(getattr(agent, attr)(**kwargs))
                    # Best effort: unblock the SSE handler waiting on the
                    # stream so the client turn ends immediately. The prompt
                    # future is still running in the executor; it resolves on
                    # its own when the worker thread exits at the next
                    # cancel_event boundary.
                    try:
                        stream = server.hub.streams.get(session_id)
                        if stream is not None:
                            stream.put(CANCEL_SENTINEL)
                    except Exception:
                        pass
                else:
                    server.submit(getattr(agent, attr)(**kwargs))
                self._send_202()
                return

            if msg_id is not None:
                self._send_json(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})
            else:
                self._send_202()

        def _handle_respond(self, method, params):
            request_id = params.get("requestId")
            if request_id:
                pending = server.hub.pendings.get(request_id)
                if pending is not None:
                    if pending["kind"] == "ask":
                        outcome = str(params.get("answer") or "")
                    else:
                        outcome = str(params.get("outcome") or "cancelled")
                    # asyncio.Event must only be touched on the server loop.
                    server.submit(server.hub.resolve(request_id, outcome))
            self._send_202()

        def _handle_request(self, msg_id, method, model, attr, params):
            try:
                if method == "chats/open":
                    kwargs = _model_kwargs(_OpenSessionParams, params)
                elif method == "chats/delete":
                    kwargs = _model_kwargs(_ChatDeleteParams, params)
                elif method == "setup/add_key":
                    kwargs = _model_kwargs(_SetupKeyParams, params)
                elif method == "chats/search":
                    kwargs = _model_kwargs(_ChatSearchParams, params)
                elif method == "setup/remove_key":
                    kwargs = _model_kwargs(_SetupRemoveKeyParams, params)
                elif method == "setup/update_role":
                    kwargs = _model_kwargs(_SetupRoleParams, params)
                elif method == "setup/update_active_role":
                    kwargs = _model_kwargs(_SetupActiveRoleParams, params)
                elif method == "setup/update_key":
                    kwargs = _model_kwargs(_SetupUpdateKeyParams, params)
                elif method == "mcp/add":
                    kwargs = _model_kwargs(_McpAddParams, params)
                elif method in ("mcp/remove", "mcp/test"):
                    kwargs = _model_kwargs(_McpNameParams, params)
                elif method in ("chats/history", "health/stats", "health/report", "todo/active",
                                "session/dangling"):
                    kwargs = _model_kwargs(_ChatHistoryParams, params)
                elif model is not None:
                    kwargs = _model_kwargs(model, params)
                else:
                    kwargs = {}
                result = server.submit(getattr(agent, attr)(**kwargs)).result()
                payload = _dump(result) if isinstance(result, BaseModel) else result
                self._send_json(msg_id, result=payload)
            except RequestError as err:
                self._send_json(msg_id, error=err.to_error_obj())
            except Exception as err:
                self._send_json(msg_id, error={"code": -32603, "message": str(err)})

        def _handle_stream(self, msg_id, params, method):
            """Stream an agent turn (prompt or resume) over SSE."""
            session_id = params.get("sessionId")
            stream = queue.Queue()
            server.hub.streams[session_id] = stream
            try:
                try:
                    if method == "session/resume":
                        # Capture the previous turn's future BEFORE submit:
                        # after submit the hub entry is this turn's own
                        # future, and awaiting it would self-deadlock into a
                        # permanent SSE keepalive hang.
                        previous = server.hub.turns.get(session_id)
                        # Resume carries no prompt content; only the session id.
                        future = server.submit(agent.resume(
                            session_id=params.get("sessionId"), _previous_turn=previous))
                    else:
                        kwargs = _model_kwargs(schema.PromptRequest, params)
                        previous = server.hub.turns.get(session_id)
                        future = server.submit(
                            agent.prompt(_previous_turn=previous, **kwargs))
                except Exception as err:
                    self._send_json(msg_id, error={"code": -32603, "message": str(err)})
                    return
                server.hub.turns[session_id] = future

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()

                last_write = time.monotonic()
                client_gone = False
                cancelled_early = False
                while not future.done():
                    try:
                        frame = stream.get(timeout=0.1)
                    except queue.Empty:
                        # Idle polling: keep the connection alive so proxies
                        # do not reap it during long silent stretches.
                        if time.monotonic() - last_write >= _KEEPALIVE_INTERVAL:
                            try:
                                self.wfile.write(b": keepalive\n\n")
                                self.wfile.flush()
                            except OSError:
                                client_gone = True
                                break
                            last_write = time.monotonic()
                        continue
                    if frame is CANCEL_SENTINEL:
                        # session/cancel arrived: end the client turn now.
                        # The prompt future is still running in the executor
                        # and resolves on its own; the interrupted step
                        # becomes dangling work recovered by the resume flow.
                        cancelled_early = True
                        break
                    if not self._send_frame(session_id, frame):
                        client_gone = True
                        break
                    last_write = time.monotonic()

                if not client_gone and not cancelled_early:
                    # The prompt future only completes after every update has
                    # been queued, so drain what remains before sending the
                    # result.
                    while not stream.empty():
                        frame = stream.get()
                        if frame is CANCEL_SENTINEL:
                            cancelled_early = True
                            break
                        if not self._send_frame(session_id, frame):
                            client_gone = True
                            break
                        last_write = time.monotonic()

                    if not client_gone:
                        self._send_result(msg_id, future)

                if not client_gone and cancelled_early:
                    self._send_sse({"jsonrpc": "2.0", "id": msg_id,
                                    "result": _dump(schema.PromptResponse(stop_reason="cancelled"))})
                if client_gone:
                    # Browser disconnected mid-turn: stop the worker at the
                    # next boundary and resolve any pending permission/ask
                    # request so it never waits for a client that is gone.
                    self._abort_turn(session_id)
            finally:
                # Only pop when we still own the stream entry: a second tab
                # opening the same session replaces the queue, and this
                # handler's exit must not steal the newer connection's live
                # stream (its turn would then stream into a dead queue).
                if server.hub.streams.get(session_id) is stream:
                    server.hub.streams.pop(session_id, None)
                # NOTE: hub.turns is intentionally NOT popped here. On an
                # early cancel the stream ends while the turn future is
                # still winding down in the background - a follow-up
                # prompt/resume must still be able to await it. Done
                # futures are harmless to _await_quiet_turn, and the next
                # turn overwrites the entry.

        def _abort_turn(self, session_id):
            """Browser disconnected mid-turn: cancel the turn so the worker
            thread stops at the next boundary, and resolve any pending
            permission/ask requests so it never waits for a client that is
            gone."""
            session = agent.sessions.get(session_id)
            if session is not None:
                session.cancel_event.set()
            server.submit(server.hub.cancel_pendings(session_id))

        def _send_frame(self, session_id, frame):
            """Send one SSE frame. Returns False when the client disconnected."""
            if isinstance(frame, dict):
                payload = frame
            else:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {"sessionId": session_id, "update": _dump(frame)},
                }
            try:
                self._send_sse(payload)
                return True
            except (ConnectionError, BrokenPipeError):
                # Browser tab closed: cancel the turn so the worker thread
                # does not hang waiting for a client that is gone.
                session = agent.sessions.get(session_id)
                if session is not None:
                    session.cancel_event.set()
                server.submit(server.hub.cancel_pendings(session_id))
                return False

        def _send_result(self, msg_id, future):
            def safe_sse(payload):
                # A gone client (tab closed / page reload mid-request) makes
                # every write raise; that is normal, not an error worth a
                # traceback. _send_frame keeps its own handling because it
                # uses the failure to cancel the turn.
                try:
                    self._send_sse(payload)
                except (BrokenPipeError, ConnectionError, OSError):
                    pass
            try:
                result = future.result()
                safe_sse({"jsonrpc": "2.0", "id": msg_id, "result": _dump(result)})
            except RequestError as err:
                safe_sse({"jsonrpc": "2.0", "id": msg_id, "error": err.to_error_obj()})
            except Exception as err:
                safe_sse({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(err)}})

        def _send_json(self, msg_id, result=None, error=None):
            payload = {"jsonrpc": "2.0", "id": msg_id}
            if error is not None:
                payload["error"] = error
            else:
                payload["result"] = result
            body = json.dumps(payload).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionError, OSError):
                # Client disconnected before the response arrived.
                pass

        def _send_202(self):
            """Reply 202 (accepted notification), tolerating a gone client."""
            try:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
            except (BrokenPipeError, ConnectionError, OSError):
                pass

        def _send_sse(self, payload):
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
            self.wfile.flush()

    return Handler


def serve_http(agent, host="127.0.0.1", port=8765, auto_approve=False, web_dist=None,
               on_bound=None, sid=None):
    """Serve the ACP-over-HTTP transport, binding ``host:port``.

    If the address is already in use, the next port is tried (and so on)
    until a free one is found. ``on_bound(port)`` is called with the port
    actually bound, before serve_forever blocks. When ``sid`` is set,
    JSON-RPC requests carrying a different ``sid`` are rejected.
    """
    server = _AcpHttpServer(agent, auto_approve=auto_approve, web_dist=web_dist, sid=sid)
    server.start()
    while True:
        try:
            httpd = ThreadingHTTPServer((host, port), _make_handler(server))
            break
        except OSError as err:
            if err.errno != errno.EADDRINUSE:
                raise
            print(f"[raggie-acp] port {port} on {host} is already in use, trying {port + 1}")
            port += 1
    if on_bound is not None:
        server.bound_port = port
        on_bound(port)
    print(f"\n[raggie-acp] server started (auto-approve: {auto_approve})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        server.loop.call_soon_threadsafe(server.loop.stop)
