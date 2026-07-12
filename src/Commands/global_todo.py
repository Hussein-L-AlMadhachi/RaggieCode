def handle(args, agent):
    """Toggle global todo list mode on/off mid-conversation.

    When enabled, todo lists are shared across all subagent sessions.
    Usage: /globalTodo on  or  /globalTodo off
    """
    from Agent.config import save_roles

    arg = args.strip().lower()

    if arg in ("on", "true", "yes"):
        agent.roles[agent.agent_role]["globalTodo"] = True
        save_roles(agent.roles)
        print("Global todo: on (saved) — todo lists are now shared across all subagent sessions")
    elif arg in ("off", "false", "no"):
        agent.roles[agent.agent_role]["globalTodo"] = False
        save_roles(agent.roles)
        print("Global todo: off (saved) — todo lists are session-scoped")
    else:
        state = "on" if agent.roles.get(agent.agent_role, {}).get("globalTodo", False) else "off"
        print(f"Global todo: {state}  (usage: /globalTodo on|off)")

    return ""
