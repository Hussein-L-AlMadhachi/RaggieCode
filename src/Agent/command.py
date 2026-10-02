class CommandRegistry:
    """Registry for slash commands and other user-facing commands.

    Commands are registered with a prefix (e.g. ``/undo``, ``!``) and a
    handler function.  When the user's prompt starts with a registered
    prefix, the matching handler is invoked with the remaining argument
    string and the agent instance.

    Handler signature::

        def handle(args: str, agent: Agent) -> str | None

    *args* is everything after the prefix (stripped).  Returning ``None``
    signals that the command was a no-op (e.g. empty ``!`` with no command).
    """

    def __init__(self):
        self.commands = {}
        self.descriptions = {}
        self.usages = {}
        self.choices = {}

    def register(self, prefix, handler, description="", usage="", choices=None):
        """Register a command handler for a given prefix.

        *description* is a short one-line summary shown in UIs that list
        the available commands. *usage* is a parameter example string
        ("" when the command takes no arguments). *choices* is an optional
        list of fixed argument options (or a callable ``(role) -> list``)
        that UIs can render as a submenu; when present the command should
        be invoked as ``<prefix> <choice>`` (or ``<prefix>`` for an empty
        choice string).
        """
        self.commands[prefix] = handler
        self.descriptions[prefix] = description
        self.usages[prefix] = usage
        self.choices[prefix] = choices

    def list_commands(self, role=None):
        """All registered commands as [{"name", "description", "usage",
        "choices", "kind"}].

        Callable *choices* providers are resolved with the given role.
        *kind* tells UIs how to present the command: "choices" (fixed
        argument options), "input" (free-form argument needed) or
        "action" (run as-is).
        """
        result = []
        for prefix in self.commands:
            choices = self.choices.get(prefix)
            if callable(choices):
                try:
                    choices = choices(role)
                except Exception:
                    choices = []
            if not choices:
                choices = None
            if choices:
                kind = "choices"
            elif self.usages.get(prefix):
                kind = "input"
            else:
                kind = "action"
            result.append({
                "name": prefix,
                "description": self.descriptions.get(prefix, ""),
                "usage": self.usages.get(prefix, ""),
                "choices": choices,
                "kind": kind,
            })
        return result


    # returns <bool>, <str>
    # if bool is true the agent need to use <str> as prompt
    # no action is needed form the agent and it will ignore the string
    def try_handle(self, prompt, agent):
        command = ""
        args = ""
        if len(prompt) >= 1 and prompt[0] == "!":
            command = "!"
            args = prompt[1:].strip()
        elif not " " in prompt:
            command = prompt
        else:
            command = prompt[:prompt.index(" ")]
            args = prompt[prompt.index(" ") + 1:].strip()

        handler = self.commands.get(command)

        if handler == None:
            return True, prompt # process normal prompts that does not match the rules must be processed by the agent
        
        result = handler(args, agent)
        if result == "":
            return False, "" #do not serve the agent any prompt. what string you return do not matter here
        else:
            return True, result
