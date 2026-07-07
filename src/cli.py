import argparse
import sys

KNOWN_COMMANDS = {"skill", "roles", "keys", "setup"}


def _create_agent_parser():
    """Parser for the default agent mode: raggie <role> <project-dir>."""
    parser = argparse.ArgumentParser(
        prog="raggie",
        description="Raggie - AI Coding Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""commands:
  raggie <role> <project-dir>   Run the AI agent (e.g. raggie code .)
  raggie skill <role> ...       Manage agent skills
  raggie roles                  List and edit agent roles
  raggie keys                   Manage API keys
  raggie setup                  First-time setup (keys + roles)

examples:
  raggie code .                                   # interactive mode in current dir
  raggie code /path/to/project                    # interactive mode in a project
  raggie code . --prompt "Write a hello function" # single prompt
  raggie code /tmp/new-project                    # creates dir if missing
  raggie skill code --show                        # list all skills for role
  raggie skill code --show --name testing         # show a specific skill
  raggie skill code --import-skill skills.md --name testing  # import from file
  raggie skill code --delete --name testing       # delete a skill
  raggie skill --list-all                        # list all skills across all roles
        """
    )
    parser.add_argument("--version", action="version", version=f"raggie v{__import__('importlib.metadata').metadata.version('raggiecode')}")
    parser.add_argument("role", nargs="?", help="The agent role to use (defined in roles.json)")
    parser.add_argument("project_dir", nargs="?", default=".", help="Path to the project directory (use '.' for current directory)")
    parser.add_argument("--prompt", help="The initial prompt for the agent (if not provided, runs in interactive mode)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode to display tool call outputs")
    return parser


def _create_subcommand_parser():
    """Parser for subcommands: skill, roles, keys."""
    parser = argparse.ArgumentParser(
        description="Raggie - AI Coding Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"raggie v{__import__('importlib.metadata').metadata.version('raggiecode')}")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Skill command
    skill_parser = subparsers.add_parser(
        "skill",
        help="Manage agent skills",
        description="Manage named skills stored in the database. A role can have multiple skills, each identified by a unique name.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  raggie skill code --show                              # list all skills for role 'code'
  raggie skill code --show --name testing               # show full content of a specific skill
  raggie skill code --import-skill my-skill.md --name testing   # import from file
  raggie skill code --export-skill backup.md --name testing     # export to file
  raggie skill code --delete --name testing             # delete a skill
  raggie skill --list-all                               # list all skills across all roles
        """
    )
    skill_parser.add_argument("role", nargs="?", help="The agent role (required unless using --list-all)")
    skill_parser.add_argument("--name", help="The skill name (required for --import-skill, --export-skill, --delete)")
    skill_parser.add_argument("--import-skill", metavar="FILE", help="Import skill from markdown file into the database (requires --name)")
    skill_parser.add_argument("--export-skill", metavar="FILE", help="Export skill from database to markdown file (requires --name)")
    skill_parser.add_argument("--show", action="store_true", help="Display skill(s) for the role (all if --name omitted)")
    skill_parser.add_argument("--delete", action="store_true", help="Delete a skill (requires --name)")
    skill_parser.add_argument("--list-all", action="store_true", help="List all skills across all roles")

    # Roles command
    subparsers.add_parser(
        "roles",
        help="List and edit agent roles",
        description="List all agent roles and interactively edit their base URL and model settings.",
    )

    # Keys command
    subparsers.add_parser(
        "keys",
        help="Manage API keys",
        description="Interactive interface to list, add, and remove API keys stored in keys.json.",
    )

    # Setup command
    subparsers.add_parser(
        "setup",
        help="First-time setup wizard",
        description="Guided first-time setup: configure API keys, then review agent roles.",
    )

    return parser


def parse_args():
    """Parse command-line arguments and return the parsed args."""
    if len(sys.argv) > 1 and sys.argv[1] in KNOWN_COMMANDS:
        parser = _create_subcommand_parser()
    else:
        parser = _create_agent_parser()

    args = parser.parse_args()

    if getattr(args, "command", None) is None and getattr(args, "role", None) is None:
        parser.print_help()
        sys.exit(1)

    return args
