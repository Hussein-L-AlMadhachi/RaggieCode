def handle(args, agent):
    """Set or show the thinking mode for the current session.

    Usage:
      /thinkingMode              Show current thinking mode and available options
      /thinkingMode <level>      Set mode by name (zen, serious, extreme, feral, insane)
    """
    from Agent.thinking_modes import THINKING_MODES, thinking_mode_name
    from Agent.chat_history_db import get_session_thinking_mode, set_session_thinking_mode

    arg = args.strip()

    if not arg:
        from interactive import _prompt_thinking_mode
        _prompt_thinking_mode(agent.session_id)
        return ""

    level_names = ", ".join(info["name"].lower() for info in THINKING_MODES.values())

    # Try numeric match
    try:
        mode = int(arg)
    except ValueError:
        # Try name match (case-insensitive)
        lower = arg.lower()
        for num, info in THINKING_MODES.items():
            if info["name"].lower() == lower:
                mode = num
                break
        else:
            print(f"Unknown thinking mode: {arg}")
            print(f"Available: {', '.join(info['name'].lower() for info in THINKING_MODES.values())}")
            return ""

    if mode not in THINKING_MODES:
        print(f"Invalid thinking mode: {mode}")
        print(f"Available modes: {', '.join(info['name'].lower() for info in THINKING_MODES.values())}")
        return ""

    set_session_thinking_mode(agent.session_id, mode)
    print(f"Thinking mode: {thinking_mode_name(mode)}")

    return ""
