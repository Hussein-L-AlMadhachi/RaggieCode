EFFORT_LEVELS = {
    1: {"name": "Zen", "max_depth": 1},
    2: {"name": "Serious", "max_depth": 2},
    3: {"name": "Extreme", "max_depth": 4},
    4: {"name": "Feral", "max_depth": 8},
    5: {"name": "Insane", "max_depth": 16},
}

DEFAULT_EFFORT = 1
UNLIMITED_EFFORT = 99


def effort_name(effort_num):
    if effort_num == UNLIMITED_EFFORT:
        return "Unlimited"
    entry = EFFORT_LEVELS.get(effort_num)
    if entry is None:
        return "Unknown"
    return entry["name"]


def effort_max_depth(effort_num):
    entry = EFFORT_LEVELS.get(effort_num)
    if entry is None:
        return None
    return entry["max_depth"]


def is_depth_allowed(effort_num, depth):
    max_depth = effort_max_depth(effort_num)
    if max_depth is None:
        return True
    return depth < max_depth
