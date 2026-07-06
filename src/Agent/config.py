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
