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

    def register(self, prefix, handler):
        """Register a command handler for a given prefix."""
        self.commands[prefix] = handler


    # returns <bool>, <str>
    # if bool is true the agent need to use <str> as prompt
    # no action is needed form the agent and it will ignore the string
    def try_handle(self, prompt, agent):
        command = ""
        args = ""
        if not " " in prompt:
            command = prompt
        elif len(prompt) >= 1 and prompt[0] == "!":
            command = "!"
            args = prompt[1:].strip()
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
