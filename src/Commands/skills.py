def handle(args, agent):
    """List all available skills with summaries."""
    from skills import SkillManager

    manager = SkillManager()
    all_skills = manager.list_skills()

    if not all_skills:
        print("No skills loaded. Place SKILL.md files in .skills/, skills/, or .claude/skills/")
        print("and run /reload-skills, or use 'raggie skill' to manage them manually.")
        return ""

    print()
    print(f"Loaded skills ({len(all_skills)}):")
    print()
    for skill in all_skills:
        print(f"  {skill['role']}/{skill['name']}")
        print(f"    {skill['summary']}")
        print()
    print("Use /use <skill-name> to inject a skill's content into the conversation.")
    print("Use /reload-skills to re-scan skill directories for changes.")
    return ""
