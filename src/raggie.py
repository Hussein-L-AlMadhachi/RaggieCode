#!/usr/bin/env python3
"""
Raggie - AI Coding Agent
Main entry point for the Raggie coding agent.
"""

import json
import os
import sys
from pathlib import Path
from rich.console import Console

console = Console()
GREEN = "\033[32m"
DIM = "\033[2m"
RESET = "\033[0m"

from cli import parse_args
from Agent.agent import Agent
from Agent.chat_history_db import init_db, select_chat, create_chat
from Agent.config import load_keys, load_roles, save_roles, USER_CONFIG_DIR
from skills import SkillManager
from Tools import setup_toolcalls
from Commands import setup_commands


def mask_key(key):
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]


def handle_roles_command():
    """Interactive menu to list roles and edit their base URL and model."""
    while True:
        roles = load_roles()
        print()
        print("Agent Roles")
        print("-" * 60)
        if not roles:
            print("  (no roles defined)")
        else:
            for i, (name, config) in enumerate(roles.items(), 1):
                model = config.get("model", "?")
                base_url = config.get("base_url", "?")
                prompt_src = config.get("system_prompt_file", "") or config.get("system_prompt", "")
                prompt_short = (prompt_src[:50] + "...") if len(str(prompt_src)) > 50 else prompt_src
                ctx_window = config.get("context_window", "?")
                reasoning = "on" if config.get("reasoning", False) else "off"
                streaming = "on" if config.get("stream", False) else "off"
                print(f"  {i}. {name}")
                print(f"     Model:          {model}")
                print(f"     Base URL:       {base_url}")
                print(f"     Context Window: {ctx_window}")
                print(f"     Prompt:         {prompt_short}")
                print(f"     Reasoning:      {reasoning}")
                print(f"     Streaming:      {streaming}")
        print()
        print("q. Exit")
        print("1. Edit role's base URL / model")
        print()

        try:
            choice = input("Choice: ").strip()
        except KeyboardInterrupt:
            print()
            return
        except EOFError:
            print()
            return

        if choice == "1":
            if not roles:
                print("No roles to edit.")
                continue

            if len(roles) == 1:
                idx = 1
            else:
                try:
                    idx = input("Number to edit (or 0 to cancel): ").strip()
                except KeyboardInterrupt:
                    print()
                    return
                except EOFError:
                    print()
                    return

                try:
                    idx = int(idx)
                except ValueError:
                    print("Invalid number.")
                    continue
                if idx == 0:
                    continue
                if idx < 1 or idx > len(roles):
                    print("Invalid selection.")
                    continue

            role_name = list(roles.keys())[idx - 1]
            role = roles[role_name]
            print(f"\nEditing '{role_name}'. Press Enter to keep current value.")

            new_model = ""
            new_url = ""

            try:
                new_model = input(f"Model [{role.get('model', '')}]: ").strip()
            except KeyboardInterrupt:
                print()
                return
            except EOFError:
                print()
                return

            if new_model:
                role['model'] = new_model

            # Base URL selection from keys.json
            keys = load_keys()
            key_urls = list(keys.keys())
            current_url = role.get('base_url', '')

            if key_urls:
                print(f"\nAvailable base URLs (from your keys):")
                for i, url in enumerate(key_urls, 1):
                    marker = " (current)" if url == current_url else ""
                    print(f"  {i}. {url}{marker}")
                print(f"  0. Enter a custom URL")
                print()
                try:
                    url_choice = input(f"Select base URL (or press Enter to keep current): ").strip()
                except KeyboardInterrupt:
                    print()
                    return
                except EOFError:
                    print()
                    return

                if url_choice == "":
                    pass
                elif url_choice == "0":
                    try:
                        new_url = input(f"Base URL [{current_url}]: ").strip()
                    except KeyboardInterrupt:
                        print()
                        return
                    except EOFError:
                        print()
                        return
                    if new_url:
                        role['base_url'] = new_url
                else:
                    try:
                        url_idx = int(url_choice)
                    except ValueError:
                        print("Invalid selection, keeping current base URL.")
                        url_idx = -1
                    if url_idx >= 1 and url_idx <= len(key_urls):
                        role['base_url'] = key_urls[url_idx - 1]
                    elif url_idx != -1:
                        print("Invalid selection, keeping current base URL.")
            else:
                try:
                    new_url = input(f"Base URL [{current_url}] (no keys configured, run 'raggie keys' first): ").strip()
                except KeyboardInterrupt:
                    print()
                    return
                except EOFError:
                    print()
                    return
                if new_url:
                    role['base_url'] = new_url

            try:
                new_ctx = input(f"Context Window [{role.get('context_window', '')}]: ").strip()
            except KeyboardInterrupt:
                print()
                return
            except EOFError:
                print()
                return

            if new_ctx:
                try:
                    role['context_window'] = int(new_ctx)
                except ValueError:
                    print("Invalid context window value, keeping previous.")

            try:
                current_reasoning = role.get('reasoning', False)
                new_reasoning = input(f"Reasoning (y/n) [{'on' if current_reasoning else 'off'}]: ").strip().lower()
            except KeyboardInterrupt:
                print()
                return
            except EOFError:
                print()
                return

            if new_reasoning in ('y', 'yes'):
                role['reasoning'] = True
            elif new_reasoning in ('n', 'no'):
                role['reasoning'] = False

            try:
                current_stream = role.get('stream', False)
                new_stream = input(f"Streaming (y/n) [{'on' if current_stream else 'off'}]: ").strip().lower()
            except KeyboardInterrupt:
                print()
                return
            except EOFError:
                print()
                return

            if new_stream in ('y', 'yes'):
                role['stream'] = True
            elif new_stream in ('n', 'no'):
                role['stream'] = False

            roles[role_name] = role
            save_roles(roles)
            print(f"Role '{role_name}' updated.")

        elif choice == "q":
            break
        else:
            print("Invalid choice.")


def handle_keys_command():
    keys_file = USER_CONFIG_DIR / "keys.json"

    while True:
        print()
        print("API Keys")
        print("-" * 40)
        keys = load_keys()
        if not keys:
            print("  (none)")
        else:
            for i, (url, key) in enumerate(keys.items(), 1):
                print(f"  {i}. {url} -> {mask_key(key)}")
        print()
        print("q. Skip")
        print("1. Add key")
        print("2. Remove key")
        print()

        try:
            choice = input("Choice: ").strip()
        except KeyboardInterrupt:
            print()
            return
        except EOFError:
            print()
            return

        if choice == "1":
            url = input("Base URL: ").strip()
            if not url:
                print("Base URL cannot be empty.")
                continue
            key = input("API Key: ").strip()
            if not key:
                print("API Key cannot be empty.")
                continue

            keys = load_keys()
            keys[url] = key
            keys_file.parent.mkdir(parents=True, exist_ok=True)
            with open(keys_file, "w") as f:
                json.dump(keys, f, indent=2)
            print(f"Key for {url} saved.")

        elif choice == "2":
            if not keys:
                print("No keys to remove.")
                continue

            try:
                idx = input("Number to remove (or 0 to cancel): ").strip()
            except KeyboardInterrupt:
                print()
                continue
            except EOFError:
                print()
                continue
            try:
                idx = int(idx)
            except ValueError:
                print("Invalid number.")
                continue

            if idx == 0:
                continue
            if idx < 1 or idx > len(keys):
                print("Invalid selection.")
                continue

            removed = list(keys.keys())[idx - 1]
            del keys[removed]
            with open(keys_file, "w") as f:
                json.dump(keys, f, indent=2)
            print(f"Key for {removed} removed.")

        elif choice == "q":
            break
        else:
            print("Invalid choice.")


def handle_setup_command():
    """First-time setup wizard: configure API keys, then review agent roles."""
    print()
    print("=" * 60)
    print("  Raggie Setup Wizard")
    print("=" * 60)
    print()
    print("Step 1: Configure your API keys.")
    print("You'll need at least one API key to use Raggie.")
    handle_keys_command()
    print()
    print("Step 2: Review your agent roles.")
    print("Roles define which model and base URL each agent uses.")
    handle_roles_command()
    print()
    print("=" * 60)
    print("  Setup complete! You're ready to use Raggie.")
    print("  Try: raggie code .")
    print("=" * 60)


def handle_skill_command(args):
    """Handle skill subcommands."""
    # Initialize database to ensure skills table exists
    init_db()
    
    manager = SkillManager()

    # --list-all: list all skills across all roles (role arg not required)
    if getattr(args, "list_all", False):
        skills = manager.list_skills()
        if skills:
            print("All skills:")
            print("-" * 60)
            for skill in skills:
                print(f"  {skill['role']}/{skill['name']}: {skill['summary']}")
            print("-" * 60)
        else:
            print("No skills found.")
        return

    # Flag-based operations (non-interactive)
    if args.import_skill:
        if not args.role:
            print("Error: role is required when using --import-skill", file=sys.stderr)
            sys.exit(1)
        if not args.name:
            print("Error: --name is required when using --import-skill", file=sys.stderr)
            sys.exit(1)
        try:
            manager.import_from_markdown(args.role, args.name, args.import_skill)
            print(f"Successfully imported skill '{args.name}' for role '{args.role}' from {args.import_skill}")
        except Exception as e:
            print(f"Error importing skill: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.export_skill:
        if not args.role:
            print("Error: role is required when using --export-skill", file=sys.stderr)
            sys.exit(1)
        if not args.name:
            print("Error: --name is required when using --export-skill", file=sys.stderr)
            sys.exit(1)
        try:
            manager.export_to_markdown(args.role, args.name, args.export_skill)
            print(f"Successfully exported skill '{args.name}' for role '{args.role}' to {args.export_skill}")
        except Exception as e:
            print(f"Error exporting skill: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if getattr(args, "delete", False):
        if not args.role:
            print("Error: role is required when using --delete", file=sys.stderr)
            sys.exit(1)
        if not args.name:
            print("Error: --name is required when using --delete", file=sys.stderr)
            sys.exit(1)
        deleted = manager.delete_skill(args.role, args.name)
        if deleted:
            print(f"Successfully deleted skill '{args.name}' for role '{args.role}'")
        else:
            print(f"No skill '{args.name}' found for role '{args.role}'")
        return

    if args.show and args.name:
        # Show specific skill (non-interactive)
        if not args.role:
            print("Error: role is required", file=sys.stderr)
            sys.exit(1)
        skill = manager.get_skill(args.role, args.name)
        if skill:
            print(f"Skill '{args.name}' for role '{args.role}':")
            print("-" * 60)
            print(skill)
            print("-" * 60)
        else:
            print(f"No skill '{args.name}' found for role '{args.role}'")
        return

    # Interactive mode: no flags, or --show without --name
    _skill_interactive_menu(manager, args.role)


def _skill_interactive_menu(manager, role_filter=None):
    """Interactive menu for managing skills."""
    while True:
        if role_filter:
            skills = manager.list_skills_by_role(role_filter)
            header = f"Skills for role '{role_filter}'"
        else:
            skills = manager.list_skills()
            header = "All Skills"

        print()
        print(header)
        print("-" * 60)
        if not skills:
            print("  (no skills found)")
        else:
            for i, skill in enumerate(skills, 1):
                r = skill['role']
                n = skill['name']
                s = skill['summary']
                if role_filter:
                    print(f"  {i}. {n}: {s}")
                else:
                    print(f"  {i}. {r}/{n}: {s}")
        print()
        print("q. Exit")
        print("1. View skill content")
        print("2. Delete skill")
        print("3. Export skill to file")
        print("4. Import skill from file")
        print("5. List all skills (all roles)")
        print()

        try:
            choice = input("Choice: ").strip()
        except KeyboardInterrupt:
            print()
            return
        except EOFError:
            print()
            return

        if choice == "q":
            break

        elif choice == "1":
            # View skill content
            if not skills:
                print("No skills to view.")
                continue
            try:
                idx = input("Number to view (or 0 to cancel): ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            try:
                idx = int(idx)
            except ValueError:
                print("Invalid number.")
                continue
            if idx == 0:
                continue
            if idx < 1 or idx > len(skills):
                print("Invalid selection.")
                continue
            skill = skills[idx - 1]
            content = manager.get_skill(skill['role'], skill['name'])
            print()
            print(f"Skill '{skill['name']}' for role '{skill['role']}':")
            print("=" * 60)
            print(content or "(empty)")
            print("=" * 60)

        elif choice == "2":
            # Delete skill
            if not skills:
                print("No skills to delete.")
                continue
            try:
                idx = input("Number to delete (or 0 to cancel): ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            try:
                idx = int(idx)
            except ValueError:
                print("Invalid number.")
                continue
            if idx == 0:
                continue
            if idx < 1 or idx > len(skills):
                print("Invalid selection.")
                continue
            skill = skills[idx - 1]
            try:
                confirm = input(f"Delete '{skill['role']}/{skill['name']}'? (y/n): ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            if confirm == 'y' or confirm == 'yes':
                manager.delete_skill(skill['role'], skill['name'])
                print(f"Deleted '{skill['role']}/{skill['name']}'.")
            else:
                print("Cancelled.")

        elif choice == "3":
            # Export skill to file
            if not skills:
                print("No skills to export.")
                continue
            try:
                idx = input("Number to export (or 0 to cancel): ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            try:
                idx = int(idx)
            except ValueError:
                print("Invalid number.")
                continue
            if idx == 0:
                continue
            if idx < 1 or idx > len(skills):
                print("Invalid selection.")
                continue
            skill = skills[idx - 1]
            try:
                file_path = input(f"Export to file [skill-{skill['name']}.md]: ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            if not file_path:
                file_path = f"skill-{skill['name']}.md"
            try:
                manager.export_to_markdown(skill['role'], skill['name'], file_path)
                print(f"Exported '{skill['role']}/{skill['name']}' to {file_path}")
            except Exception as e:
                print(f"Error exporting: {e}")

        elif choice == "4":
            # Import skill from file
            try:
                role = input(f"Role [{role_filter or 'code'}]: ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            if not role:
                role = role_filter or "code"
            try:
                name = input("Skill name: ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            if not name:
                print("Skill name is required.")
                continue
            try:
                file_path = input("File path: ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            if not file_path:
                print("File path is required.")
                continue
            try:
                manager.import_from_markdown(role, name, file_path)
                print(f"Imported skill '{name}' for role '{role}' from {file_path}")
            except Exception as e:
                print(f"Error importing: {e}")

        elif choice == "5":
            # Switch to all-roles view
            role_filter = None

        else:
            print("Invalid choice.")


def main():
    args = parse_args()
    
    # Handle skill command
    if getattr(args, "command", None) == "skill":
        handle_skill_command(args)
        return
    
    # Handle roles command
    if getattr(args, "command", None) == "roles":
        handle_roles_command()
        return
    
    # Handle keys command
    if getattr(args, "command", None) == "keys":
        handle_keys_command()
        return
    
    # Handle setup command
    if getattr(args, "command", None) == "setup":
        handle_setup_command()
        return
    
    # Resolve and prepare project directory
    project_dir = Path(args.project_dir).resolve()
    if not project_dir.exists():
        project_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(str(project_dir))
    
    # Initialize database
    init_db()
    
    # Get or create chat
    # Auto-detect interactive mode: if no prompt provided, use interactive mode
    interactive_mode = not args.prompt
    
    if interactive_mode:
        # In interactive mode, let user select chat
        chat_id = select_chat(args.role)
        if chat_id is None:
            chat_id = create_chat(args.role)
    else:
        # In non-interactive mode, use latest chat or create new one
        from Agent.chat_history_db import list_chats
        chats = list_chats(args.role)
        if chats:
            chat_id = chats[0]['id']  # Use most recent chat
        else:
            chat_id = create_chat(args.role)
    
    # Create agent with the selected chat
    try:
        agent = Agent(args.role, chat_id=chat_id, debug=args.debug)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        print("\nRun 'raggie setup' to configure your roles and API keys.", file=sys.stderr)
        sys.exit(1)
    
    # Setup tools and commands
    setup_toolcalls(agent.tool_registry)
    setup_commands(agent.command_registry)
    
    # Run agent
    if interactive_mode:
        from interactive import run_interactive
        run_interactive(agent, args.role)
    else:
        if not args.prompt:
            print("Error: prompt is required in non-interactive mode")
            from cli import _create_agent_parser
            _create_agent_parser().print_help()
            sys.exit(1)

        from interactive import run_non_interactive
        run_non_interactive(agent, args.prompt)


if __name__ == "__main__":
    main()
