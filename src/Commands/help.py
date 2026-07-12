def handle(args, agent):
    """Show available in-chat commands."""
    print()
    print("Available commands:")
    print()
    print("  /undo              Undo the last agent commit")
    print("  /redo              Re-apply the last undone commit")
    print("  /streaming on|off  Toggle streaming mode (persists to roles.json)")
    print("  /reasoning on|off  Toggle reasoning output (persists to roles.json)")
    print("  /windowSize <num>  Set context window size in tokens (persists to roles.json)")
    print("  /globalTodo on|off Toggle shared todo lists across subagents (persists to roles.json)")
    print("  /effort <num|name> Set effort level (1-5 or zen, serious, extreme, feral, insane)")
    print("  /help              Show this help message")
    print("  !<command>         Run a shell command (e.g. !ls -la)")
    print()
    print("  Ctrl+C             Go back (exits too)")
    print("  Ctrl+D             Leave the chat")
    print()
    print("Press Esc followed by Enter to send message, or type 'exit' to quit")

    return ""
