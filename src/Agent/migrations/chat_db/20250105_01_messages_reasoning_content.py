"""
Add a reasoning_content column to the messages table.

Providers like DeepSeek return a ``reasoning_content`` field on assistant
messages in thinking mode and require it to be passed back in subsequent
requests. Persisting it lets raggie replay the full conversation correctly.

Idempotent: checks if the column already exists before adding it.
"""


def migrate(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)")]
    if "reasoning_content" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN reasoning_content TEXT")


step(migrate)
