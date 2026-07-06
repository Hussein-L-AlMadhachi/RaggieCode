import sqlite3
from pathlib import Path
from typing import Optional
from Agent.chat_history_db import DB_PATH


class SkillManager:
    """Manages role-specific skills stored in the database."""
    
    def __init__(self):
        """Initialize the skill manager."""
        # No directory creation needed since DB_PATH is the file itself
    
    def get_skill(self, role: str, name: str) -> Optional[str]:
        """Load a specific skill for a role by name from the database."""
        conn = sqlite3.connect(DB_PATH)
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
        conn = sqlite3.connect(DB_PATH)
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
            summary = content.strip().split("\n")[0][:200]
            skills.append({"role": role, "name": name, "summary": summary})
        
        conn.close()
        return skills

    def list_skills(self) -> list:
        """Return all skills with brief summaries (role + name + first ~200 chars of content)."""
        conn = sqlite3.connect(DB_PATH)
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
            summary = content.strip().split("\n")[0][:200]
            skills.append({"role": role, "name": name, "summary": summary})
        
        conn.close()
        return skills
    
    def set_skill(self, role: str, name: str, content: str) -> None:
        """Save a skill for a specific role with a given name to the database."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO skills (role, name, content, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(role, name) DO UPDATE SET content = excluded.content, updated_at = CURRENT_TIMESTAMP
        """, (role, name, content))
        
        conn.commit()
        conn.close()
    
    def import_from_markdown(self, role: str, name: str, file_path: str) -> None:
        """Load skill from a markdown file into the database."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Skill file not found: {file_path}")
        
        content = path.read_text(encoding='utf-8')
        self.set_skill(role, name, content)
    
    def export_to_markdown(self, role: str, name: str, file_path: str) -> None:
        """Export skill from the database to a markdown file."""
        content = self.get_skill(role, name)
        if content is None:
            raise ValueError(f"No skill found for role '{role}' with name '{name}'")
        
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def delete_skill(self, role: str, name: str) -> bool:
        """Delete a skill by role and name. Returns True if a row was deleted."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM skills WHERE role = ? AND name = ?
        """, (role, name))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
