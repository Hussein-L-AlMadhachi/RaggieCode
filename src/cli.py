import argparse
import sys

KNOWN_COMMANDS = {"skill", "roles", "keys", "setup", "mcp", "config"}


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
  raggie code --web                               # serve the web UI in the current dir
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
    parser.add_argument("--effort", "--thinking-mode", dest="thinking_mode", type=int, choices=[1, 2, 3, 4, 5], help="Thinking mode: 1=zen, 2=serious, 3=extreme, 4=feral, 5=insane (you can also use names in /thinkingMode)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode to display tool call outputs")
    parser.add_argument("--acp-stdio", action="store_true", help="Run as an ACP (Agent Client Protocol) agent over stdio (for editors like Zed)")
    parser.add_argument("--acp-http", action="store_true", help="Run as an ACP agent over HTTP (JSON-RPC POST + SSE streaming)")
    parser.add_argument("--acp-port", type=int, default=8765, help="Port for --acp-http (default: 8765)")
    parser.add_argument("--acp-auto-approve", action="store_true", help="Auto-approve permission requests in ACP mode (required for HTTP mode, which has no interactive client)")
    parser.add_argument("--web", action="store_true", help="Serve the built-in web UI rooted at the current directory (default port: 8765, see --acp-port)")
    parser.add_argument("--dev", action="store_true", help="Use a separate .raggie-dev data directory instead of .raggie, so a dev build never touches or wipes the production database, session history, or memory")
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
    skill_parser.add_argument("--import-skill-dir", metavar="DIR", help="Import an Agent Skills directory (folder with SKILL.md) or a container of skill folders")
    skill_parser.add_argument("--export-skill-dir", metavar="DIR", help="Export a skill as an Agent Skills directory (requires --name)")
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

    # MCP command
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Manage MCP servers",
        description=(
            "Manage external MCP (Model Context Protocol) servers. Supports both "
            "the 2026-07-28 revision (MCP 2.0, stateless) and earlier 2025-era "
            "stateful servers, over stdio and Streamable HTTP.\n\n"
            "Examples:\n"
            "  raggie mcp --list                       # list configured servers\n"
            "  raggie mcp --add local-files --cmd npx --args -y @modelcontextprotocol/server-filesystem /tmp\n"
            "  raggie mcp --add remote --url https://example.com/mcp --trust\n"
            "  raggie mcp --remove local-files         # remove a server\n"
            "  raggie mcp --test local-files           # connect and list tools\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mcp_parser.add_argument("--list", action="store_true", help="List all configured MCP servers")
    mcp_parser.add_argument("--add", metavar="NAME", help="Add a server with this name (use with --command or --url)")
    mcp_parser.add_argument("--remove", metavar="NAME", help="Remove the named server")
    mcp_parser.add_argument("--test", metavar="NAME", help="Connect to the named server and list its tools")
    mcp_parser.add_argument("--cmd", help="Executable to run for a stdio server (use with --add)")
    mcp_parser.add_argument("--args", nargs="*", help="Arguments for the stdio command (use with --add)")
    mcp_parser.add_argument("--url", help="URL for a Streamable HTTP server (use with --add)")
    mcp_parser.add_argument("--trust", action="store_true", help="Mark server as trusted (skip per-call confirmation)")
    mcp_parser.add_argument("--env", action="append", help="Environment variable for stdio server, KEY=VALUE (repeatable)")

    # Config command
    config_parser = subparsers.add_parser(
        "config",
        help="Manage and migrate config files",
        description=(
            "Manage the config files in ~/.config/raggie. Migrations update "
            "older config schemas to the latest version shipped with raggie.\n\n"
            "Examples:\n"
            "  raggie config status              # show current vs latest schema version\n"
            "  raggie config migrate             # apply pending migrations\n"
            "  raggie config migrate --dry-run   # preview what migrations would do\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_parser.add_argument("action", nargs="?", choices=["status", "migrate"], help="Action to perform: 'status' (default) or 'migrate'")
    config_parser.add_argument("--dry-run", action="store_true", help="Show what migrations would be applied without writing any files")

    return parser


def parse_args():
    """Parse command-line arguments and return the parsed args."""
    if len(sys.argv) > 1 and sys.argv[1] in KNOWN_COMMANDS:
        parser = _create_subcommand_parser()
    else:
        parser = _create_agent_parser()

    args = parser.parse_args()

    acp_mode = getattr(args, "acp_stdio", False) or getattr(args, "acp_http", False)
    web_mode = getattr(args, "web", False)
    if getattr(args, "command", None) is None and getattr(args, "role", None) is None and not acp_mode and not web_mode:
        parser.print_help()
        sys.exit(1)

    return args
