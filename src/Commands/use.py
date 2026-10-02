def handle(args, agent):
    """Inject a skill's full content into the conversation as a user message."""
    from skills import SkillManager

    skill_name = args.strip()
    if not skill_name:
        print("Usage: /use <skill-name>")
        print("Lists all skills if you run /use with no arguments.")
        print("Use /skills to see available skills.")
        return ""

    manager = SkillManager()

    # Try the current role first, then search all roles
    content = manager.get_skill(agent.agent_role, skill_name)
    role_used = agent.agent_role

    if content is None:
        # Search across all roles
        all_skills = manager.list_skills()
        for skill in all_skills:
            if skill["name"] == skill_name:
                content = manager.get_skill(skill["role"], skill_name)
                role_used = skill["role"]
                break

    if content is None:
        print(f"Skill '{skill_name}' not found. Use /skills to list available skills.")
        return ""

    # Strip frontmatter from the content   the model only needs the body
    from skills.manager import parse_frontmatter
    meta, body = parse_frontmatter(content)
    skill_body = body if meta else content

    print(f"  [skill] loaded: {role_used}/{skill_name}")

    # Return the skill content as the prompt for the agent to process
    return f"Here is the skill '{skill_name}' for reference. Follow its instructions:\n\n{skill_body}"
