import os
import re
import sqlite3

import yaml

from pathlib import Path
from typing import Optional
from raggie_dirs import get_chat_db_path

from Agent.chat_history_db import ensure_db_file


def _connect():
    """Open the chat DB, creating the .raggie dir and DB file if missing."""
    db_path = get_chat_db_path()
    ensure_db_file(db_path)
    return sqlite3.connect(db_path)


# YAML frontmatter pattern used by the Agent Skills standard (agentskills.io).
# Each SKILL.md starts with ---, then YAML metadata (name, description, ...),
# then ---, then the markdown body.
_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n?(.*)', re.DOTALL)


def _parse_frontmatter_lines(raw_meta):
    """Fallback line-based frontmatter parser for malformed YAML.

    Splits each line on ':' and lower-cases the key, stripping surrounding
    quotes from values. Used only when ``yaml.safe_load`` fails or returns a
    non-dict value.
    """
    fallback = {}
    for line in raw_meta.strip().splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        fallback[key] = value
    return fallback


def parse_frontmatter(content):
    """Parse YAML frontmatter from a SKILL.md file.

    Returns (metadata_dict, body_str). If no frontmatter is present,
    returns ({}, content).

    The metadata block is parsed with ``yaml.safe_load`` so nested mappings
    (e.g. ``metadata:``) become dicts and sequences (e.g. ``allowed-tools:``)
    are preserved. The Agent Skills standard fields (name, description,
    license, compatibility, metadata, allowed-tools) are all passed through.
    Top-level keys are normalized to lowercase strings. Malformed YAML falls
    back to a simple line-based parser so parsing never raises.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    raw_meta, body = match.group(1), match.group(2)
    try:
        parsed = yaml.safe_load(raw_meta)
    except yaml.YAMLError:
        parsed = None

    if not isinstance(parsed, dict):
        parsed = _parse_frontmatter_lines(raw_meta)

    meta = {}
    for key, value in parsed.items():
        if key is None:
            continue
        meta[str(key).strip().lower()] = value
    return meta, body.strip()


def build_frontmatter(name, description, **extra):
    """Build a YAML frontmatter block for a SKILL.md file."""
    lines = ["---", f"name: {name}", f"description: {description}"]
    for key, value in extra.items():
        if value:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def discover_skill_dirs(base_dir):
    """Return immediate subdirectories of ``base_dir`` that contain a skill file.

    A skill directory is a direct child directory containing a ``SKILL.md`` or
    ``skill.md`` file. The scan is one level deep (not recursive) and the
    result is sorted. Returns an empty list when ``base_dir`` is not a
    directory.
    """
    base = Path(base_dir)
    if not base.is_dir():
        return []

    skill_dirs = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        if (child / "SKILL.md").is_file() or (child / "skill.md").is_file():
            skill_dirs.append(child)
    return sorted(skill_dirs)


class SkillManager:
    """Manages role-specific skills stored in the database.

    Supports both Raggie's native format (plain markdown in the DB) and the
    Agent Skills standard (agentskills.io): directories with a SKILL.md file
    containing YAML frontmatter (name, description) + markdown body.
    """

    # Standard skill directory names to scan for auto-discovery, in priority order.
    SKILL_DIR_NAMES = [".skills", "skills", ".claude/skills"]

    def __init__(self):
        """Initialize the skill manager."""
        # No directory creation needed since the db path resolves at call time

    def get_skill(self, role: str, name: str) -> Optional[str]:
        """Load a specific skill for a role by name from the database."""
        conn = _connect()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT content FROM skills
            WHERE role = ? AND name = ?
        """, (role, name))

        result = cursor.fetchone()
        conn.close()

        return result[0] if result else None

    def list_skills_by_role(self, role: str) -> list:
        """Return all skills for a specific role with brief summaries."""
        conn = _connect()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name, content FROM skills
            WHERE role = ?
            ORDER BY name ASC
        """, (role,))

        skills = []
        for row in cursor.fetchall():
            name = row[0]
            content = row[1] or ""
            summary = self._extract_summary(content)
            skills.append({"role": role, "name": name, "summary": summary})

        conn.close()
        return skills

    def list_skills(self) -> list:
        """Return all skills with brief summaries (role + name + description/first line)."""
        conn = _connect()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT role, name, content FROM skills
            ORDER BY role ASC, name ASC
        """)

        skills = []
        for row in cursor.fetchall():
            role = row[0]
            name = row[1]
            content = row[2] or ""
            summary = self._extract_summary(content)
            skills.append({"role": role, "name": name, "summary": summary})

        conn.close()
        return skills

    def set_skill(self, role: str, name: str, content: str) -> None:
        """Save a skill for a specific role with a given name to the database."""
        conn = _connect()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO skills (role, name, content, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(role, name) DO UPDATE SET content = excluded.content, updated_at = CURRENT_TIMESTAMP
        """, (role, name, content))

        conn.commit()
        conn.close()

    def import_from_markdown(self, role: str, name: str, file_path: str) -> None:
        """Load skill from a markdown file into the database.

        If the file has YAML frontmatter with a 'name' field, that name is used
        instead of the provided name argument (Agent Skills compatibility).
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Skill file not found: {file_path}")

        content = path.read_text(encoding='utf-8')
        meta, _ = parse_frontmatter(content)
        skill_name = meta.get("name", name)
        self.set_skill(role, skill_name, content)

    def import_from_skill_dir(self, role: str, skill_dir: str) -> str:
        """Import a single Agent Skills directory (must contain SKILL.md).

        Returns the skill name that was imported.
        """
        path = Path(skill_dir)
        skill_md = path / "SKILL.md"
        if not skill_md.exists():
            # Also check lowercase skill.md for case-insensitive filesystems
            skill_md = path / "skill.md"
        if not skill_md.exists():
            raise FileNotFoundError(f"No SKILL.md found in {skill_dir}")

        content = skill_md.read_text(encoding='utf-8')
        meta, _ = parse_frontmatter(content)
        name = meta.get("name", path.name)
        self.set_skill(role, name, content)
        return name

    def import_skill_dirs(self, role: str, container_dir: str) -> list:
        """Scan a directory for skill subdirectories and import all of them.

        Each subdirectory that contains a SKILL.md file is imported as a skill.
        Returns a list of imported skill names.
        """
        path = Path(container_dir)
        if not path.is_dir():
            raise FileNotFoundError(f"Directory not found: {container_dir}")

        imported = []
        for child in sorted(path.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.exists():
                skill_md = child / "skill.md"
            if not skill_md.exists():
                continue
            try:
                name = self.import_from_skill_dir(role, str(child))
                imported.append(name)
            except Exception as err:
                print(f"Warning: failed to import skill from {child}: {err}")
        return imported

    def export_to_markdown(self, role: str, name: str, file_path: str) -> None:
        """Export skill from the database to a markdown file."""
        content = self.get_skill(role, name)
        if content is None:
            raise ValueError(f"No skill found for role '{role}' with name '{name}'")

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def export_to_skill_dir(self, role: str, name: str, output_dir: str) -> str:
        """Export a skill from the database as an Agent Skills directory.

        Creates a directory named after the skill (sanitized) with a SKILL.md
        file. If the skill content already has frontmatter, it is preserved;
        otherwise frontmatter is generated from the name and first line.

        Returns the path to the created skill directory.
        """
        content = self.get_skill(role, name)
        if content is None:
            raise ValueError(f"No skill found for role '{role}' with name '{name}'")

        meta, body = parse_frontmatter(content)
        skill_name = meta.get("name", name)
        description = meta.get("description", body.strip().split("\n")[0][:200])

        # If the content already has frontmatter, write it as-is; otherwise
        # generate frontmatter and prepend it to the body.
        if meta:
            skill_content = content
        else:
            skill_content = f"{build_frontmatter(skill_name, description)}\n\n{body}"

        skill_dir_name = re.sub(r"[^a-zA-Z0-9_-]", "-", skill_name).strip("-").lower()
        out_path = Path(output_dir) / skill_dir_name
        out_path.mkdir(parents=True, exist_ok=True)
        (out_path / "SKILL.md").write_text(skill_content, encoding='utf-8')
        return str(out_path)

    def auto_discover(self, role: str, project_dir: str = None) -> list:
        """Scan standard skill directories in the project and import new skills.

        Looks for .skills/, skills/, and .claude/skills/ in the project root.
        Only imports skills that don't already exist in the database (by name).

        Returns a list of newly imported skill names.
        """
        if project_dir is None:
            project_dir = os.getcwd()

        imported = []
        for dir_name in self.SKILL_DIR_NAMES:
            skill_dir = Path(project_dir) / dir_name
            if not skill_dir.is_dir():
                continue
            for child in sorted(skill_dir.iterdir()):
                if not child.is_dir():
                    # Also support loose SKILL.md files directly in the directory
                    if child.name in ("SKILL.md", "skill.md"):
                        try:
                            meta, _ = parse_frontmatter(child.read_text(encoding="utf-8"))
                            name = meta.get("name", dir_name.rstrip("/"))
                            if self.get_skill(role, name) is None:
                                self.import_from_skill_dir(role, str(skill_dir))
                                imported.append(name)
                        except Exception:
                            pass
                    continue
                skill_md = child / "SKILL.md"
                if not skill_md.exists():
                    skill_md = child / "skill.md"
                if not skill_md.exists():
                    continue
                try:
                    content = skill_md.read_text(encoding="utf-8")
                    meta, _ = parse_frontmatter(content)
                    name = meta.get("name", child.name)
                    if self.get_skill(role, name) is None:
                        self.import_from_skill_dir(role, str(child))
                        imported.append(name)
                except Exception as err:
                    print(f"Warning: failed to auto-discover skill from {child}: {err}")
        return imported

    def delete_skill(self, role: str, name: str) -> bool:
        """Delete a skill by role and name. Returns True if a row was deleted."""
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM skills WHERE role = ? AND name = ?
        """, (role, name))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    @staticmethod
    def _extract_summary(content):
        """Extract a skill summary from content.

        If the content has YAML frontmatter with a 'description' field, use
        that (Agent Skills standard). Otherwise fall back to the first line.
        """
        meta, body = parse_frontmatter(content)
        if "description" in meta:
            return str(meta["description"])[:200]
        return body.strip().split("\n")[0][:200]
