THINKING_MODES = {
    1: {"name": "Zen", "max_depth": 1},
    2: {"name": "Serious", "max_depth": 2},
    3: {"name": "Extreme", "max_depth": 4},
    4: {"name": "Feral", "max_depth": 8},
    5: {"name": "Insane", "max_depth": 16},
}

DEFAULT_THINKING_MODE = 1
UNLIMITED_THINKING_MODE = 99


def thinking_mode_name(mode_num):
    if mode_num == UNLIMITED_THINKING_MODE:
        return "Unlimited"
    entry = THINKING_MODES.get(mode_num)
    if entry is None:
        return "Unknown"
    return entry["name"]


def thinking_mode_max_depth(mode_num):
    entry = THINKING_MODES.get(mode_num)
    if entry is None:
        return None
    return entry["max_depth"]


def is_depth_allowed(mode_num, depth):
    max_depth = thinking_mode_max_depth(mode_num)
    if max_depth is None:
        return True
    return depth < max_depth
