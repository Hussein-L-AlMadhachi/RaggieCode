# Skills

Skills are named instruction sets the agent can load when a task calls for them, such as a testing approach or a release checklist. They persist across chats and are stored per project.

## How it works

1. **At chat start**, every skill is listed in the system prompt as one line: `role/name: summary`.
2. **When a skill is relevant**, the agent calls `GetSkill(name)` and receives the full content as a tool result.
3. **The agent follows it** for the task at hand.

Only summaries cost tokens up front. Full content is loaded on demand.

You can also force a skill into the conversation yourself with `/use <name>`.

## Characteristics

- **Per role, by name.** A role can have many skills, e.g. `code/testing`, `code/git-workflow`. `GetSkill` and `SetSkill` always act on the agent's own role.
- **Stored in the project.** Skills live in `.raggie/.raggie.chat`, so each project has its own set.
- **Agent-authored, with consent.** The agent can create or update a skill with `SetSkill`. You are shown the full content and asked before anything is saved.
- **Summary source.** The `description` from the frontmatter if there is one, otherwise the first line of the content (up to 200 characters).

## Agent Skills format

Raggie reads and writes the [Agent Skills](https://agentskills.io) format: a folder per skill with a `SKILL.md` file.

```
my-skills/
├── web-testing/
│   └── SKILL.md
└── git-workflow/
    └── SKILL.md
```

```markdown
---
name: web-testing
description: Systematic approach to testing web applications
---

# Web Testing

When asked to test a web application:
1. Start with unit tests for individual components
2. Write integration tests for API endpoints
```

`name` becomes the skill name (the folder name is the fallback) and `description` becomes the summary. Other frontmatter fields are kept as is.

Only `SKILL.md` is imported. The optional `scripts/`, `references/` and `assets/` folders from the spec are not loaded.

## Auto-discovery

At chat start Raggie scans these folders in the project root and imports any skill it does not already have:

1. `.skills/`
2. `skills/`
3. `.claude/skills/`

Existing skills with the same name are never overwritten. Drop a skill folder into one of these directories and it is available on the next chat, or immediately with `/reload-skills`.

`.agents/skills/` is not scanned automatically. Import from it with `/importSkills`.

## In-chat commands

| Command | Description |
|---|---|
| `/skills` | List loaded skills with summaries |
| `/use <name>` | Inject a skill's content into the conversation now |
| `/reload-skills` | Re-run auto-discovery and refresh the skill list in the system prompt |
| `/importSkills [dir]` | Import `SKILL.md` folders from a directory (default `.agents/skills`). Asks for a name and confirmation per skill, and skips names that already exist. Run `/reload-skills` afterwards |

## CLI

Run these from the project directory.

```bash
raggie skill code                                   # interactive menu
raggie skill code --show --name testing             # print one skill
raggie skill code --import-skill my-skill.md --name testing
raggie skill code --export-skill backup.md --name testing
raggie skill code --delete --name testing
raggie skill --list-all

# Agent Skills folders
raggie skill code --import-skill-dir ./my-skills/              # a folder of skill folders
raggie skill code --import-skill-dir ./my-skills/web-testing/  # one skill folder
raggie skill code --export-skill-dir ./exported/ --name web-testing
```

When importing a Markdown file that has a `name` in its frontmatter, that name wins over `--name`. Exporting to a folder generates frontmatter if the skill has none.

## Where skills sit in the prompt

1. Role system prompt
2. Date, working directory, host info
3. Skill summaries
4. `AGENTS.md`

`AGENTS.md` comes last, so use it for rules that must always apply, and skills for knowledge that is only needed sometimes.
