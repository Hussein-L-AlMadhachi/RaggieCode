"""
Create the command_whitelist table.

Stores per-role shell commands that the user has explicitly approved for
auto-execution (no confirmation prompt). Matches are exact full-command
strings   the user adds ``git status`` to auto-approve exactly that, not
``git push``.

Idempotent: uses CREATE TABLE IF NOT EXISTS.
"""

step("""
    CREATE TABLE IF NOT EXISTS command_whitelist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL,
        command TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(role, command)
    )
""")
