"""
Add toolcall_id and cancel_reason to todo_tasks table.

Originally these columns were added inline in init_db() via PRAGMA table_info
checks. This migration replicates that logic as a proper migration file.

Idempotent: checks if each column already exists before adding it, so it's
safe to run on databases that already had the inline migration applied.
"""


def migrate(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(todo_tasks)")]
    if "toolcall_id" not in cols:
        conn.execute("ALTER TABLE todo_tasks ADD COLUMN toolcall_id TEXT")
    if "cancel_reason" not in cols:
        conn.execute("ALTER TABLE todo_tasks ADD COLUMN cancel_reason TEXT")


step(migrate)
