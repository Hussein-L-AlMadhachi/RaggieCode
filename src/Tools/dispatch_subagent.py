import json
import sys
import threading

from .utils import BLUE, RESET


# Programming errors   a retry cannot fix any of these, and none can be caused
# by a bad LLM response, a network fault, or an API error. Anything else is
# treated as an operational failure and reported back to the parent agent.
_BUG_TYPES = (TypeError, AttributeError, NameError, ImportError)


# ---------------------------------------------------------------------------
# Subagent activity bridge (web UI)
#
# Tool handlers run synchronously inside the parent agent's worker thread, so
# subagent events cannot be yielded through the generator chain like the main
# agent's events are. Instead, while a prompt is running the active transport
# registers a sink for the parent session below; the dispatch publishes frames
# to it and the transport forwards them to the UI. With no sink registered
# (terminal / CLI mode) emission is a no-op   the terminal already shows this
# activity via the DIM prints in _collect_subagent_output.
# ---------------------------------------------------------------------------
_parent_sinks = {}
_sinks_lock = threading.Lock()


def register_parent_sink(parent_session_id, sink):
    with _sinks_lock:
        _parent_sinks[parent_session_id] = sink


def unregister_parent_sink(parent_session_id):
    with _sinks_lock:
        _parent_sinks.pop(parent_session_id, None)


def _emit_subagent_event(parent_session_id, payload):
    with _sinks_lock:
        sink = _parent_sinks.get(parent_session_id)
    if sink is None:
        return
    try:
        sink(payload)
    except Exception as err:
        print(f"[subagent] failed to forward event: {err}", file=sys.stderr)


class SubagentInternalError(BaseException):
    """A bug in subagent dispatch, raised so it reaches the operator.

    Derives from BaseException rather than Exception on purpose. Both
    _collect_subagent_output below and Agent._execute_tool_call
    (Agent/agent.py) wrap tool execution in a catch-all `except Exception`,
    which would otherwise turn a TypeError into a tool *result* string. The
    parent LLM then reads the stringified crash as data and its most likely
    next move is to retry the same call, which fails identically   burning
    tokens at every nesting level until the thinking mode depth limit stops it.

    Escaping both handlers surfaces the traceback instead. The dispatch is
    left recorded as a dangling toolcall, so resume_dangling_tool_work()
    re-executes it once the bug is fixed.
    """


def _collect_subagent_output(subagent, subagent_session_id, prompt=None, resume=False, emit=None):
    """Run a subagent and collect its output. If resume=True, resume dangling work instead of starting fresh.

    Returns a tuple (output, error_occurred) so callers can detect failure
    structurally instead of sniffing string prefixes.

    emit, when given, is called with a frame dict for every subagent event so
    a UI can stream the subagent's work live (see the bridge comment above).
    """
    import json

    from .utils import DIM

    debug = getattr(subagent, "debug", False)
    output_parts = []
    error_occurred = False
    tool_seq = 0
    last_tool_call_id = None

    def emit_event(phase, **fields):
        if emit is None:
            return
        payload = dict(fields)
        payload["phase"] = phase
        emit(payload)

    try:
        if resume:
            events = subagent.resume_dangling_tool_work()
        else:
            events = subagent.start(prompt=prompt)

        if events is None:
            events = []

        for event in events:
            event_type, *event_data = event
            if event_type == "response":
                output_parts.append(event_data[0])
                emit_event("chunk", text=event_data[0])
            elif event_type == "response_end":
                output_parts.append(event_data[0])
                emit_event("chunk", text=event_data[0])
            elif event_type == "reasoning" or event_type == "reasoning_chunk":
                emit_event("thought", text=event_data[0])
            elif event_type == "error":
                emit_event("error", text=str(event_data[0]))
                output_parts.append(f"Error: {event_data[0]}")
                error_occurred = True
                break
            elif event_type == "tool_call":
                tool_name, tool_args = event_data[0], event_data[1]
                tool_seq += 1
                last_tool_call_id = f"sub-{subagent_session_id}-{tool_seq}"
                emit_event(
                    "tool_call",
                    toolCallId=last_tool_call_id,
                    title=tool_name,
                    status="in_progress",
                    input=tool_args if isinstance(tool_args, str) else json.dumps(tool_args),
                )
                if debug:
                    try:
                        args_dict = json.loads(tool_args)
                        desc = ", ".join(f"{k}={str(v)[:40]}" for k, v in args_dict.items())
                    except Exception:
                        desc = ""
                    print(f"{DIM}  [subagent tool] {tool_name}({desc}){RESET}")
            elif event_type == "tool_result":
                tool_name, content, is_error = event_data[0], event_data[1], event_data[2]
                emit_event(
                    "tool_result",
                    toolCallId=last_tool_call_id,
                    status="failed" if is_error else "completed",
                    output=str(content)[:4000],
                )
                if debug:
                    label = f"[subagent tool error] {tool_name}" if is_error else f"[subagent tool output] {tool_name}"
                    print(f"{DIM}  {label}{RESET}")
                    if content:
                        print(f"{DIM}{content}{RESET}")
    except _BUG_TYPES as e:
        raise SubagentInternalError(
            f"{type(e).__name__} while collecting subagent output "
            f"(session {subagent_session_id}): {e}"
        ) from e
    except Exception as e:
        output_parts.append(f"Subagent execution failed: {str(e)}")
        error_occurred = True

    output = "\n".join(output_parts) if output_parts else "No output from subagent"

    if error_occurred:
        output = f"Subagent encountered errors:\n{output}"

    emit_event("end", text=output, errored=error_occurred)

    from Agent.chat_history_db import get_all_changes_by_session_chain
    changes = get_all_changes_by_session_chain(subagent_session_id)
    if changes:
        changes_summary = "\n".join(
            f"  - [{c['change_type']}] {c['file_path'] or 'N/A'}: {c['description']}"
            for c in changes
        )
        output = f"{output}\n\n--- Changes made by subagent for you to review ---\n{changes_summary}"

    return output, error_occurred


def handle(arguments, toolcall_id, parent_session_id=None, skip_depth_check=False, cancel_check=None):
    prompt = arguments.get("prompt")

    if not prompt:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'prompt' is a required parameter",
        }

    if parent_session_id is None:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: parent_session_id is required to determine the subagent role",
        }

    from Agent.chat_history_db import get_session_role, get_session_thinking_mode, get_session_depth
    from Agent.thinking_modes import (
        is_depth_allowed, thinking_mode_name, thinking_mode_max_depth,
        DEFAULT_THINKING_MODE,
    )
    role = get_session_role(parent_session_id)
    if not role:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error: Could not determine role for parent session {parent_session_id}",
        }

    # Check depth limit via the thinking modes system
    if not skip_depth_check:
        thinking_mode = get_session_thinking_mode(parent_session_id)
        # A session with no stored mode must NOT bypass the limit: fall back
        # to the default mode so nesting stays bounded.
        effective_mode = thinking_mode if thinking_mode is not None else DEFAULT_THINKING_MODE
        depth = get_session_depth(parent_session_id)
        if not is_depth_allowed(effective_mode, depth):
            max_d = thinking_mode_max_depth(effective_mode)
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                # Marked as a dispatch failure so callers (e.g. the todo
                # executor's task-status logic) never mistake a refused
                # dispatch for a completed one.
                "dispatch_error": True,
                "content": f"Cannot dispatch subagent: thinking mode '{thinking_mode_name(effective_mode)}' limits depth to {max_d}. Current depth is {depth}.",
            }

    try:
        from Agent.chat_history_db import (
            get_chat_id_for_session, create_session, get_child_session_by_toolcall,
            is_session_finished, load_messages,
            get_session_thinking_mode, get_session_depth,
            resolve_session_id,
        )
        from Agent.agent import Agent
        from Tools import setup_toolcalls
        from Commands import setup_commands

        def first_user_prompt(session_id):
            """Original prompt of a (resumed) subagent, for the UI header."""
            for msg in load_messages(session_id):
                if msg.get("role") == "user":
                    return str(msg.get("content", "") or "")
            return None

        # Subagent sessions that already emitted a start frame; used to close
        # their UI block if the dispatch itself crashes.
        started_sessions = []

        def make_emit(subagent_session_id):
            """Build an emit callback pre-filled with session id + nesting level."""
            subagent_depth = get_session_depth(subagent_session_id)
            started_sessions.append(subagent_session_id)

            def _emit(payload):
                payload.setdefault("subagentSessionId", str(subagent_session_id))
                payload.setdefault("depth", subagent_depth)
                _emit_subagent_event(parent_session_id, payload)

            return _emit

        def collect_with_relay(subagent, run_session_id, **kwargs):
            """Run _collect_subagent_output with a relay sink registered under
            the running subagent's session.

            A nested DispatchSubagent call inside the subagent emits its
            events with parent_session_id set to this subagent's session  
            but only the top-level session has a real UI sink registered.
            Without the relay, every depth-2+ frame is silently dropped and
            the web UI shows nothing for nested subagents. The relay forwards
            those payloads up the sink chain (payloads already carry their
            own subagentSessionId/depth), so nested work streams live no
            matter how deep the dispatch chain goes.
            """
            register_parent_sink(
                run_session_id,
                lambda payload: _emit_subagent_event(parent_session_id, payload),
            )
            try:
                return _collect_subagent_output(subagent, run_session_id, **kwargs)
            finally:
                unregister_parent_sink(run_session_id)

        chat_id = get_chat_id_for_session(parent_session_id)
        if chat_id is None:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"Error: Could not find chat for parent session {parent_session_id}",
            }

        # Check for existing child session matching this toolcall_id (from a previous interrupted dispatch)
        child = get_child_session_by_toolcall(parent_session_id, toolcall_id)
        if child is not None:
            child_session_id = child["id"]
            # Follow redirect chain to find the active session (may have been handed over)
            active_session_id = resolve_session_id(child_session_id)
            if is_session_finished(child_session_id):
                # Subagent completed but main agent was interrupted before processing the result
                print(f"{BLUE}Found completed subagent session {active_session_id}, retrieving output...{RESET}")
                emit = make_emit(active_session_id)
                emit({"phase": "start", "prompt": first_user_prompt(active_session_id),
                      "role": role, "resumed": True})
                messages = load_messages(active_session_id)
                output_parts = []
                for msg in messages:
                    if msg.get("role") == "assistant" and not msg.get("tool_calls"):
                        output_parts.append(msg.get("content", ""))
                output = "\n".join(output_parts) if output_parts else "No output from subagent"

                from Agent.chat_history_db import get_all_changes_by_session_chain
                changes = get_all_changes_by_session_chain(active_session_id)
                if changes:
                    changes_summary = "\n".join(
                        f"  - [{c['change_type']}] {c['file_path'] or 'N/A'}: {c['description']}"
                        for c in changes
                    )
                    output = f"{output}\n\n--- Changes made by subagent for you to review ---\n{changes_summary}"

                emit({"phase": "chunk", "text": output})
                emit({"phase": "end", "text": output, "errored": False})

                return {
                    "role": "tool",
                    "tool_call_id": toolcall_id,
                    "content": output,
                    "subagent_session_id": active_session_id,
                }
            else:
                # Subagent was interrupted   resume it
                print(f"{BLUE}Resuming interrupted subagent session {active_session_id}...{RESET}")

                emit = make_emit(active_session_id)
                emit({"phase": "start", "prompt": first_user_prompt(active_session_id),
                      "role": role, "resumed": True})

                subagent = Agent(role=role, chat_id=chat_id, session_id=active_session_id)
                setup_toolcalls(subagent.tool_registry)
                setup_commands(subagent.command_registry)
                if cancel_check is not None:
                    subagent.set_cancel_check(cancel_check)
                    subagent.tool_registry.set_cancel_check(cancel_check)

                output, error_occurred = collect_with_relay(
                    subagent, active_session_id, resume=True, emit=emit
                )

                return {
                    "role": "tool",
                    "tool_call_id": toolcall_id,
                    "content": output,
                    "subagent_session_id": active_session_id,
                    "dispatch_error": error_occurred,
                }

        # No existing child session   create a new one under the parent's chat
        print(f"{BLUE}Dispatching subagent with role '{role}'{RESET}")
        parent_thinking_mode = get_session_thinking_mode(parent_session_id)
        parent_depth = get_session_depth(parent_session_id)
        subagent_session_id = create_session(
            chat_id, parent_session_id=parent_session_id, toolcall_id=toolcall_id,
            thinking_mode=parent_thinking_mode, depth=parent_depth + 1,
        )

        # Emit before Agent construction so the prompt is visible even when
        # the subagent itself cannot be started.
        emit = make_emit(subagent_session_id)
        emit({"phase": "start", "prompt": prompt, "role": role, "resumed": False})

        subagent = Agent(role=role, chat_id=chat_id, session_id=subagent_session_id)
        setup_toolcalls(subagent.tool_registry)
        setup_commands(subagent.command_registry)
        if cancel_check is not None:
            subagent.set_cancel_check(cancel_check)
            subagent.tool_registry.set_cancel_check(cancel_check)

        output, error_occurred = collect_with_relay(
            subagent, subagent_session_id, prompt=prompt, resume=False, emit=emit
        )

        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": output,
            "subagent_session_id": subagent_session_id,
            "dispatch_error": error_occurred,
        }

    except _BUG_TYPES as e:
        # Close any open subagent UI block so it cannot be stuck at "working".
        for sid in list(started_sessions):
            _emit_subagent_event(parent_session_id, {
                "phase": "end", "text": f"Dispatch failed: {e}",
                "errored": True,
                "subagentSessionId": str(sid),
                "depth": get_session_depth(sid),
            })
        raise SubagentInternalError(
            f"{type(e).__name__} in subagent dispatch "
            f"(parent session {parent_session_id}, toolcall {toolcall_id}): {e}"
        ) from e
    except Exception as e:
        for sid in list(started_sessions):
            _emit_subagent_event(parent_session_id, {
                "phase": "end", "text": f"Dispatch failed: {e}",
                "errored": True,
                "subagentSessionId": str(sid),
                "depth": get_session_depth(sid),
            })
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to dispatch subagent: {str(e)}",
            "dispatch_error": True,
        }
