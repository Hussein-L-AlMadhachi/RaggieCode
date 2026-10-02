"""
Migrate skills table from old schema to new schema.

The old skills table had role as the PRIMARY KEY and no name column. The new
schema has an autoincrement id, a name column, and UNIQUE(role, name).

Originally this was done inline in init_db() with a table rename + data copy.
This migration replicates that logic as a proper migration file.

Idempotent: checks if the name column already exists before doing the rename,
so it's safe to run on databases that already had the inline migration applied.
"""


def migrate(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(skills)")]
    if "name" not in cols and "role" in cols:
        conn.execute("ALTER TABLE skills RENAME TO skills_old")
        conn.execute(
            """
            CREATE TABLE skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                name TEXT NOT NULL,
                content TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(role, name)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO skills (role, name, content, updated_at)
            SELECT role, role, content, updated_at FROM skills_old
            """
        )
        conn.execute("DROP TABLE skills_old")


step(migrate)
