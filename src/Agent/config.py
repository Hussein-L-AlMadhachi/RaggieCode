import json
import shutil
from pathlib import Path

# The user's config directory (~/.config/raggie)
USER_CONFIG_DIR = Path.home() / ".config" / "raggie"

# The default config directory in the source code
DEFAULT_CONFIG_DIR = Path(__file__).parent.parent / "config"

def ensure_config_exists(filename):
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    user_file = USER_CONFIG_DIR / filename

    # If the user doesn't have the config file yet, copy it from the defaults
    if not user_file.exists():
        default_file = DEFAULT_CONFIG_DIR / filename
        if default_file.exists():
            shutil.copy2(default_file, user_file)
        else:
            # Fallback if somehow the default doesn't exist
            user_file.write_text("{}")

    return user_file


# --- Schema version tracking + migrations ---

_META_FILE = USER_CONFIG_DIR / "_meta.json"


def _load_meta():
    """Load the config metadata file (schema version, etc.)."""
    if _META_FILE.exists():
        try:
            with open(_META_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_meta(meta):
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_META_FILE, "w") as f:
        json.dump(meta, f, indent=2)


def get_schema_version():
    """Current schema version recorded for the user's config dir."""
    return _load_meta().get("schema_version", 1)


def run_migrations(dry_run=False):
    """Apply pending config migrations iteratively.

    Returns a list of ``(from_version, to_version, description)`` tuples for
    each migration step that was (or would be) applied. When ``dry_run`` is
    True, files and the meta file are left untouched.

    Only config files that already exist in the user's config dir are loaded
    before migrations run. Migrations may introduce new files by adding keys
    to the ``configs`` dict; those new files are persisted alongside existing
    ones.
    """
    from Agent.migrations import MIGRATIONS, LATEST_VERSION, CONFIG_FILES

    current = get_schema_version()
    if current >= LATEST_VERSION:
        return []

    # Load only files that already exist   do NOT pre-create. Migrations are
    # responsible for introducing new config files.
    paths = {}
    configs = {}
    for fname in CONFIG_FILES:
        user_file = USER_CONFIG_DIR / fname
        if user_file.exists():
            paths[fname] = user_file
            try:
                with open(user_file, "r") as f:
                    configs[fname] = json.load(f)
            except (json.JSONDecodeError, OSError):
                configs[fname] = {}

    applied = []
    version = current
    # Iterative loop   NEVER recursive.
    while version < LATEST_VERSION:
        target = version + 1
        migrate_fn = MIGRATIONS.get(target)
        if migrate_fn is None:
            # No migration registered for this step; bump version with a no-op.
            applied.append((version, target, "no migration registered"))
            version = target
            continue
        configs = migrate_fn(configs)
        desc = (migrate_fn.__doc__ or migrate_fn.__name__).strip().splitlines()[0]
        applied.append((version, target, desc))
        version = target

    if dry_run or not applied:
        return applied

    # Persist migrated configs (including new files introduced by migrations)
    # and update the recorded schema version.
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for fname, data in configs.items():
        with open(USER_CONFIG_DIR / fname, "w") as f:
            json.dump(data, f, indent=2)
    meta = _load_meta()
    meta["schema_version"] = LATEST_VERSION
    _save_meta(meta)
    return applied


def init_config():
    """Ensure base config files exist and run any pending migrations.

    Only the base (v1) config files are pre-created via ``ensure_config_exists``.
    Newer config files (e.g. mcp_servers.json) are introduced by migrations,
    not pre-created here, so the migration is the single source of truth for
    when a file enters the config set.

    Intended to be called once at startup so users automatically get
    up-to-date config schemas after upgrading raggie.
    """
    from Agent.migrations import BASE_CONFIG_FILES

    for fname in BASE_CONFIG_FILES:
        ensure_config_exists(fname)
    run_migrations()

def load_roles():
    config_file = ensure_config_exists("roles.json")
    with open(config_file, "r") as f:
        return json.load(f)


def save_roles(roles: dict):
    """Save roles dict to the user's roles.json file."""
    config_file = ensure_config_exists("roles.json")
    with open(config_file, "w") as f:
        json.dump(roles, f, indent=4)

def load_tools():
    config_file = ensure_config_exists("tools.json")
    with open(config_file, "r") as f:
        return json.load(f)

def load_keys():
    config_file = ensure_config_exists("keys.json")
    with open(config_file, "r") as f:
        return json.load(f)


def load_mcp_servers():
    config_file = ensure_config_exists("mcp_servers.json")
    with open(config_file, "r") as f:
        return json.load(f)


def save_mcp_servers(servers: dict):
    """Save MCP servers dict to the user's mcp_servers.json file."""
    config_file = ensure_config_exists("mcp_servers.json")
    with open(config_file, "w") as f:
        json.dump(servers, f, indent=2)
