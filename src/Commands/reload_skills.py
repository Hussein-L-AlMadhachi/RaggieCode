def handle(args, agent):
    """Re-scan skill directories and rebuild the system prompt's skills section."""
    from skills import SkillManager

    manager = SkillManager()

    # Count skills before reload
    before = set(s["role"] + "/" + s["name"] for s in manager.list_skills())

    # Re-run auto-discovery from project directories
    discovered = manager.auto_discover(agent.agent_role)
    for name in discovered:
        print(f"  [skill] discovered: {name}")

    # Count skills after reload
    after = set(s["role"] + "/" + s["name"] for s in manager.list_skills())
    added = after - before
    removed = before - after

    # Rebuild the system prompt so the new skills are advertised to the model
    agent.system_prompt = agent._build_system_prompt(agent.agent_role)

    # Replace the system message in chat history
    for i, msg in enumerate(agent.chat_history):
        if msg.get("role") == "system":
            agent.chat_history[i]["content"] = agent.system_prompt
            break

    print()
    print(f"Skills reloaded: {len(after)} available ({len(added)} added, {len(removed)} removed)")
    if added:
        print(f"  Added: {', '.join(sorted(added))}")
    if removed:
        print(f"  Removed: {', '.join(sorted(removed))}")
    if not added and not removed:
        print("  No changes detected.")
    return ""
