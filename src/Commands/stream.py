def handle(args, agent):
    """Toggle streaming mode on/off mid-conversation.

    Usage: /streaming on  or  /streaming off
    """
    from Agent.config import save_roles

    arg = args.strip().lower()

    if arg in ("on", "true", "yes"):
        agent.streaming = True
        agent.roles[agent.agent_role]["stream"] = True
        save_roles(agent.roles)
        print("Streaming: on (saved)")
    elif arg in ("off", "false", "no"):
        agent.streaming = False
        agent.roles[agent.agent_role]["stream"] = False
        save_roles(agent.roles)
        print("Streaming: off (saved)")
    else:
        state = "on" if agent.streaming else "off"
        print(f"Streaming: {state}  (usage: /stream on|off)")

    return ""
