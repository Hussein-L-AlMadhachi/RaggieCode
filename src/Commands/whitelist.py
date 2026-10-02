"""Handler for the /whitelist command."""

from Tools.utils import BLUE, DIM, GRAY, GREEN, RED, RESET, YELLOW


def handle(args, agent):
    """Review the shell commands whitelisted for the current role.

    Lists every whitelisted command and lets the user optionally remove
    entries by number, remove all of them, or keep the list unchanged.

    Args:
        args: Extra arguments (unused).
        agent: The Agent instance (used for the current session/role).

    Returns:
        Empty string (fully handled; the agent is not involved).
    """
    import io_backend
    from Agent.chat_history_db import (
        get_command_whitelist,
        get_session_role,
        remove_from_command_whitelist,
    )

    role = get_session_role(agent.session_id) or getattr(agent, "agent_role", None)
    if not role:
        print(f"{RED}No active session or role, cannot resolve the command whitelist.{RESET}")
        return ""

    commands = get_command_whitelist(role)
    if not commands:
        print(f"{YELLOW}No whitelisted shell commands for role '{role}'.{RESET}")
        print(f"{GRAY}Commands get whitelisted when you answer 'always' to a shell{RESET}")
        print(f"{GRAY}execution prompt.{RESET}")
        return ""

    print()
    print(f"{YELLOW}Whitelisted shell commands for role '{role}'{RESET} ({len(commands)}):")
    print()
    for i, command in enumerate(commands, 1):
        print(f"  {GREEN}{i}.{RESET} {DIM}{command}{RESET}")
    print()

    answer = io_backend.ask(
        f"{BLUE}Numbers to remove (comma-separated), 'all', "
        f"or press Enter to keep everything: {RESET}"
    ).strip()

    if not answer:
        print(f"{GRAY}Whitelist unchanged.{RESET}")
        return ""

    if answer.lower() == "all":
        count = 0
        for command in commands:
            if remove_from_command_whitelist(role, command):
                count += 1
        print(f"{GREEN}Removed {count} command(s) from the '{role}' whitelist.{RESET}")
        return ""

    removed_count = 0
    for token in answer.replace(" ", "").split(","):
        if not token.isdigit():
            print(f"  {YELLOW}skipped:{RESET} '{token}' is not a number")
            continue
        idx = int(token)
        if idx < 1 or idx > len(commands):
            print(f"  {YELLOW}skipped:{RESET} '{token}' is out of range")
            continue
        command = commands[idx - 1]
        if remove_from_command_whitelist(role, command):
            print(f"{GREEN}  removed:{RESET} {command}")
            removed_count += 1
        else:
            print(f"  {RED}not found:{RESET} {command}")

    if removed_count:
        print(f"{GREEN}Removed {removed_count} command(s) from the '{role}' whitelist.{RESET}")
    else:
        print(f"{GRAY}Whitelist unchanged.{RESET}")
    return ""
