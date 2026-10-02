from Agent.command import CommandRegistry


def setup_commands(registry: CommandRegistry):
    """Register all user-facing commands with the registry."""
    from . import (
        undo, redo, shell, reasoning, window_size, help, global_todo,
        thinking_mode, unlimited_thinking_mode, reindex, skills, reload_skills, use,
        import_skills, health_report, model, reasoning_effort, debug, whitelist,
    )

    def _skill_choices(role=None):
        """Skill names for /use, resolved per role (empty on failure)."""
        try:
            from skills import SkillManager
            return [s["name"] for s in SkillManager().list_skills_by_role(role or "code")]
        except Exception:
            return []

    def _reasoning_effort_choices(role=None):
        """Valid reasoning_effort values for the role's provider."""
        try:
            from Agent.config import load_roles
            from Agent.providers import get_behavior
            roles = load_roles()
            provider = roles.get(role or "code", {}).get("provider", "")
            values = list(get_behavior(provider).get("reasoning_effort_values", []))
            if values:
                values.append("auto")
            return values
        except Exception:
            return []

    def _thinking_mode_names(role=None):
        """Thinking mode names (lowercase), in level order."""
        from Agent.thinking_modes import THINKING_MODES
        return [info["name"].lower() for info in THINKING_MODES.values()]

    def _thinking_mode_usage():
        """Usage hint generated from the mode table, e.g.
        '/thinkingMode <mode>   zen | serious | extreme | feral | insane'."""
        return f"/thinkingMode <mode>   {' '.join(_thinking_mode_names())}"

    registry.register(
        "/undo", undo.handle,
        "Undo the last code change (git snapshot rollback)",
    )
    registry.register(
        "/redo", redo.handle,
        "Redo the last undone code change",
    )
    registry.register(
        "!", shell.handle,
        "Run a shell command directly",
        usage="!<command>   e.g. !ls -la",
    )
    registry.register(
        "/reasoning", reasoning.handle,
        "Toggle reasoning mode on/off",
        usage="/reasoning on|off",
        choices=["on", "off"],
    )
    registry.register(
        "/reasoningEffort", reasoning_effort.handle,
        "Set the reasoning effort for the role",
        usage="/reasoningEffort low|medium|high",
        choices=_reasoning_effort_choices,
    )
    registry.register(
        "/model", model.handle,
        "Change the model for the current role",
        usage="/model <model-name>",
    )
    registry.register(
        "/windowSize", window_size.handle,
        "Set the context window size in tokens",
        usage="/windowSize <tokens>   e.g. /windowSize 202752",
    )
    registry.register(
        "/help", help.handle,
        "Show available in-chat commands",
    )
    registry.register(
        "/globalTodo", global_todo.handle,
        "Toggle sharing todo lists across all subagent sessions",
        usage="/globalTodo on|off",
        choices=["on", "off"],
    )
    registry.register(
        "/thinkingMode", thinking_mode.handle,
        "Set or show the thinking mode for this session",
        usage=_thinking_mode_usage(),
        choices=_thinking_mode_names,
    )
    registry.register(
        "/unlimitedThinkingMode", unlimited_thinking_mode.handle,
        "Set truly unlimited subagent depth",
    )
    registry.register(
        "/reindex", reindex.handle,
        "Re-index the codebase",
        usage="/reindex [--force]   --force rebuilds from scratch",
        choices=["", "--force"],
    )
    registry.register(
        "/skills", skills.handle,
        "List all available skills with summaries",
    )
    registry.register(
        "/reload-skills", reload_skills.handle,
        "Re-scan skill directories and rebuild the skills section",
    )
    registry.register(
        "/use", use.handle,
        "Inject a skill's full content into the conversation",
        usage="/use <skill-name>",
        choices=_skill_choices,
    )
    registry.register(
        "/importSkills", import_skills.handle,
        "Import SKILL.md directories into the current role's skills",
        usage="/importSkills [directory]   default: .agents/skills",
    )
    registry.register(
        "/health", health_report.handle,
        "Generate the full code complexity report to a .txt file",
    )
    registry.register(
        "/debug", debug.handle,
        "Toggle raw tool call output",
        usage="/debug on|off",
        choices=["on", "off"],
    )
    registry.register(
        "/whitelist", whitelist.handle,
        "Review shell commands whitelisted for the current role",
    )
