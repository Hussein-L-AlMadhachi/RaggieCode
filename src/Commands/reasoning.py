def handle(args, agent):
    """Toggle reasoning mode on/off mid-conversation.

    Usage: /reasoning on  or  /reasoning off
    """
    from Agent.config import save_roles

    arg = args.strip().lower()

    if arg in ("on", "true", "yes"):
        agent.reasoning = True
        agent.roles[agent.agent_role]["reasoning"] = True
        save_roles(agent.roles)
        print("Reasoning: on (saved)")
    elif arg in ("off", "false", "no"):
        agent.reasoning = False
        agent.roles[agent.agent_role]["reasoning"] = False
        save_roles(agent.roles)
        print("Reasoning: off (saved)")
    else:
        state = "on" if agent.reasoning else "off"
        print(f"Reasoning: {state}  (usage: /reasoning on|off)")

    return ""
