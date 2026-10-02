"""
Backfill style_selector_parts from compound selectors.

The style_selector_parts table normalizes compound CSS selectors into one row
per class/id/tag part so compound matching can run as relational division in
SQL. Originally this was backfilled inline in migrate_database().

This migration replicates that logic as a proper migration file.

Idempotent: if the table already has rows, it's a no-op. Safe to run on
databases that already had the inline migration applied.
"""


def migrate(conn):
    # Check if the table exists
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='style_selector_parts'"
    ).fetchone()
    if not table_exists:
        return  # baseline migration will have created it

    count = conn.execute("SELECT COUNT(*) FROM style_selector_parts").fetchone()[0]
    if count > 0:
        return

    from indexing.frontend.css_selector_utils import split_selector_parts

    rows = conn.execute(
        "SELECT id, selector_text FROM style_selectors WHERE selector_type = 'compound'"
    ).fetchall()

    parts = []
    for sel_id, sel_text in rows:
        for part_type, part_value in split_selector_parts(sel_text):
            parts.append((sel_id, part_type, part_value))

    if parts:
        conn.executemany(
            "INSERT INTO style_selector_parts (selector_id, part_type, part_value) VALUES (?, ?, ?)",
            parts,
        )


step(migrate)
