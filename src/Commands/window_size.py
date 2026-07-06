def handle(args, agent):
    """Set the context window size mid-conversation.

    Usage: /WindowSize 202752
    """
    from Agent.config import save_roles

    arg = args.strip()

    if not arg:
        current = agent.roles[agent.agent_role].get("context_window", "?")
        print(f"Context window: {current}  (usage: /WindowSize <number>)")
        return ""

    try:
        value = int(arg)
    except ValueError:
        print(f"Invalid value '{arg}'. Must be a number.")
        return ""

    if value <= 0:
        print("Context window must be positive.")
        return ""

    agent.roles[agent.agent_role]["context_window"] = value
    save_roles(agent.roles)
    print(f"Context window: {value} (saved)")

    return ""
