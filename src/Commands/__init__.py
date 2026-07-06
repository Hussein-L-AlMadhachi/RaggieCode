from Agent.command import CommandRegistry


def setup_commands(registry: CommandRegistry):
    """Register all user-facing commands with the registry."""
    from . import undo, redo, shell, stream, reasoning, window_size, help

    registry.register("/undo", undo.handle)
    registry.register("/redo", redo.handle)
    registry.register("!", shell.handle)
    registry.register("/streaming", stream.handle)
    registry.register("/reasoning", reasoning.handle)
    registry.register("/windowSize", window_size.handle)
    registry.register("/help", help.handle)
