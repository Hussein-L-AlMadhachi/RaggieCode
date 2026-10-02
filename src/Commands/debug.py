def handle(args, agent):
    """Toggle debug mode at runtime.

    Usage:
      /debug          Show current debug state
      /debug on        Enable debug (tool call outputs shown)
      /debug off       Disable debug
    """
    import io_backend

    arg = args.strip().lower()

    if not arg:
        state = "on" if agent.debug else "off"
        print(f"Debug: {state}")
        print("Usage: /debug on|off")
        return ""

    if arg in ("on", "true", "1", "yes"):
        agent.debug = True
        io_backend.set_debug(True)
        print("Debug: on (tool call outputs will be shown)")
    elif arg in ("off", "false", "0", "no"):
        agent.debug = False
        io_backend.set_debug(False)
        print("Debug: off")
    else:
        print("Usage: /debug on|off")
    return ""
