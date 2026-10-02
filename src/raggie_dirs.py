"""Central configuration for the raggie per-project data directory name.

All components that read/write the per-project data directory (chat DB,
code index DB, git repo, frontend config, ...) must go through these
helpers instead of hard-coding ".raggie". This lets a single CLI flag
(``--dev``) swap the directory to ".raggie-dev" so a development build of
raggie never touches the production ".raggie" database, avoiding shared-DB
corruption and wiped session history.
"""

from pathlib import Path


_DEFAULT_DIR_NAME = ".raggie"
_DEV_DIR_NAME = ".raggie-dev"

_raggie_dir_name = _DEFAULT_DIR_NAME


def set_raggie_dir_name(name):
    """Override the raggie data directory name (e.g. ".raggie-dev")."""
    global _raggie_dir_name
    _raggie_dir_name = name


def get_raggie_dir_name():
    """Return the configured raggie directory name (".raggie" by default)."""
    return _raggie_dir_name


def is_dev_mode():
    """Return True if the dev data directory (".raggie-dev") is in use."""
    return _raggie_dir_name == _DEV_DIR_NAME


def get_raggie_dir():
    """Return the absolute path to the raggie data dir under cwd."""
    return Path.cwd() / _raggie_dir_name


def get_chat_db_path():
    """Return the path to the chat history SQLite database."""
    return get_raggie_dir() / ".raggie.chat"


def get_code_index_db_path():
    """Return the path to the code index SQLite database."""
    return get_raggie_dir() / ".code_index.raggie"


def get_frontend_config_path(root_dir):
    """Return the path to the frontend config json under root_dir."""
    return Path(root_dir) / _raggie_dir_name / "frontend_config.json"


def enable_dev_mode():
    """Convenience: switch to the ".raggie-dev" data directory."""
    set_raggie_dir_name(_DEV_DIR_NAME)
