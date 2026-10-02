"""ACP (Agent Client Protocol) adapter on top of the Raggie agent.

Maps Raggie's generator-based event stream ("response_chunk", "tool_call",
"tool_result", ...) onto ACP ``session/update`` notifications, and bridges
tool confirmations to ACP ``session/request_permission``.

Both transports (stdio and HTTP) share this class; the transport supplies the
client connection via ``on_connect``.
"""

import asyncio
import json
import os
import sys
import threading
from importlib.metadata import version as pkg_version

import acp
from acp import schema
from acp.helpers import (
    start_tool_call,
    text_block,
    tool_content,
    update_agent_message_text,
    update_agent_thought_text,
    update_tool_call,
)

import io_backend

MAX_TOOL_OUTPUT_CHARS = 4000

# Tools whose output is intentionally large (full source, file semantics,
# call trees, edit diffs). Truncating them for display defeats the purpose of
# the tool, so their full payload is forwarded to the UI untouched.
UNTRUNCATED_TOOLS = frozenset({
    "GetSymbolSourceCode",
    "GetFileCodeSemantics",
    "WalkCallTree",
    "ReplaceText",
})


def _truncate_tool_output(tool_name, output):
    """Clamp a tool result for display, unless the tool opted out.

    GetSymbolSourceCode, GetFileCodeSemantics, WalkCallTree and ReplaceText
    are exempt so the UI can show their complete output.
    """
    if tool_name in UNTRUNCATED_TOOLS:
        return output
    if len(output) > MAX_TOOL_OUTPUT_CHARS:
        return output[:MAX_TOOL_OUTPUT_CHARS] + "\n... [truncated]"
    return output


def _format_tool_input(arguments):
    """Pretty JSON of a tool call's parameters for the expandable details."""
    try:
        parsed = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
    except (json.JSONDecodeError, TypeError):
        parsed = arguments
    if isinstance(parsed, dict):
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    return None if not parsed else str(parsed)


def _history_tool_title(name, arguments):
    """One-line tool call summary including its parameters.

    Mirrors the terminal's [tool] display: name followed by every parameter,
    each value truncated so the summary stays readable.
    """
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
    except (json.JSONDecodeError, TypeError):
        args = {}
    if not isinstance(args, dict):
        args = {}
    parts = []
    for k, v in args.items():
        text = str(v)
        if "\n" in text:
            text = text.replace("\r", "").replace("\n", " ")
        if len(text) > 180:
            text = text[:177] + "..."
        parts.append(f"{k}: {text}")
    summary = f"{name}   {' '.join(parts)}".rstrip()
    if len(summary) > 300:
        summary = summary[:297] + "..."
    return summary


def _history_subagent_block(session_id, messages, nested_blocks):
    """Rebuild one stored subagent run as a web-UI subagent entry.

    Uses the child session's preloaded persisted messages (same shapes as
    the live dispatch bridge emitted, cached by the caller during BFS
    discovery) so the nested streaming view is reproduced in chat history:
    prompt, tool calls with outputs, response text, and nested subagent
    blocks embedded in `children`.

    Nested DispatchSubagent calls embed the child session's already-built
    block (kind "subagent") directly in `children`: the child session is
    resolved via get_child_session_by_toolcall and must have a built block
    in nested_blocks (built deepest-first by the caller, no recursion).
    A nested dispatch whose block could not be built is skipped   never
    rendered as a tool row   so a broken child session cannot break its
    parent's block.

    Returns the block dict or None on any failure so a broken child
    session can never break history loading.
    """
    from Agent.chat_history_db import (
        get_child_session_by_toolcall,
        get_session_depth,
        get_session_role,
    )

    if messages is None:
        return None
    try:
        depth = get_session_depth(session_id)
        role = get_session_role(session_id)
    except Exception as err:
        print(f"[raggie-acp] subagent history build failed: {err}", file=sys.stderr)
        return None

    prompt = None
    text_parts = []
    children = []
    child_seq = 0
    pending_outputs = {}
    pending_tool_names = {}
    errored = False

    for msg in messages:
        msg_role = msg.get("role")
        content = msg.get("content")
        tool_call_id = msg.get("tool_call_id")

        if tool_call_id and msg_role in ("tool", "user"):
            entry = pending_outputs.get(str(tool_call_id))
            if entry is not None:
                if isinstance(content, list):
                    content = "\n".join(
                        str(b.get("text", "")) for b in content if isinstance(b, dict)
                    )
                output = content if isinstance(content, str) else str(content or "")
                output = _truncate_tool_output(
                    pending_tool_names.get(str(tool_call_id)), output
                )
                entry["output"] = output
                if output.lstrip().startswith("Error:"):
                    entry["status"] = "failed"
                    errored = True
            continue

        if msg_role == "user" and prompt is None:
            prompt = content if isinstance(content, str) else str(content or "")
        elif msg_role == "assistant":
            # Persisted reasoning (save_message stores reasoning_content on
            # every assistant message that carries it) renders as a thought
            # child ahead of the message's own tool calls.
            reasoning = str(msg.get("reasoning_content") or "")
            if reasoning:
                child_seq += 1
                children.append({
                    "id": f"{session_id}-thought-{child_seq}",
                    "kind": "thought",
                    "text": reasoning,
                })
            if isinstance(content, str) and content.strip():
                text_parts.append(content)
            for idx, tc in enumerate(msg.get("tool_calls") or []):
                func = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                name = func.get("name") or "unknown tool"
                child_seq += 1
                fallback_id = f"{session_id}-tool-{child_seq}"
                real_id = str(tc.get("id") or fallback_id)
                if name == "DispatchSubagent":
                    # Embed the child session's already-built nested block
                    # (kind "subagent"); a failed/unresolvable child is
                    # skipped, never rendered as a tool row.
                    try:
                        nested_child = get_child_session_by_toolcall(session_id, real_id)
                    except Exception as err:
                        print(
                            f"[raggie-acp] subagent history lookup failed: {err}",
                            file=sys.stderr,
                        )
                        nested_child = None
                    nested_block = (
                        nested_blocks.get(nested_child["id"])
                        if nested_child is not None else None
                    )
                    if nested_block is not None:
                        children.append(nested_block)
                    continue
                children.append({
                    "id": fallback_id,
                    "kind": "tool",
                    "toolCallId": real_id,
                    "title": _history_tool_title(name, func.get("arguments")),
                    "status": "completed",
                    "input": _format_tool_input(func.get("arguments")),
                })
                pending_outputs[real_id] = children[-1]
                pending_tool_names[real_id] = name

    return {
        "id": f"sub-{session_id}",
        "kind": "subagent",
        "subagentSessionId": str(session_id),
        "depth": depth,
        "role": role,
        "prompt": prompt,
        "resumed": False,
        "done": True,
        "errored": errored,
        "text": "\n\n".join(text_parts),
        "children": children,
    }


def _history_subagent_entries(parent_session_id, toolcall_id):
    """The root subagent block for a DispatchSubagent tool call, as a list.

    Builds the whole nested subagent subtree iteratively (no recursion):
    a breadth-first discovery pass starts from
    get_child_session_by_toolcall(parent_session_id, toolcall_id), caches
    each discovered session's load_messages result (one DB read per
    session) and queues deeper sessions discovered via DispatchSubagent
    tool calls (resolved with get_child_session_by_toolcall per child).
    Blocks are then built deepest-first by iterating the discovery order
    in reverse, so every nested block exists in the blocks dict before
    its parent embeds it from there.

    Returns [root_block], or [] when the root lookup/build fails so
    history loading is never broken; a broken child session only prunes
    its own subtree and never breaks its ancestors.
    """
    from Agent.chat_history_db import get_child_session_by_toolcall, load_messages

    try:
        root = get_child_session_by_toolcall(parent_session_id, toolcall_id)
        if root is None:
            return []
        root_id = root["id"]

        # BFS discovery: map each session id to its cached messages (None
        # when the read failed, so its block build fails cleanly and its
        # children   undiscoverable without the messages   are pruned).
        messages_by_sid = {}
        queue = [root_id]
        while queue:
            sid = queue.pop(0)
            if sid in messages_by_sid:
                continue
            try:
                messages_by_sid[sid] = load_messages(sid)
            except Exception as err:
                print(f"[raggie-acp] subagent history load failed: {err}", file=sys.stderr)
                messages_by_sid[sid] = None
                continue
            for msg in messages_by_sid[sid]:
                if msg.get("role") != "assistant":
                    continue
                for tc in msg.get("tool_calls") or []:
                    func = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                    if (func.get("name") or "unknown tool") != "DispatchSubagent":
                        continue
                    nested_id = str(tc.get("id") or "")
                    if not nested_id:
                        continue
                    try:
                        nested_child = get_child_session_by_toolcall(sid, nested_id)
                    except Exception:
                        continue
                    if nested_child is not None and nested_child["id"] not in messages_by_sid:
                        queue.append(nested_child["id"])

        # Build deepest-first (reverse BFS order) so nested blocks exist
        # before their parents embed them.
        blocks = {}
        for sid in reversed(list(messages_by_sid.keys())):
            block = _history_subagent_block(sid, messages_by_sid[sid], blocks)
            if block is not None:
                blocks[sid] = block
        root_block = blocks.get(root_id)
        return [root_block] if root_block is not None else []
    except Exception as err:
        print(f"[raggie-acp] subagent history lookup failed: {err}", file=sys.stderr)
        return []


def _history_display_entries(page):
    """Turn a chronological chunk of raw DB messages into web-UI entries.

    Reconstructs tool calls from the persisted OpenAI-style tool_calls and
    attaches each stored tool response (role "tool", or a user-role vision
    response linked by tool_call_id) as the matching tool call's output.
    The machine-generated handover prompt is hidden; the agent-written
    handover document carries handover=True.

    DispatchSubagent tool calls are replaced by their reconstructed subagent
    block(s) so chat history shows the same nested streaming view as the
    live turn.
    """
    entries = []
    # tool_call_id (from assistant tool_calls) -> entry awaiting its output
    pending_outputs = {}
    pending_tool_names = {}
    for msg in page:
        role = msg.get("role")
        content = msg.get("content")
        tool_call_id = msg.get("tool_call_id")

        if tool_call_id and (role in ("tool", "user")):
            # A tool response: attach as output to its tool call entry.
            entry = pending_outputs.get(str(tool_call_id))
            if entry is not None:
                if isinstance(content, list):
                    content = "\n".join(
                        str(block.get("text", "")) for block in content
                        if isinstance(block, dict)
                    )
                output = content if isinstance(content, str) else str(content or "")
                output = _truncate_tool_output(
                    pending_tool_names.get(str(tool_call_id)), output
                )
                entry["output"] = output
                if output.lstrip().startswith("Error:"):
                    entry["status"] = "failed"
            # Tool responses never render on their own.
            continue

        if msg.get("kind") == "handover_prompt":
            continue

        if role == "user":
            entry = {"id": msg["id"], "role": "user", "text": str(content)}
            if msg.get("kind") == "handover_doc":
                entry["handover"] = True
            entries.append(entry)
        elif role == "assistant":
            if isinstance(content, str) and content.strip():
                entries.append({"id": msg["id"], "role": "agent", "text": content})
            for idx, tc in enumerate(msg.get("tool_calls") or []):
                func = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                name = func.get("name") or "unknown tool"
                tool_id = str(msg["id"]) + "-" + str(idx)
                if name == "DispatchSubagent":
                    blocks = _history_subagent_entries(
                        msg.get("session_id"), str(tc.get("id") or tool_id)
                    )
                    if blocks:
                        # The block already carries prompt, tool work and the
                        # response   no separate flat tool entry needed.
                        entries.extend(blocks)
                        continue
                entry = {
                    "id": tool_id,
                    "kind": "tool",
                    "toolCallId": tc.get("id") or tool_id,
                    "title": _history_tool_title(name, func.get("arguments")),
                    "status": "completed",
                    "input": _format_tool_input(func.get("arguments")),
                }
                entries.append(entry)
                if tc.get("id"):
                    pending_outputs[str(tc.get("id"))] = entry
                    pending_tool_names[str(tc.get("id"))] = name
    return entries


def _raggie_version():
    try:
        return pkg_version("raggiecode")
    except Exception:
        return "dev"


class _Session:
    __slots__ = (
        "session_id",
        "agent",
        "cancel_event",
        "current_tool_call_id",
        "tool_seq",
    )

    def __init__(self, session_id, agent):
        self.session_id = session_id
        self.agent = agent
        self.cancel_event = threading.Event()
        self.current_tool_call_id = None
        self.tool_seq = 0


class RaggieACPAgent:
    """Implements the ACP Agent interface using a per-session Raggie Agent."""

    def __init__(self, role="code", debug=False):
        self.role = role
        self.debug = debug
        self.sessions = {}
        self._conn = None
        self._loop = None
        self._cwd = None

    def on_connect(self, conn):
        self._conn = conn

    # -- lifecycle ------------------------------------------------------

    async def initialize(self, protocol_version, client_capabilities=None, client_info=None, **kwargs):
        return schema.InitializeResponse(
            protocol_version=acp.PROTOCOL_VERSION,
            agent_capabilities=schema.AgentCapabilities(
                load_session=False,
                prompt_capabilities=schema.PromptCapabilities(
                    image=False, audio=False, embedded_context=False
                ),
            ),
            agent_info=schema.Implementation(name="raggie", version=_raggie_version()),
        )

    async def authenticate(self, method_id, **kwargs):
        return None

    async def new_session(self, cwd, mcp_servers=None, additional_directories=None, **kwargs):
        loop = asyncio.get_running_loop()
        self._loop = loop
        try:
            session = await loop.run_in_executor(None, self._create_session, cwd)
        except Exception as err:
            raise acp.RequestError.internal_error({"detail": str(err)})
        self.sessions[session.session_id] = session
        return schema.NewSessionResponse(session_id=session.session_id)

    def _create_session(self, cwd):
        """Create a session bound to a brand-new chat."""
        return self._build_session(cwd, None)

    def _build_session(self, cwd, chat_id):
        """Shared session construction for new_session/open_session.

        chat_id=None creates a new chat; otherwise the session binds to the
        existing chat (creating a session row for it if none is active).
        """
        from Agent.agent import Agent
        from Agent.chat_history_db import (
            create_chat,
            get_or_create_session,
            get_session_thinking_mode,
            init_db,
            set_session_thinking_mode,
        )
        from Agent.thinking_modes import DEFAULT_THINKING_MODE
        from Commands import setup_commands
        from Tools import setup_toolcalls

        target = os.path.abspath(cwd)
        if self._cwd is None:
            os.chdir(target)
            self._cwd = target
        elif target != self._cwd:
            print(
                f"[raggie-acp] warning: session cwd '{target}' ignored; "
                f"process is rooted at '{self._cwd}'",
                file=sys.stderr,
            )

        init_db()
        if chat_id is None:
            chat_id = create_chat(self.role)
        agent = Agent(
            self.role,
            chat_id=int(chat_id),
            session_id=get_or_create_session(int(chat_id)),
            debug=self.debug,
        )
        # Stream completions so the web UI gets progressive chunks and the
        # per-session cancel flag takes effect mid-generation.
        agent.stream = True
        setup_toolcalls(agent.tool_registry)
        setup_commands(agent.command_registry)
        try:
            import mcp_client
            mcp_client.setup(agent.tool_registry)
        except Exception as err:
            print(f"[raggie-acp] MCP setup failed: {err}", file=sys.stderr)
        if get_session_thinking_mode(agent.session_id) is None:
            set_session_thinking_mode(agent.session_id, DEFAULT_THINKING_MODE)
        session = _Session(f"raggie-{agent.session_id}", agent)
        # Cooperative cancellation: long-running tools (Shell) poll this
        # between poll ticks so a cancelled turn stops the worker quickly,
        # and the agent loop itself aborts per-chunk work and guards
        # tool-call dispatch on the same session cancel event.
        agent.tool_registry.set_cancel_check(session.cancel_event.is_set)
        agent.set_cancel_check(session.cancel_event.is_set)
        return session

    # -- prompting ------------------------------------------------------

    async def has_dangling(self, session_id, **kwargs):
        """Report whether the session has interrupted work (dangling tool calls).

        Returned as {"pending": bool, "count": int, "tools": [...]} so the web
        UI can offer a resume button, like the terminal UI does on startup.
        """
        session = self.sessions.get(session_id)
        if session is None:
            raise acp.RequestError.invalid_params({"detail": f"unknown session '{session_id}'"})
        agent = session.agent

        def check():
            pending = agent._get_pending_toolcalls()
            tools = []
            for toolcall in pending:
                func = toolcall.get("function", {}) if isinstance(toolcall, dict) else {}
                tools.append(_history_tool_title(
                    func.get("name") or "unknown tool", func.get("arguments")
                ))
            # A turn interrupted right after its final tool response, or a
            # stored user prompt that never got a response, has no pending
            # tool call but is still resumable. Report the same predicate
            # resume uses so the resume button appears whenever resume would
            # actually do work.
            has_work = (
                agent._has_dangling_tool_work()
                or agent._ends_with_unanswered_user_message()
            )
            return {"pending": has_work, "count": len(pending), "tools": tools}

        return await asyncio.get_running_loop().run_in_executor(None, check)

    async def resume(self, session_id, _previous_turn=None, **kwargs):
        """Resume interrupted work (dangling tool calls) for a session.

        Same streaming contract as prompt: ACP updates flow over the SSE
        stream until the resumed turn finishes. Only an actually
        interrupted turn is resumed (dangling tool calls, or a stored user
        prompt that never got a response); when the history shows nothing
        to resume the turn ends quietly instead of firing an empty prompt.
        """
        session = self.sessions.get(session_id)
        if session is None:
            raise acp.RequestError.invalid_params({"detail": f"unknown session '{session_id}'"})

        await self._await_quiet_turn(_previous_turn)

        # Guard the chat only for the duration of this turn so idle
        # sessions do not block other raggie instances from opening it.
        from Agent import chat_lock
        if not chat_lock.acquire(session.agent.chat_id):
            raise acp.RequestError.invalid_params(
                {"detail": f"chat {session.agent.chat_id} is in use by another raggie instance"}
            )
        try:
            session.cancel_event.clear()
            loop = asyncio.get_running_loop()
            self._loop = loop
            stop_reason = await loop.run_in_executor(None, self._pump_resume, session)
            return schema.PromptResponse(stop_reason=stop_reason)
        finally:
            chat_lock.release(session.agent.chat_id)

    async def _await_quiet_turn(self, previous):
        """Wait for an in-flight turn (e.g. one still winding down after a
        cancel) to finish, so two workers never mutate one session's agent
        concurrently.

        Takes the future directly instead of looking it up in the hub:
        the transport captures the previous turn's future BEFORE the new
        turn is submitted, so it can never be the turn's own future (the
        hub entry is only registered after submit)."""
        if previous is not None and not previous.done():
            await asyncio.wrap_future(previous)

    async def prompt(self, session_id, prompt, _previous_turn=None, **kwargs):
        session = self.sessions.get(session_id)
        if session is None:
            raise acp.RequestError.invalid_params({"detail": f"unknown session '{session_id}'"})

        text = "\n\n".join(
            block.text for block in prompt
            if isinstance(block, schema.TextContentBlock) and block.text
        )
        if not text.strip():
            return schema.PromptResponse(stop_reason="refusal")

        # A still-winding-down cancelled turn must finish first, or two
        # workers would mutate the same agent's history concurrently.
        await self._await_quiet_turn(_previous_turn)

        # Guard the chat only for the duration of this turn so idle
        # sessions do not block other raggie instances from opening it.
        from Agent import chat_lock
        if not chat_lock.acquire(session.agent.chat_id):
            raise acp.RequestError.invalid_params(
                {"detail": f"chat {session.agent.chat_id} is in use by another raggie instance"}
            )
        try:
            session.cancel_event.clear()
            loop = asyncio.get_running_loop()
            self._loop = loop
            stop_reason = await loop.run_in_executor(None, self._pump, session, text)
            return schema.PromptResponse(stop_reason=stop_reason)
        finally:
            chat_lock.release(session.agent.chat_id)

    async def cancel(self, session_id, **kwargs):
        session = self.sessions.get(session_id)
        if session is not None:
            session.cancel_event.set()

    # -- chat management (web transport) ---------------------------------

    async def list_chats(self, **kwargs):
        """List chats for this agent's role, with a preview of the last message."""
        from Agent.chat_history_db import get_chat_preview
        from Agent.chat_history_db import list_chats as db_list_chats

        result = []
        for chat in db_list_chats(self.role):
            preview = get_chat_preview(chat["id"]) or {}
            result.append({
                "id": str(chat["id"]),
                "title": chat["title"],
                "updatedAt": chat["updated_at"],
                "previewRole": preview.get("role"),
                "preview": preview.get("text"),
            })
        return result

    async def open_session(self, cwd, chat_id, **kwargs):
        """Create (or reuse) a session bound to an existing chat."""
        from Agent.chat_history_db import get_chat_role

        try:
            chat_id = int(chat_id)
        except (TypeError, ValueError):
            raise acp.RequestError.invalid_params({"detail": f"invalid chat id '{chat_id}'"})
        if get_chat_role(chat_id) is None:
            raise acp.RequestError.invalid_params({"detail": f"unknown chat '{chat_id}'"})

        loop = asyncio.get_running_loop()
        self._loop = loop
        try:
            session = await loop.run_in_executor(None, self._build_session, cwd, chat_id)
        except Exception as err:
            raise acp.RequestError.internal_error({"detail": str(err)})
        self.sessions[session.session_id] = session
        return schema.NewSessionResponse(session_id=session.session_id)

    async def delete_chat(self, chat_id, **kwargs):
        """Delete a chat and all its sessions and messages."""
        from Agent.chat_history_db import delete_chat as db_delete_chat
        from Agent.chat_history_db import get_chat_role

        try:
            chat_id = int(chat_id)
        except (TypeError, ValueError):
            raise acp.RequestError.invalid_params({"detail": f"invalid chat id '{chat_id}'"})
        if get_chat_role(chat_id) is None:
            raise acp.RequestError.invalid_params({"detail": f"unknown chat '{chat_id}'"})

        # Allow deleting a chat this instance itself holds, but refuse to
        # delete a chat another raggie instance is actively working on.
        from Agent import chat_lock
        if not (chat_lock.is_held(chat_id) or chat_lock.probe(chat_id)):
            raise acp.RequestError.invalid_params(
                {"detail": "chat is in use by another raggie instance"}
            )

        def _delete():
            db_delete_chat(chat_id)
            return {"ok": True}

        return await asyncio.get_running_loop().run_in_executor(None, _delete)

    async def search_messages(self, query, limit=None, **kwargs):
        """Full-text search over user messages (FTS5) for the web UI.

        Returns [{"chatId", "title", "messageId", "snippet", "updatedAt"}]
        ordered by relevance so the user can jump straight to a match.
        """
        from Agent.chat_history_db import search_user_messages

        def _search():
            return search_user_messages(
                str(query or ""),
                self.role,
                limit=int(limit) if limit else 10,
            )

        return await asyncio.get_running_loop().run_in_executor(None, _search)

    async def chat_history(self, session_id, before_id=None, limit=None, **kwargs):
        """Return chat history for the web UI, paginated on demand.

        Messages from handed-over sessions are included so the history
        predating a handover stays visible (like the terminal UI does).

        Returns {"messages": [...], "hasMore": bool, "nextBefore": id} where
        messages is chronological [{"id", "role": "user"|"agent", "text",
        "handover"?}]   handover prompt messages carry handover=True.
        Without *limit*, the whole history is returned (hasMore=False).
        """
        session = self.sessions.get(session_id)
        if session is None:
            raise acp.RequestError.invalid_params({"detail": f"unknown session '{session_id}'"})
        agent = session.agent

        from Agent.chat_history_db import get_old_session_ids, load_messages_page

        def session_chain():
            old_ids = get_old_session_ids(agent.chat_id, agent.session_id)
            return old_ids + [agent.session_id]

        if limit is None:
            def load_all():
                # Full annotated history across the handed-over session chain.
                page, _, _ = load_messages_page(session_chain(), before_id=None, limit=10**9)
                return _history_display_entries(page)

            messages = await asyncio.get_running_loop().run_in_executor(None, load_all)
            return {"messages": messages, "hasMore": False, "nextBefore": None}

        def load_page():
            before = int(before_id) if before_id not in (None, "") else None
            return load_messages_page(session_chain(), before_id=before, limit=int(limit))

        page, oldest_id, has_more = await asyncio.get_running_loop().run_in_executor(
            None, load_page
        )

        return {"messages": _history_display_entries(page), "hasMore": has_more,
                "nextBefore": oldest_id}

    async def health_stats(self, session_id, **kwargs):
        """On-demand health stats summary for the web UI modal."""
        session = self.sessions.get(session_id)
        if session is None:
            raise acp.RequestError.invalid_params({"detail": f"unknown session '{session_id}'"})

        payload = await asyncio.get_running_loop().run_in_executor(
            None, session.agent._build_health_stats_payload
        )
        if not payload:
            raise acp.RequestError.invalid_params({"detail": "no health data available"})
        return payload

    async def health_report(self, session_id, **kwargs):
        """Full code complexity report text (same content /health writes).

        Returns {"filename": str, "text": str} or None when there is nothing
        to report; the UI turns it into a downloaded .txt file.
        """
        session = self.sessions.get(session_id)
        if session is None:
            raise acp.RequestError.invalid_params({"detail": f"unknown session '{session_id}'"})

        report = await asyncio.get_running_loop().run_in_executor(
            None, session.agent._build_full_complexity_report
        )
        if not report:
            raise acp.RequestError.invalid_params({"detail": "no health data available"})
        from datetime import datetime
        filename = f"complexity_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        return {"filename": filename, "text": report}

    async def active_todo(self, session_id, **kwargs):
        """Active todo list with its tasks for the web UI todo bar/modal."""
        session = self.sessions.get(session_id)
        if session is None:
            raise acp.RequestError.invalid_params({"detail": f"unknown session '{session_id}'"})

        from Agent.chat_history_db import (
            get_active_todo_list,
            get_todo_tasks,
            resolve_session_id,
        )

        effective_id = await asyncio.get_running_loop().run_in_executor(
            None, resolve_session_id, session.agent.session_id
        )
        todo = await asyncio.get_running_loop().run_in_executor(
            None, get_active_todo_list, effective_id
        )
        if todo is None:
            return None
        tasks = await asyncio.get_running_loop().run_in_executor(
            None, get_todo_tasks, todo["id"]
        )
        return {**todo, "tasks": tasks}

    # -- first-time setup (web UI) ---------------------------------------

    async def setup_status(self, **kwargs):
        """Setup inspection for the first-run web UI setup page.

        Reports whether keys and role configuration exist and are readable.
        Only masked keys are returned   never the raw secrets.
        """
        from Agent.config import load_keys, load_roles
        from Agent.providers import KNOWN_PROVIDERS, parse_key_id, suggest_base_url, get_behavior

        def _build():
            try:
                keys = load_keys()
            except Exception:
                keys = {}
            try:
                roles = load_roles()
            except Exception:
                roles = {}

            key_list = []
            for key_id, raw_key in keys.items():
                provider, base_url = parse_key_id(key_id)
                masked = raw_key[:4] + "..." + raw_key[-4:] if len(raw_key) > 8 else "****"
                key_list.append({
                    "id": key_id,
                    "provider": provider or "",
                    "baseUrl": base_url or key_id,
                    "masked": masked,
                })

            role_list = [
                {
                    "name": name,
                    "model": cfg.get("model", ""),
                    "baseUrl": cfg.get("base_url", ""),
                    "provider": cfg.get("provider", ""),
                    "contextWindow": cfg.get("context_window") or "",
                    "reasoningEffort": cfg.get("reasoning_effort") or "auto",
                    "userAgent": cfg.get("user_agent") or "",
                }
                for name, cfg in roles.items()
            ]

            # The default per-role: available reasoning effort values and suggested base url.
            provider_options = []
            for p in KNOWN_PROVIDERS:
                try:
                    behavior = get_behavior(p)
                    effort_values = list(behavior.get("reasoning_effort_values", []))
                except Exception:
                    behavior, effort_values = None, []
                if effort_values:
                    effort_values.append("auto")
                provider_options.append({
                    "name": p,
                    "baseUrl": suggest_base_url(p),
                    "reasoningEffortValues": effort_values or ["auto"],
                })

            # Setup is complete when there is at least one API key and
            # every role has a model and base_url wired up.
            roles_ready = bool(roles) and all(
                cfg.get("model") and cfg.get("base_url") for cfg in roles.values()
            )
            return {
                "setupComplete": bool(keys) and roles_ready,
                "keys": key_list,
                "roles": role_list,
                "providers": provider_options,
                # The role this agent instance runs as; lets the chat view
                # show the model + reasoning effort it is actually using.
                "activeRole": self.role,
            }

        return await asyncio.get_running_loop().run_in_executor(None, _build)

    async def setup_add_key(self, provider, base_url, api_key, **kwargs):
        """Store a new API key (same behavior as the `raggie setup` wizard)."""
        from Agent.config import USER_CONFIG_DIR
        from Agent.providers import KNOWN_PROVIDERS, make_key_id

        def _save():
            keys_file = USER_CONFIG_DIR / "keys.json"
            if provider not in KNOWN_PROVIDERS:
                raise acp.RequestError.invalid_params({"detail": f"unknown provider '{provider}'"})
            if not api_key or not base_url:
                raise acp.RequestError.invalid_params({"detail": "base_url and api_key are required"})
            key_id = make_key_id(provider, base_url)
            keys_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                keys = json.loads(keys_file.read_text()) if keys_file.exists() else {}
            except Exception:
                keys = {}
            keys[key_id] = api_key
            keys_file.write_text(json.dumps(keys, indent=2))
            return {"keyId": key_id}

        return await asyncio.get_running_loop().run_in_executor(None, _save)

    async def setup_remove_key(self, key_id, **kwargs):
        from Agent.config import USER_CONFIG_DIR

        def _remove():
            keys_file = USER_CONFIG_DIR / "keys.json"
            try:
                keys = json.loads(keys_file.read_text()) if keys_file.exists() else {}
            except Exception:
                keys = {}
            keys.pop(key_id, None)
            keys_file.parent.mkdir(parents=True, exist_ok=True)
            keys_file.write_text(json.dumps(keys, indent=2))
            return {"ok": True}

        return await asyncio.get_running_loop().run_in_executor(None, _remove)

    async def setup_update_role(self, role, model=None, base_url=None, provider=None,
                                context_window=None, reasoning_effort=None, user_agent=None, **kwargs):
        from Agent.config import load_roles, save_roles

        def _update():
            roles = load_roles()
            if role not in roles:
                raise acp.RequestError.invalid_params({"detail": f"unknown role '{role}'"})
            cfg = roles[role]
            # Only overwrite fields that were actually provided.
            if model is not None:
                cfg["model"] = model
            if base_url is not None:
                cfg["base_url"] = base_url
            if provider is not None:
                cfg["provider"] = provider
            if context_window is not None:
                cfg["context_window"] = int(context_window) if context_window != "" else None
            if reasoning_effort is not None:
                effort = (reasoning_effort or "").strip()
                cfg["reasoning_effort"] = effort
                # No effort configured -> reasoning is off.
                cfg["reasoning"] = bool(effort)
            if user_agent is not None:
                cfg["user_agent"] = (user_agent or "").strip()
            save_roles(roles)
            return {"ok": True}

        return await asyncio.get_running_loop().run_in_executor(None, _update)

    async def update_active_role(self, model=None, reasoning_effort=None, **kwargs):
        """Update the running role's model and/or reasoning effort.

        Persists to roles.json (so future sessions pick it up) and applies the
        change to every live session's agent so the current chat uses it on
        the next turn   mirroring the terminal ``/model`` and
        ``/reasoningEffort`` commands.
        """
        from Agent.config import load_roles, save_roles

        def _update():
            roles = load_roles()
            if self.role not in roles:
                raise acp.RequestError.invalid_params(
                    {"detail": f"unknown role '{self.role}'"}
                )
            cfg = roles[self.role]

            new_model = None
            new_effort = None

            if model is not None:
                value = (model or "").strip()
                if not value:
                    raise acp.RequestError.invalid_params({"detail": "model must not be empty"})
                cfg["model"] = value
                new_model = value

            if reasoning_effort is not None:
                effort = (reasoning_effort or "").strip()
                cfg["reasoning_effort"] = effort
                cfg["reasoning"] = bool(effort)
                new_effort = effort

            save_roles(roles)

            # Apply to every live session's agent so the change is effective
            # for the next turn without reopening the chat.
            for session in self.sessions.values():
                agent = session.agent
                role_cfg = agent.roles.get(agent.agent_role)
                if role_cfg is None:
                    continue
                if new_model is not None:
                    role_cfg["model"] = new_model
                if new_effort is not None:
                    role_cfg["reasoning_effort"] = new_effort
                    role_cfg["reasoning"] = bool(new_effort)
                    agent.reasoning_effort = new_effort
                    agent.reasoning = bool(new_effort)

            return {"ok": True}

        return await asyncio.get_running_loop().run_in_executor(None, _update)


    async def setup_update_key(self, key_id, api_key, **kwargs):
        """Replace the secret for an existing key id.

        The base URL/provider pair of an existing key is fixed   users who
        want to change endpoints remove the key and re-add it. The current
        key value is never returned to the client.
        """
        from Agent.config import USER_CONFIG_DIR

        def _update():
            keys_file = USER_CONFIG_DIR / "keys.json"
            try:
                keys = json.loads(keys_file.read_text()) if keys_file.exists() else {}
            except Exception:
                keys = {}
            if key_id not in keys:
                raise acp.RequestError.invalid_params({"detail": f"unknown key '{key_id}'"})
            if not api_key:
                raise acp.RequestError.invalid_params({"detail": "api_key is required"})
            keys[key_id] = api_key
            keys_file.parent.mkdir(parents=True, exist_ok=True)
            keys_file.write_text(json.dumps(keys, indent=2))
            return {"ok": True}

        return await asyncio.get_running_loop().run_in_executor(None, _update)

    # -- MCP server management (web UI) ----------------------------------

    async def mcp_list(self, **kwargs):
        """List configured MCP servers for the web UI settings page.

        Each stored config is normalized into the fields the UI shows: kind
        ("stdio" for a command, "http" for a URL, else "unknown"), the
        stdio command/args/env and the http url, plus the trust flag. A
        non-dict entry and an unreadable config file both degrade to an
        empty/partial listing instead of failing the request.
        """
        from Agent.config import USER_CONFIG_DIR, load_mcp_servers

        def _build():
            path = str(USER_CONFIG_DIR / "mcp_servers.json")
            try:
                servers = load_mcp_servers()
            except Exception:
                servers = {}
            if not isinstance(servers, dict):
                servers = {}
            entries = []
            for name, cfg in servers.items():
                if not isinstance(cfg, dict):
                    cfg = {}
                command = cfg.get("command")
                url = cfg.get("url")
                if command:
                    kind = "stdio"
                elif url:
                    kind = "http"
                else:
                    kind = "unknown"
                args = cfg.get("args")
                if not isinstance(args, list):
                    args = []
                env = cfg.get("env")
                if not isinstance(env, dict):
                    env = {}
                entries.append({
                    "name": name,
                    "kind": kind,
                    "command": command or "",
                    "args": [str(a) for a in args],
                    "env": {str(k): str(v) for k, v in env.items()},
                    "url": url or "",
                    "trust": bool(cfg.get("trust", False)),
                })
            return {"path": path, "servers": entries}

        return await asyncio.get_running_loop().run_in_executor(None, _build)

    async def mcp_add(self, name, command=None, args=None, env=None, url=None, trust=False, **kwargs):
        """Add an MCP server (same behavior as `raggie mcp --add`)."""
        from Agent.config import load_mcp_servers, save_mcp_servers

        def _add():
            clean = (name or "").strip()
            if not clean:
                raise acp.RequestError.invalid_params({"detail": "name is required"})
            if not url and not command:
                raise acp.RequestError.invalid_params(
                    {"detail": "either url or command is required"}
                )
            servers = load_mcp_servers()
            if not isinstance(servers, dict):
                servers = {}
            if clean in servers:
                raise acp.RequestError.invalid_params(
                    {"detail": f"server '{clean}' already exists; remove it first"}
                )
            cfg = {}
            # A URL wins over a command: a server is either http (url) or
            # stdio (command), never both.
            if url:
                cfg["url"] = url
            else:
                cfg["command"] = command
                cfg["args"] = [str(a) for a in (args or [])]
                clean_env = {str(k): str(v) for k, v in (env or {}).items() if k}
                if clean_env:
                    cfg["env"] = clean_env
            if trust:
                cfg["trust"] = True
            servers[clean] = cfg
            save_mcp_servers(servers)
            return {"ok": True, "name": clean}

        return await asyncio.get_running_loop().run_in_executor(None, _add)

    async def mcp_remove(self, name, **kwargs):
        """Remove a configured MCP server (same behavior as `raggie mcp --remove`)."""
        from Agent.config import load_mcp_servers, save_mcp_servers

        def _remove():
            clean = (name or "").strip()
            servers = load_mcp_servers()
            if not isinstance(servers, dict) or clean not in servers:
                raise acp.RequestError.invalid_params(
                    {"detail": f"no server named '{clean}' is configured"}
                )
            del servers[clean]
            save_mcp_servers(servers)
            return {"ok": True}

        return await asyncio.get_running_loop().run_in_executor(None, _remove)

    async def mcp_test(self, name, **kwargs):
        """Connect to one configured MCP server and list its discovered tools.

        Same behavior as `raggie mcp --test`: a temporary manager connects
        to just this server and is always shut down afterwards.
        """
        from Agent.config import load_mcp_servers

        def _test():
            clean = (name or "").strip()
            servers = load_mcp_servers()
            if not isinstance(servers, dict) or clean not in servers:
                raise acp.RequestError.invalid_params(
                    {"detail": f"no server named '{clean}' is configured"}
                )
            try:
                import mcp_client
            except Exception as err:
                raise acp.RequestError.invalid_params(
                    {"detail": f"MCP support is unavailable: {err}"}
                )
            manager = mcp_client.McpManager()
            try:
                count = manager.connect({clean: servers[clean]})
                if count == 0:
                    return {"ok": False, "tools": [], "error": "failed to connect"}
                return {"ok": True, "tools": manager.tool_names, "error": ""}
            finally:
                manager.shutdown()

        return await asyncio.get_running_loop().run_in_executor(None, _test)

    async def commands_list(self, **kwargs):
        """List registered slash commands for the web UI command menu.

        Builds a fresh registry (no session needed) so the menu is always
        the full command set.
        """
        from Commands import setup_commands
        from Agent.command import CommandRegistry

        registry = CommandRegistry()
        setup_commands(registry)
        return registry.list_commands(role=self.role)

    # -- worker thread ---------------------------------------------------

    def _forward_subagent_event(self, session, payload):
        """Forward a subagent bridge frame to the web UI (no-op in stdio mode)."""
        send = getattr(self._conn, "subagent_event", None)
        if not callable(send):
            return
        try:
            asyncio.run_coroutine_threadsafe(
                send(session.session_id, payload), self._loop
            ).result()
        except Exception as err:
            print(f"[raggie-acp] failed to send subagent update: {err}", file=sys.stderr)

    def _stream_agent_events(self, session, get_events, status_label=None):
        """Shared streaming loop for prompt turns and resume turns.

        get_events() must return an event generator; it is called in the
        worker thread. Returns the stop reason string.
        """
        io_backend.set_permission_handler(self._make_permission_handler(session))
        io_backend.set_ask_handler(self._make_ask_handler(session))
        # Register the subagent bridge sink so DispatchSubagent work streams
        # to the UI while the parent tool call is still running. The bridge
        # no-ops when the transport has no subagent_event channel (stdio).
        try:
            from Tools.dispatch_subagent import register_parent_sink, unregister_parent_sink
            register_parent_sink(
                session.agent.session_id,
                lambda payload: self._forward_subagent_event(session, payload),
            )
            subagent_sink_registered = True
        except Exception as err:
            print(f"[raggie-acp] subagent sink registration failed: {err}", file=sys.stderr)
            subagent_sink_registered = False
        try:
            cancelled = False
            for event in get_events():
                if session.cancel_event.is_set():
                    cancelled = True
                if cancelled:
                    # Wind-down after a cancel: the pre-streaming behavior
                    # let the current completion finish and persist the
                    # assistant message, leaving resumable dangling tool
                    # calls. Keep that: consume chunk events silently so
                    # the in-flight completion completes and is persisted,
                    # then stop before anything else runs (no further
                    # sends, no further tool executions).
                    if event[0] in ("response_chunk", "reasoning_chunk"):
                        continue
                    return "cancelled"
                try:
                    self._send_event(session, event)
                except Exception as err:
                    print(f"[raggie-acp] failed to send update: {err}", file=sys.stderr)
            return "end_turn"
        except Exception as err:
            try:
                self._send_update(session, update_agent_message_text(f"\n\nError: {err}"))
            except Exception:
                pass
            return "end_turn"
        finally:
            io_backend.clear_permission_handler()
            io_backend.clear_ask_handler()
            if subagent_sink_registered:
                try:
                    from Tools.dispatch_subagent import unregister_parent_sink
                    unregister_parent_sink(session.agent.session_id)
                except Exception:
                    pass

    def _pump(self, session, text):
        """Run the raggie generator in a worker thread, streaming ACP updates."""
        return self._stream_agent_events(session, lambda: session.agent.start(text))

    def _pump_resume(self, session):
        """Resume dangling tool work in a worker thread, streaming ACP updates.

        Mirrors the terminal UI's startup behavior: interrupted turns leave
        tool calls without responses; re-running them repairs the history and
        the agent continues where it stopped.
        """
        return self._stream_agent_events(
            session, lambda: session.agent.resume_dangling_tool_work()
        )

    def _send_update(self, session, update):
        future = asyncio.run_coroutine_threadsafe(
            self._conn.session_update(session.session_id, update), self._loop
        )
        future.result()

    def _send_event(self, session, event):
        kind = event[0]

        if kind == "response_chunk" or kind == "response":
            self._send_update(session, update_agent_message_text(event[1]))

        elif kind == "reasoning_chunk" or kind == "reasoning":
            self._send_update(session, update_agent_thought_text(event[1]))

        elif kind == "tool_call":
            tool_name, tool_args = event[1], event[2]
            session.tool_seq += 1
            call_id = f"{session.session_id}-tool-{session.tool_seq}"
            session.current_tool_call_id = call_id
            try:
                raw_input = json.loads(tool_args) if isinstance(tool_args, str) else tool_args
            except (json.JSONDecodeError, TypeError):
                raw_input = {"arguments": tool_args}
            self._send_update(
                session,
                start_tool_call(
                    call_id,
                    _history_tool_title(tool_name, raw_input),
                    status="in_progress",
                    raw_input=raw_input,
                ),
            )

        elif kind == "tool_result":
            _, tool_name, content, is_error = event
            call_id = session.current_tool_call_id or f"{session.session_id}-tool-unknown"
            content = content if isinstance(content, str) else str(content)
            content = _truncate_tool_output(tool_name, content)
            self._send_update(
                session,
                update_tool_call(
                    call_id,
                    status="failed" if is_error else "completed",
                    content=[tool_content(text_block(content))] if content else None,
                    raw_output=content,
                ),
            )

        elif kind == "error":
            self._send_update(session, update_agent_message_text(f"\n\n**Error:** {event[1]}"))

        elif kind == "notice":
            send_notice = getattr(self._conn, "session_notice", None)
            if callable(send_notice):
                # Web mode: command output goes to a dedicated notice frame.
                clean = io_backend._ANSI_RE.sub("", event[1])
                asyncio.run_coroutine_threadsafe(
                    send_notice(session.session_id, clean), self._loop
                ).result()
            else:
                # stdio mode: command output was never forwarded before, but
                # keep it visible on the redirected protocol stderr.
                print(event[1], file=sys.stderr)

        elif kind == "health_stats":
            send_health = getattr(self._conn, "health_stats", None)
            if callable(send_health):
                # Web mode: dedicated notification with the structured payload
                # (falls back to the plain text when the payload builder is
                # unavailable); the chat text stays clean.
                payload_builder = getattr(session.agent, "_build_health_stats_payload", None)
                payload = payload_builder() if callable(payload_builder) else None
                value = payload if payload is not None else io_backend._ANSI_RE.sub("", event[1])
                asyncio.run_coroutine_threadsafe(
                    send_health(session.session_id, value), self._loop
                ).result()
            else:
                # stdio mode: no dedicated channel, keep the text fallback.
                self._send_update(session, update_agent_message_text(f"\n\n{event[1]}"))

        elif kind == "status":
            session_status = getattr(self._conn, "session_status", None)
            if callable(session_status):
                asyncio.run_coroutine_threadsafe(
                    session_status(session.session_id, event[1]), self._loop
                ).result()

        elif kind == "handover_doc":
            send_handover = getattr(self._conn, "session_handover", None)
            if callable(send_handover):
                # Web mode: dedicated notification carrying the handover doc.
                # No text fallback in stdio mode: the terminal already prints
                # it via src/interactive.py, and chat text would pollute the
                # transcript.
                asyncio.run_coroutine_threadsafe(
                    send_handover(session.session_id, event[1]), self._loop
                ).result()

        elif kind == "status_done":
            session_status = getattr(self._conn, "session_status", None)
            if callable(session_status):
                asyncio.run_coroutine_threadsafe(
                    session_status(session.session_id, None), self._loop
                ).result()

    # -- permissions & asks -----------------------------------------------

    def _make_ask_handler(self, session):
        conn = self._conn
        loop = self._loop

        def handler(question, options=None, allow_multiple=False):
            request_ask = getattr(conn, "request_ask", None)
            if not callable(request_ask):
                return ""
            try:
                future = asyncio.run_coroutine_threadsafe(
                    request_ask(
                        session.session_id, question,
                        options=list(options or []),
                        allow_multiple=bool(allow_multiple),
                    ), loop
                )
                return future.result() or ""
            except Exception:
                return ""

        return handler

    def _make_permission_handler(self, session):
        conn = self._conn
        loop = self._loop

        def handler(title, detail, allow_always=False):
            options = [
                schema.PermissionOption(option_id="allow", name="Allow", kind="allow_once"),
                schema.PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
            ]
            if allow_always:
                options.insert(1, schema.PermissionOption(
                    option_id="allow_always", name="Always Allow", kind="allow_always",
                ))
            tool_call = schema.ToolCallUpdate(
                tool_call_id=session.current_tool_call_id or f"{session.session_id}-permission",
                title=title,
                status="pending",
            )
            future = asyncio.run_coroutine_threadsafe(
                conn.request_permission(
                    session.session_id, tool_call=tool_call, options=options,
                    detail=detail,
                ),
                loop,
            )
            response = future.result()
            option_id = getattr(response.outcome, "option_id", None)
            if option_id == "allow_always":
                return "always"
            return option_id == "allow"

        return handler
