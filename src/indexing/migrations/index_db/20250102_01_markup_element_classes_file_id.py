"""
Migrate markup_element_classes: add file_id column, ensure indexes, backfill.

The markup_element_classes table originally lacked a denormalized file_id
column. The new schema includes it so scoped matching can probe by
(file_id, class_name) directly.

Idempotent: checks if the column exists, drops and recreates only if needed.
Always ensures the indexes exist (they're skipped in the baseline migration
because the table might not have file_id yet). Safe to run on databases that
already had this migration applied.
"""


def migrate(conn):
    # Check if the table exists at all
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='markup_element_classes'"
    ).fetchone()
    if not table_exists:
        # Create it with the correct shape
        conn.execute(
            """
            CREATE TABLE markup_element_classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                element_id INTEGER NOT NULL,
                file_id INTEGER NOT NULL,
                class_name TEXT NOT NULL,
                FOREIGN KEY (element_id) REFERENCES markup_elements(id) ON DELETE CASCADE,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
            )
            """
        )
    else:
        # Check if file_id column is missing   if so, drop and recreate
        cols = {r[1] for r in conn.execute("PRAGMA table_info(markup_element_classes)")}
        if "file_id" not in cols:
            conn.execute("DROP TABLE markup_element_classes")
            conn.execute(
                """
                CREATE TABLE markup_element_classes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    element_id INTEGER NOT NULL,
                    file_id INTEGER NOT NULL,
                    class_name TEXT NOT NULL,
                    FOREIGN KEY (element_id) REFERENCES markup_elements(id) ON DELETE CASCADE,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
                )
                """
            )

    # Always ensure indexes exist (skipped in baseline because table shape
    # might not have been correct yet)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_markup_element_classes_element_id "
        "ON markup_element_classes(element_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_markup_element_classes_file_class "
        "ON markup_element_classes(file_id, class_name)"
    )

    # Backfill if empty
    count = conn.execute("SELECT COUNT(*) FROM markup_element_classes").fetchone()[0]
    if count == 0:
        conn.execute(
            """
            INSERT INTO markup_element_classes (element_id, file_id, class_name)
            SELECT me.id, me.file_id, je.value
            FROM markup_elements me, json_each(me.static_classes) je
            WHERE json_valid(me.static_classes)
              AND json_type(me.static_classes) = 'array'
            """
        )


step(migrate)
