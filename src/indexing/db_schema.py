"""
SQLite database initialization for code index.

Schema is defined in migration files under src/indexing/migrations/index_db/.
"""
from pathlib import Path

from db_migrations import run_yoyo_migrations

INDEX_DB_MIGRATIONS_DIR = str(Path(__file__).parent / "migrations" / "index_db")


def init_database(db_path):
    """Initialize the database via yoyo migrations."""
    import sqlite3
    run_yoyo_migrations(db_path, INDEX_DB_MIGRATIONS_DIR)
    conn = sqlite3.connect(db_path, timeout=30)
    return conn
