"""
Add redirect_session_id, toolcall_id, effort, depth to sessions table.

Originally these columns were added inline in init_db() via PRAGMA table_info
checks. This migration replicates that logic as a proper migration file.

Idempotent: checks if each column already exists before adding it, so it's
safe to run on databases that already had the inline migration applied.
"""


def migrate(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)")]
    if "redirect_session_id" not in cols:
        conn.execute(
            "ALTER TABLE sessions ADD COLUMN redirect_session_id INTEGER "
            "REFERENCES sessions(id) ON DELETE SET NULL"
        )
    if "toolcall_id" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN toolcall_id TEXT")
    if "effort" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN effort INTEGER")
    if "depth" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN depth INTEGER DEFAULT 0")


step(migrate)
