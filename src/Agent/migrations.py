"""Config schema migrations.

Each migration function takes a ``configs`` dict mapping config filename to
its parsed JSON data and returns the updated dict. Migrations are applied
iteratively from the current schema version up to the
latest version recorded in ``MIGRATIONS``.

To ship a config schema change:
  1. Bump the target version number (e.g. add key ``3`` below).
  2. Write a ``migrate_vN`` function that transforms ``configs`` from
     version N-1 to N.
  3. Register it in ``MIGRATIONS``.

The schema version for a user's config dir is stored in
``~/.config/raggie/_meta.json`` under the ``schema_version`` key.
"""

import json
import shutil
from pathlib import Path

# Config files that existed at schema version 1 (the original raggie config set).
# These are ensured to exist before migrations run.
BASE_CONFIG_FILES = ["roles.json", "tools.json", "keys.json"]

# All config files known at the latest schema version. Migrations may
# introduce new files beyond the base set (e.g. mcp_servers.json at v2).
CONFIG_FILES = BASE_CONFIG_FILES + ["mcp_servers.json"]

_DEFAULT_CONFIG_DIR = Path(__file__).parent.parent / "config"


def _load_default(filename):
    """Load a default config file from src/config/, returning {} if missing."""
    default = _DEFAULT_CONFIG_DIR / filename
    if default.exists():
        try:
            with open(default, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def migrate_v2(configs):
    """v1 -> v2: introduce mcp_servers.json for MCP server configuration.

    Users upgrading from v1 (which had no mcp_servers.json) get the default
    file created. Users who somehow already have one are left alone.
    """
    if "mcp_servers.json" not in configs:
        configs["mcp_servers.json"] = _load_default("mcp_servers.json")
    return configs


_OLD_TOOL_NAME = "UglyWholeFileContentDump"
_NEW_TOOL_NAME = "WholeFileContentDump"


def migrate_v3(configs):
    """v2 -> v3: rename UglyWholeFileContentDump to WholeFileContentDump.

    Updates tool references in tools.json (top-level key + inner "name" field)
    and roles.json (tool lists per role) so existing users keep working after
    the tool was renamed.
    """
    # --- tools.json ---
    tools = configs.get("tools.json")
    if tools and isinstance(tools, dict):
        # Rename top-level key
        if _OLD_TOOL_NAME in tools:
            entry = tools.pop(_OLD_TOOL_NAME)
            # Also fix the inner "function.name" if present
            fn = entry.get("function") if isinstance(entry, dict) else None
            if isinstance(fn, dict) and fn.get("name") == _OLD_TOOL_NAME:
                fn["name"] = _NEW_TOOL_NAME
            tools[_NEW_TOOL_NAME] = entry
        # Fix any inner "name" field even if top-level key was already renamed
        for entry in tools.values():
            if isinstance(entry, dict):
                fn = entry.get("function")
                if isinstance(fn, dict) and fn.get("name") == _OLD_TOOL_NAME:
                    fn["name"] = _NEW_TOOL_NAME

    # --- roles.json ---
    roles = configs.get("roles.json")
    if roles and isinstance(roles, dict):
        for role in roles.values():
            if not isinstance(role, dict):
                continue
            tool_list = role.get("tools")
            if not isinstance(tool_list, list):
                continue
            role["tools"] = [
                _NEW_TOOL_NAME if t == _OLD_TOOL_NAME else t
                for t in tool_list
            ]

    return configs


def migrate_v4(configs):
    """v3 -> v4: add a ``provider`` field to each role in roles.json.

    The provider field identifies which LLM API the role targets
    ("deepseek", "z.ai", "openai", "grok", "qwen") so raggie can apply
    provider-specific request quirks (e.g. DeepSeek requiring
    reasoning_content to be passed back). If the role already has a
    non-empty provider it is left alone; otherwise it is inferred from
    the base_url and set to "" when inference fails.
    """
    from Agent.providers import infer_provider

    roles = configs.get("roles.json")
    if roles and isinstance(roles, dict):
        for role in roles.values():
            if not isinstance(role, dict):
                continue
            if role.get("provider"):
                continue
            base_url = role.get("base_url", "")
            role["provider"] = infer_provider(base_url)
    return configs


def migrate_v5(configs):
    """v4 -> v5: add a ``reasoning_effort`` field to each role in roles.json.

    The reasoning_effort field controls the reasoning depth for providers
    that support it (e.g. "low", "medium", "high"). Empty string means
    "use the provider's default". Existing roles get "" so behavior is
    unchanged unless the user explicitly sets a value.
    """
    roles = configs.get("roles.json")
    if roles and isinstance(roles, dict):
        for role in roles.values():
            if not isinstance(role, dict):
                continue
            if not role.get("reasoning_effort"):
                role["reasoning_effort"] = ""
    return configs


def migrate_v6(configs):
    """v5 -> v6: ensure every role has a non-empty ``provider`` field.

    Provider is now the mandatory field that drives API behavior; base_url is
    optional and falls back to the provider's default URL. For roles that
    still have an empty provider (e.g. created before v4 or with an
    unrecognized base_url), infer it from base_url one more time. Roles that
    already have a provider set are left alone.
    """
    from Agent.providers import infer_provider

    roles = configs.get("roles.json")
    if roles and isinstance(roles, dict):
        for role in roles.values():
            if not isinstance(role, dict):
                continue
            if role.get("provider"):
                continue
            base_url = role.get("base_url", "")
            role["provider"] = infer_provider(base_url)
    return configs


def migrate_v7(configs):
    """v6 -> v7: migrate keys.json from {base_url: key} to {provider:base_url: key}.

    The new format lets users store multiple keys for the same provider with
    different base URLs (e.g. self-hosted in different places). Each old key
    (a bare base_url) is converted to "provider:base_url" using infer_provider
    on the base_url. Keys already in the new format (parse_key_id returns a
    known provider) are left alone.
    """
    from Agent.providers import infer_provider, make_key_id, parse_key_id

    keys = configs.get("keys.json")
    if keys and isinstance(keys, dict):
        new_keys = {}
        for key_id, api_key in keys.items():
            # Skip entries already in "provider:base_url" format.
            provider, base_url = parse_key_id(key_id)
            if provider:
                new_keys[key_id] = api_key
                continue
            # Legacy format: key_id is a bare base_url.
            provider = infer_provider(base_url)
            if provider:
                new_keys[make_key_id(provider, base_url)] = api_key
            else:
                # Unknown provider   keep the bare URL so the user can fix it.
                new_keys[key_id] = api_key
        configs["keys.json"] = new_keys
    return configs


def migrate_v8(configs):
    """v7 -> v8: update Shell tool description to document the exit_code field.

    The Shell tool now returns an 'exit_code' field in its response (0 on
    success, non-zero on failure, null when the command didn't run). This
    migration updates the tool description in tools.json so existing users
    see the new documentation.
    """
    tools = configs.get("tools.json")
    if tools and isinstance(tools, dict):
        shell = tools.get("Shell")
        if shell and isinstance(shell, dict):
            fn = shell.get("function")
            if isinstance(fn, dict):
                fn["description"] = (
                    "Execute a shell command. Response includes 'exit_code' "
                    "(0=success, non-zero=failure, null=not run). Timeout default "
                    "30s. NEVER use to write/edit files (use WriteFile/ReplaceText). "
                    "NEVER read gitignored files. For long-running commands use "
                    "TempBackgroundService."
                )
    return configs


def migrate_v9(configs):
    """v8 -> v9: rename UglyWholeFileContentDump everywhere in user config.

    The tool rename in v3 only covered the tool key, the inner function name
    and role tool lists; stale references survived in two other places:

    1. Markdown system prompt files in the user config dir (e.g.
       coder_system_prompt.md), causing the agent to keep emitting the old
       name. Those files are rewritten in place (they are not part of the
       JSON configs dict).
    2. The "description" strings of other tools in tools.json (e.g. the
       GetFileCodeSemantics description telling the model to use the dump
       tool first).

    Idempotent: files/fields without the old name are left untouched.
    """
    from Agent.config import USER_CONFIG_DIR

    # --- tools.json descriptions ---
    tools = configs.get("tools.json")
    if tools and isinstance(tools, dict):
        for entry in tools.values():
            if not isinstance(entry, dict):
                continue
            fn = entry.get("function")
            if isinstance(fn, dict) and isinstance(fn.get("description"), str):
                if _OLD_TOOL_NAME in fn["description"]:
                    fn["description"] = fn["description"].replace(
                        _OLD_TOOL_NAME, _NEW_TOOL_NAME
                    )

    # --- markdown prompt files (touched on disk, not via configs) ---
    if USER_CONFIG_DIR.exists():
        for md_file in USER_CONFIG_DIR.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
            except OSError:
                continue
            if _OLD_TOOL_NAME not in content:
                continue
            try:
                md_file.write_text(
                    content.replace(_OLD_TOOL_NAME, _NEW_TOOL_NAME),
                    encoding="utf-8",
                )
            except OSError:
                continue
    return configs


# Registry: target version -> function that migrates FROM (version-1) TO version.
# Keys must be contiguous integers starting at 2 (version 1 is the initial
# schema shipped by ensure_config_exists copying the defaults).
def migrate_v10(configs):
    """v9 -> v10: document ViewChanges diff pagination in tools.json.

    The diff view is now paginated via 'page' and 'files_per_page' so a huge
    change set can never overflow the model's context window in a single
    tool result. This migration updates the ViewChanges entry (description
    plus the new parameters) in the user's tools.json copy.
    """
    tools = configs.get("tools.json")
    if tools and isinstance(tools, dict):
        vc = tools.get("ViewChanges")
        if vc and isinstance(vc, dict):
            fn = vc.get("function")
            if isinstance(fn, dict):
                fn["description"] = (
                    "View changes tracked by the built-in git repository "
                    "(.raggie/git/). Supports three view_type modes: 'status' "
                    "(list added/modified/deleted files since last commit), "
                    "'diff' (show the actual file diffs/content, paginated), "
                    "'log' (show commit history). For 'status', optionally "
                    "filter by 'category' to see only one type of change. For "
                    "'diff', results are paginated: 'page' (1-based) and "
                    "'files_per_page' (default 25) select which slice of "
                    "changed files to show   the response reports the total "
                    "page count and tells you the next page to request. "
                    "Optionally set 'max_diff_lines' to limit lines per file "
                    "(default 500). Optionally filter by 'path' to narrow "
                    "results to specific files. Use this to review what has "
                    "changed before or after commits, or to understand the "
                    "commit history."
                )
                props = fn.get("parameters", {}).get("properties")
                if isinstance(props, dict):
                    props["page"] = {
                        "type": "integer",
                        "description": (
                            "For view_type='diff': 1-based page of changed "
                            "files to show (default: 1). The response reports "
                            "the total number of pages; request page+1 for "
                            "the next slice."
                        ),
                    }
                    props["files_per_page"] = {
                        "type": "integer",
                        "description": (
                            "For view_type='diff': how many changed files per "
                            "page (default: 25). Lower this when individual "
                            "diffs are very large."
                        ),
                    }
    return configs


def migrate_v11(configs):
    """v10 -> v11: add an optional ``user_agent`` field to each role in roles.json.

    The user_agent field overrides the default ``raggie/<version>`` User-Agent
    header sent to all providers. Empty string means "use the default".
    Existing roles get "" so behavior is unchanged unless the user explicitly
    sets a value.
    """
    roles = configs.get("roles.json")
    if roles and isinstance(roles, dict):
        for role in roles.values():
            if not isinstance(role, dict):
                continue
            if not role.get("user_agent"):
                role["user_agent"] = ""
    return configs


def migrate_v12(configs):
    """v11 -> v12: per-tool indexing flags + per-role indexing switch.

    tools.json entries get an "indexing" boolean copied from the default
    tools.json (True only for the index-driven tools, False otherwise; any
    tool unknown to the defaults gets False). roles.json roles that predate
    the switch get "indexing": True, while an explicit False is preserved.
    The bundled coder_system_prompt.md is refreshed on disk so the updated
    prompt ships to existing users.
    """
    # --- tools.json: per-tool indexing flags ---
    tools = configs.get("tools.json")
    if tools and isinstance(tools, dict):
        defaults = _load_default("tools.json")
        for name, entry in tools.items():
            if not isinstance(entry, dict):
                continue
            default_entry = defaults.get(name) if isinstance(defaults, dict) else None
            if isinstance(default_entry, dict):
                entry["indexing"] = bool(default_entry.get("indexing", False))
            else:
                entry["indexing"] = False

    # --- roles.json: per-role indexing switch ---
    roles = configs.get("roles.json")
    if roles and isinstance(roles, dict):
        for role in roles.values():
            if not isinstance(role, dict):
                continue
            if "indexing" not in role:
                role["indexing"] = True

    # --- refresh the bundled system prompt (on disk, not in configs) ---
    from Agent.config import USER_CONFIG_DIR

    default_prompt = _DEFAULT_CONFIG_DIR / "coder_system_prompt.md"
    if default_prompt.exists() and USER_CONFIG_DIR.exists():
        try:
            shutil.copy2(default_prompt, USER_CONFIG_DIR / "coder_system_prompt.md")
        except OSError:
            pass
    return configs


MIGRATIONS = {
    2: migrate_v2,
    3: migrate_v3,
    4: migrate_v4,
    5: migrate_v5,
    6: migrate_v6,
    7: migrate_v7,
    8: migrate_v8,
    9: migrate_v9,
    10: migrate_v10,
    11: migrate_v11,
    12: migrate_v12,
}

# Latest schema version. Derived from the registry so it stays in sync.
LATEST_VERSION = max(MIGRATIONS) if MIGRATIONS else 1
