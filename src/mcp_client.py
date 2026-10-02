"""MCP client integration: lets the Raggie agent call external MCP servers.

Supports both protocol eras   legacy 2025-era stateful servers and the
stateless 2026-07-28 revision ("MCP 2.0")   over both transports (stdio
subprocess and Streamable HTTP). The official mcp v2 SDK negotiates the
protocol version automatically per server.

Servers are configured in ~/.config/raggie/mcp_servers.json:

    {
      "local-files": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "env": {"EXTRA": "..."},
        "trust": false
      },
      "remote-api": {
        "url": "https://example.com/mcp",
        "trust": true
      }
    }

Tools are exposed to the model as ``mcp__<server>__<tool>``. Calls to
servers without ``"trust": true`` require user confirmation (routed through
io_backend, so in ACP mode the editor's permission UI is used).

The mcp SDK is imported lazily so users without configured servers pay no
import cost.
"""

import asyncio
import contextlib
import json
import re
import sys
import threading

import io_backend

MAX_RESULT_CHARS = 30000
MAX_NAME_LEN = 64

_manager = None


class McpManager:
    """Owns a background asyncio loop and all MCP server connections."""

    def __init__(self):
        self._loop = None
        self._thread = None
        self._stack = None
        self._clients = {}    # server name -> mcp Client
        self._tool_map = {}   # exposed name -> (server name, remote tool name, trust)
        self._schemas = []    # OpenAI function schemas for the API

    # -- lifecycle -------------------------------------------------------

    def _ensure_loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._loop.run_forever, daemon=True, name="raggie-mcp"
            )
            self._thread.start()

    def connect(self, servers):
        """Connect to all configured servers and discover their tools.

        Returns the number of servers successfully connected.
        """
        if not servers:
            return 0
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(self._connect_all(servers), self._loop)
        return future.result()

    async def _connect_all(self, servers):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters, stdio_client

        self._stack = contextlib.AsyncExitStack()
        connected = 0
        for name, cfg in servers.items():
            try:
                if "url" in cfg:
                    client = Client(cfg["url"])
                elif "command" in cfg:
                    params = StdioServerParameters(
                        command=cfg["command"],
                        args=cfg.get("args", []),
                        env=cfg.get("env"),
                    )
                    client = Client(stdio_client(params))
                else:
                    print(
                        f"[mcp] server '{name}' has neither 'url' nor 'command', skipping",
                        file=sys.stderr,
                    )
                    continue

                client = await self._stack.enter_async_context(client)
                result = await client.list_tools()
                trust = bool(cfg.get("trust", False))
                for tool in result.tools:
                    self._register_tool(name, tool, trust)
                self._clients[name] = client
                connected += 1
                print(
                    f"[mcp] connected to '{name}' "
                    f"(protocol {client.protocol_version}, {len(result.tools)} tools)",
                    file=sys.stderr,
                )
            except Exception as err:
                print(f"[mcp] failed to connect to '{name}': {err}", file=sys.stderr)
        return connected

    def shutdown(self):
        if self._loop is None:
            return
        try:
            if self._stack is not None:
                future = asyncio.run_coroutine_threadsafe(self._stack.aclose(), self._loop)
                future.result(timeout=10)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop = None

    # -- tool registration -------------------------------------------------

    def _register_tool(self, server_name, tool, trust):
        exposed = _exposed_name(server_name, tool.name)
        if exposed in self._tool_map:
            print(f"[mcp] tool name collision for '{exposed}', skipping", file=sys.stderr)
            return
        self._tool_map[exposed] = (server_name, tool.name, trust)
        description = tool.description or ""
        self._schemas.append({
            "type": "function",
            "function": {
                "name": exposed,
                "description": f"[MCP server: {server_name}] {description}",
                "parameters": tool.input_schema or {"type": "object", "properties": {}},
            },
        })

    def register_into(self, registry):
        """Register call handlers for all discovered MCP tools."""
        for exposed, (server_name, remote_name, trust) in self._tool_map.items():
            registry.set_handler(exposed, self._make_handler(exposed, server_name, remote_name, trust))

    def api_schemas(self):
        """OpenAI-format tool schemas for all discovered MCP tools."""
        return list(self._schemas)

    @property
    def tool_names(self):
        return list(self._tool_map)

    # -- calling -------------------------------------------------------------

    def _make_handler(self, exposed, server_name, remote_name, trust):
        def handler(arguments, toolcall_id):
            if not trust:
                detail = json.dumps(arguments)[:500]
                if not io_backend.confirm(
                    f"Allow MCP tool '{remote_name}' on server '{server_name}'?", detail
                ):
                    reason = io_backend.ask("Reason for refusal (optional, press Enter to skip): ").strip()
                    msg = "The user refused running this MCP tool."
                    if reason:
                        msg += f" Reason: {reason}"
                    return {"role": "tool", "tool_call_id": toolcall_id, "content": msg}
            try:
                content = self.call(exposed, arguments)
            except Exception as err:
                content = f"Error calling MCP tool '{remote_name}' on server '{server_name}': {err}"
            return {"role": "tool", "tool_call_id": toolcall_id, "content": content}

        return handler

    def call(self, exposed, arguments):
        """Synchronously call an exposed MCP tool; returns text content."""
        server_name, remote_name, _ = self._tool_map[exposed]
        future = asyncio.run_coroutine_threadsafe(
            self._clients[server_name].call_tool(remote_name, arguments), self._loop
        )
        result = future.result()
        text = _result_text(result)
        if result.is_error:
            text = f"MCP tool error: {text}"
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "\n... [truncated]"
        return text


def _exposed_name(server_name, tool_name):
    raw = f"mcp__{server_name}__{tool_name}"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", raw)[:MAX_NAME_LEN]


def _result_text(result):
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        parts.append(text if text is not None else str(block))
    return "\n".join(parts)


# -- module-level API ---------------------------------------------------------


def setup(registry, servers=None):
    """Load configured MCP servers, connect, and register their tools.

    Returns the number of servers connected (0 when none are configured).
    """
    global _manager
    if servers is None:
        from Agent.config import load_mcp_servers
        servers = load_mcp_servers()
    if not servers:
        return 0
    if _manager is None:
        _manager = McpManager()
    connected = _manager.connect(servers)
    _manager.register_into(registry)
    return connected


def get_api_schemas():
    """OpenAI-format schemas for all connected MCP tools (empty if none)."""
    return _manager.api_schemas() if _manager is not None else []


def shutdown():
    global _manager
    if _manager is not None:
        _manager.shutdown()
        _manager = None
