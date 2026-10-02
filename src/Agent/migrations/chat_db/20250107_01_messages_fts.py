"""
Add full-text search over chat messages using SQLite FTS5.

Creates an external-content FTS5 virtual table indexed on the ``content``
column of ``messages`` and keeps it in sync with triggers. Existing rows
are backfilled on migration. Searching filters to user messages at query
time (the API layer adds ``role = 'user'``).

Idempotent: uses IF NOT EXISTS / trigger guards.
"""

step("""
    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
        content,
        content='messages',
        content_rowid='id'
    )
""")

step("""
    CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
    END
""")

step("""
    CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, content)
        VALUES ('delete', old.id, old.content);
    END
""")

step("""
    CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, content)
        VALUES ('delete', old.id, old.content);
        INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
    END
""")

# Backfill any messages that existed before this migration.
step("""
    INSERT INTO messages_fts(rowid, content)
    SELECT m.id, m.content FROM messages m
    WHERE m.id NOT IN (SELECT rowid FROM messages_fts)
""")
