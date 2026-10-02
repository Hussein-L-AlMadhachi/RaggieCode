"""In-chat command: import Agent Skills from local directories into a role.

The ``/importSkills`` command scans a directory (by default
``.agents/skills`` relative to the current working directory) for skill
directories that contain a ``SKILL.md`` file. For each one it prompts for a
name (defaulting to the frontmatter ``name``) and a confirmation, then stores
the raw ``SKILL.md`` content against the current role in the skill database.

Only ``SKILL.md`` is imported; the optional ``scripts/``, ``references/`` and
``assets/`` directories described by the Agent Skills spec are ignored (a
warning is printed when they exist).
"""

import os
from pathlib import Path


def handle(args, agent) -> str:
    """Import ``SKILL.md`` files from disk into the current role's skills.

    Args:
        args: Optional directory to scan. When empty, ``.agents/skills`` under
            the current working directory is used.
        agent: The Agent instance; its ``agent_role`` selects the target role.

    Returns:
        Always the empty string, so the agent is never invoked.
    """
    role = getattr(agent, "agent_role", None)
    if not role:
        print("No active role; cannot import skills.")
        return ""

    arg = args.strip()
    if arg:
        base_dir = Path(arg)
    else:
        base_dir = Path(os.getcwd()) / ".agents" / "skills"

    if not base_dir.is_dir():
        print(f"No skills directory found at: {base_dir}")
        print("Pass a directory to scan, or create .agents/skills/ with one SKILL.md per skill folder.")
        return ""

    from skills import SkillManager
    from skills.manager import discover_skill_dirs, parse_frontmatter

    skill_dirs = discover_skill_dirs(base_dir)
    if not skill_dirs:
        print(f"No SKILL.md files found under: {base_dir}")
        return ""

    import io_backend

    manager = SkillManager()
    imported = []
    skipped = []

    for skill_dir in sorted(skill_dirs):
        # Resolve the skill file: SKILL.md first, then skill.md.
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            skill_md = skill_dir / "skill.md"

        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError as err:
            print(f"  skipped {skill_dir}: could not read SKILL.md ({err})")
            skipped.append(skill_dir.name)
            continue

        try:
            meta, _ = parse_frontmatter(content)
        except Exception as err:
            print(f"  skipped {skill_dir}: could not parse frontmatter ({err})")
            skipped.append(skill_dir.name)
            continue

        default_name = str(meta.get("name") or "").strip()

        if default_name:
            answer = io_backend.ask(
                f"Import '{skill_dir.name}' as [Enter = '{default_name}']: ",
                default=default_name,
            ).strip()
            name = answer or default_name
        else:
            answer = io_backend.ask(
                f"Import '{skill_dir.name}' as (no name in frontmatter): "
            ).strip()
            if not answer:
                print("  skipped: no name provided")
                skipped.append(skill_dir.name)
                continue
            name = answer

        if manager.get_skill(role, name) is not None:
            print(f"  skipped: skill '{name}' already exists for role '{role}'")
            skipped.append(name)
            continue

        if not io_backend.confirm(
            f"Import skill '{name}' into role '{role}'?",
            detail=f"Source: {skill_md}",
        ):
            print("  skipped: not confirmed")
            skipped.append(name)
            continue

        manager.set_skill(role, name, content)
        imported.append(name)
        print(f"  imported: {name}")

        extra = [
            sub
            for sub in ("scripts", "references", "assets")
            if (skill_dir / sub).is_dir()
        ]
        if extra:
            print(
                "  warning: only SKILL.md was imported; skipped: "
                + ", ".join(extra)
            )

    print()
    print(f"Imported {len(imported)} skill(s) into role '{role}'.")
    if imported:
        print(f"  Imported: {', '.join(imported)}")
    if skipped:
        print(f"  Skipped: {', '.join(skipped)}")
    if imported:
        print("Run /reload-skills to make the new skills available in this session.")
    return ""
