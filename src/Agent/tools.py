import inspect
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from indexing.code_index_sdk import CodeIndexSDK


class ToolRegistry:

    def __init__(self):
        self.tools = {}
        self.agent_role = None
        self.code_indexer: Optional["CodeIndexSDK"] = None
        self.cancel_check = None

    def set_handler(self, name, callback):
        self.tools[name] = callback

    def set_cancel_check(self, fn):
        self.cancel_check = fn

    def call(self, name, arguments, toolcall_id, parent_session_id=None):
        if name not in self.tools:
            raise KeyError(f"Tool '{name}' is not registered")

        tool = self.tools[name]
        try:
            return self._dispatch(tool, arguments, toolcall_id, parent_session_id)
        except KeyError as err:
            # Missing required argument in the tool's arguments dict   turn the
            # bare "'symbol_name'" style message into something actionable.
            missing = str(err).strip("'\"")
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": (
                    f"Error: missing required tool argument '{missing}' for "
                    f"'{name}'. Re-issue the tool call with '{missing}' provided "
                    "(large arguments may have been truncated   keep new_source "
                    "complete and send one edit per call)."
                ),
            }

    def _dispatch(self, tool, arguments, toolcall_id, parent_session_id):
        signature = inspect.signature(tool)
        params = signature.parameters
        has_agent_role = "agent_role" in params
        has_parent_session_id = "parent_session_id" in params

        kwargs = {}
        if "code_indexer" in params:
            kwargs["code_indexer"] = self.code_indexer
        # Tools that declare cancel_check get the registry-level hook (may be
        # None   e.g. terminal mode   and tools must tolerate that).
        if "cancel_check" in params:
            kwargs["cancel_check"] = self.cancel_check

        if has_agent_role and has_parent_session_id:
            return tool(arguments, toolcall_id, self.agent_role, parent_session_id, **kwargs)
        if has_agent_role:
            return tool(arguments, toolcall_id, self.agent_role, **kwargs)
        if has_parent_session_id or "session_id" in params:
            return tool(arguments, toolcall_id, parent_session_id, **kwargs)

        return tool(arguments, toolcall_id, **kwargs)
