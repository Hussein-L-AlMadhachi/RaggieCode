def handle(args, agent):
    """Set or show the effort level for the current session.

    Usage:
      /effort            Show current effort level and available options
      /effort <num>      Set effort by number (1-5)
      /effort <name>     Set effort by name (zen, serious, extreme, feral, insane)
    """
    from Agent.effort_levels import EFFORT_LEVELS, effort_name
    from Agent.chat_history_db import get_session_effort, set_session_effort

    arg = args.strip()

    if not arg:
        from interactive import _prompt_effort
        _prompt_effort(agent.session_id)
        return ""

    # Try numeric match
    try:
        effort = int(arg)
    except ValueError:
        # Try name match (case-insensitive)
        lower = arg.lower()
        for num, info in EFFORT_LEVELS.items():
            if info["name"].lower() == lower:
                effort = num
                break
        else:
            print(f"Unknown effort level: {arg}")
            print(f"Available: {', '.join(info['name'] for info in EFFORT_LEVELS.values())}")
            return ""

    if effort not in EFFORT_LEVELS:
        print(f"Invalid effort level: {effort}")
        print(f"Pick a number between 1 and {len(EFFORT_LEVELS)}")
        return ""

    set_session_effort(agent.session_id, effort)
    print(f"Effort: {EFFORT_LEVELS[effort]['name']}")

    return ""
