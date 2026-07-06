import inspect


class ToolRegistry:

    def __init__(self):
        self.tools = {}
        self.agent_role = None
        self.code_indexer = None

    def set_handler(self, name, callback):
        self.tools[name] = callback

    def call(self, name, arguments, toolcall_id, parent_session_id=None):
        if name not in self.tools:
            raise KeyError(f"Tool '{name}' is not registered")

        tool = self.tools[name]
        signature = inspect.signature(tool)
        params = signature.parameters
        has_agent_role = "agent_role" in params
        has_parent_session_id = "parent_session_id" in params

        kwargs = {}
        if "code_indexer" in params:
            kwargs["code_indexer"] = self.code_indexer

        if has_agent_role and has_parent_session_id:
            return tool(arguments, toolcall_id, self.agent_role, parent_session_id, **kwargs)
        if has_agent_role:
            return tool(arguments, toolcall_id, self.agent_role, **kwargs)
        if has_parent_session_id or len(params) >= 3:
            return tool(arguments, toolcall_id, parent_session_id, **kwargs)

        return tool(arguments, toolcall_id, **kwargs)
