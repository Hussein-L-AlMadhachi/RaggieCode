def handle(args, agent):
    """Change the model for the current role mid-conversation.

    Usage:
      /model            Show the current model
      /model <name>     Set the model (persists to roles.json)
    """
    from Agent.config import save_roles

    arg = args.strip()

    if not arg:
        current = agent.roles[agent.agent_role].get("model", "")
        print(f"Model: {current}")
        print("Usage: /model <name>")
        return ""

    agent.roles[agent.agent_role]["model"] = arg
    save_roles(agent.roles)
    print(f"Model: {arg} (saved)")
    return ""
