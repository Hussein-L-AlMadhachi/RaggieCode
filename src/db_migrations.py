"""Database migration helpers using yoyo-migrations.

yoyo tracks applied migrations in a ``_yoyo_migration`` table inside each DB.
Migration files live in directories (one per DB) and are named with a
timestamp prefix, e.g. ``20250101_01_initial.py``.

Each migration file calls ``step()`` with SQL strings:

    step("ALTER TABLE foo ADD COLUMN bar TEXT")

To apply migrations programmatically, call ``run_yoyo_migrations(db_path,
migrations_dir)``. It reads all migration files from the directory, figures
out which ones haven't been applied yet, and applies them in order.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from yoyo import get_backend, read_migrations

# Python 3.12 deprecated the default datetime adapter for sqlite3. yoyo passes
# datetime objects internally, which triggers the warning. Register a custom
# adapter so the deprecated default is never used.
sqlite3.register_adapter(datetime, lambda dt: dt.isoformat())


def run_yoyo_migrations(db_path, migrations_dir):
    """Apply pending yoyo migrations to a SQLite database.

    Args:
        db_path: path to the .db file (string or Path).
        migrations_dir: path to the directory containing migration .py files.

    Does nothing if the migrations directory is empty or doesn't exist.
    """
    migrations_dir = Path(migrations_dir)
    if not migrations_dir.exists() or not any(migrations_dir.glob("*.py")):
        return []

    # Resolve to an absolute path so yoyo always opens the same file regardless
    # of what the cwd was when the path was passed.
    db_path = Path(db_path).resolve()
    db_uri = f"sqlite:///{db_path}"
    backend = get_backend(db_uri)
    try:
        migrations = read_migrations(str(migrations_dir))
        pending = backend.to_apply(migrations)
        if not pending:
            return []
        backend.apply_migrations(pending)
        return [str(m) for m in pending]
    finally:
        backend.connection.close()
