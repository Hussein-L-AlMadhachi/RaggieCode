def handle(args, agent):
    """Change the reasoning effort for the current role mid-conversation.

    This is the provider-specific reasoning_effort parameter (e.g. "low",
    "medium", "high") sent to the API, not the raggie effort level that
    controls turn count (use /thinkingMode for that).

    Usage:
      /reasoningEffort            Show current value and valid options
      /reasoningEffort <value>    Set the reasoning effort (persists to roles.json)
      /reasoningEffort auto       Clear the override (use provider default)
    """
    from Agent.config import save_roles
    from Agent.providers import get_behavior

    arg = args.strip()

    provider = agent.provider
    behavior = get_behavior(provider)
    valid_values = behavior.get("reasoning_effort_values", [])
    default = behavior.get("reasoning_effort_default", "")

    if not arg:
        current = agent.reasoning_effort or "(auto)"
        print(f"Reasoning effort: {current}")
        if valid_values:
            print(f"Valid values: {', '.join(valid_values)}")
        if default:
            print(f"Provider default: {default}")
        print("Usage: /reasoningEffort <value>  (or 'auto' to use provider default)")
        return ""

    if arg.lower() == "auto":
        agent.reasoning_effort = ""
        agent.roles[agent.agent_role]["reasoning_effort"] = ""
        save_roles(agent.roles)
        print(f"Reasoning effort: (auto)   provider default ({default})")
        return ""

    if valid_values and arg not in valid_values:
        print(f"Invalid value '{arg}'")
        print(f"Valid values: {', '.join(valid_values)}")
        return ""

    agent.reasoning_effort = arg
    agent.roles[agent.agent_role]["reasoning_effort"] = arg
    save_roles(agent.roles)
    print(f"Reasoning effort: {arg} (saved)")
    return ""
