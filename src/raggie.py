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
from Agent.chat_history_db import init_db, select_chat, create_chat
from Agent.config import load_keys, load_roles, save_roles, USER_CONFIG_DIR
from Agent.config import load_mcp_servers, init_config, get_schema_version, run_migrations
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
                reasoning_effort = config.get("reasoning_effort", "") or "(auto)"
                provider = config.get("provider", "") or "(auto)"
                print(f"  {i}. {name}")
                print(f"     Model:            {model}")
                print(f"     Base URL:         {base_url}")
                print(f"     Provider:         {provider}")
                print(f"     Context Window:   {ctx_window}")
                print(f"     Prompt:           {prompt_short}")
                print(f"     Reasoning:        {reasoning}")
                print(f"     Reasoning Effort: {reasoning_effort}")
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

            # Provider selection (mandatory)   drives API behavior and the
            # default base_url suggestion below.
            from Agent.providers import (
                KNOWN_PROVIDERS, infer_provider, suggest_base_url, get_behavior,
            )
            current_provider = role.get('provider', '') or ''
            inferred = infer_provider(role.get('base_url', ''))
            print(f"\nKnown providers: {', '.join(KNOWN_PROVIDERS)}")
            if not current_provider and inferred:
                print(f"  (inferred from base URL -> {inferred})")
            try:
                new_provider = input(
                    f"Provider [{current_provider or inferred}]: "
                ).strip()
            except KeyboardInterrupt:
                print()
                return
            except EOFError:
                print()
                return

            if new_provider:
                if new_provider in KNOWN_PROVIDERS:
                    role['provider'] = new_provider
                else:
                    print(f"Unknown provider '{new_provider}', keeping previous.")
            elif not current_provider and inferred:
                role['provider'] = inferred

            effective_provider = role.get('provider', '') or inferred

            # Base URL selection (optional)   suggest the default for the
            # chosen provider; user can accept it, pick from keys, or override.
            from Agent.providers import parse_key_id
            keys = load_keys()
            # Filter keys to those matching the selected provider.
            key_entries = []
            for key_id in keys.keys():
                kp, kurl = parse_key_id(key_id)
                if kp == effective_provider:
                    key_entries.append(kurl)
                elif not kp and infer_provider(kurl) == effective_provider:
                    # Legacy format (bare base_url) matching this provider.
                    key_entries.append(kurl)
            current_url = role.get('base_url', '')
            suggested = suggest_base_url(effective_provider)
            default_url = current_url or suggested or ''

            if key_entries:
                print(f"\nAvailable base URLs (from your keys for '{effective_provider}'):")
                for i, url in enumerate(key_entries, 1):
                    marker = " (current)" if url == current_url else ""
                    print(f"  {i}. {url}{marker}")
                if suggested and suggested not in key_entries:
                    print(f"  0. Use provider default: {suggested}")
                else:
                    print(f"  0. Enter a custom URL")
                if suggested:
                    print(f"  (leave blank to use provider default -> {suggested})")
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
                    if not current_url and suggested:
                        role['base_url'] = suggested
                elif url_choice == "0":
                    if suggested and suggested not in key_entries:
                        role['base_url'] = suggested
                    else:
                        try:
                            new_url = input(f"Base URL [{default_url}]: ").strip()
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
                    if url_idx >= 1 and url_idx <= len(key_entries):
                        role['base_url'] = key_entries[url_idx - 1]
                    elif url_idx != -1:
                        print("Invalid selection, keeping current base URL.")
            else:
                hint = f" (provider default: {suggested})" if suggested else ""
                try:
                    new_url = input(f"Base URL [{default_url}]{hint} (no keys configured, run 'raggie keys' first): ").strip()
                except KeyboardInterrupt:
                    print()
                    return
                except EOFError:
                    print()
                    return
                if new_url:
                    role['base_url'] = new_url
                elif not current_url and suggested:
                    role['base_url'] = suggested

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

            # Reasoning effort selection
            current_effort = role.get('reasoning_effort', '') or ''
            behavior = get_behavior(effective_provider)
            effort_values = behavior.get('reasoning_effort_values', [])
            if effort_values:
                effort_default = behavior.get('reasoning_effort_default', '')
                print(f"\nReasoning effort levels: {', '.join(effort_values)}")
                print(f"  (leave blank to use provider default -> {effort_default})")
                try:
                    new_effort = input(
                        f"Reasoning Effort [{current_effort or effort_default}]: "
                    ).strip().lower()
                except KeyboardInterrupt:
                    print()
                    return
                except EOFError:
                    print()
                    return

                if new_effort:
                    if new_effort in effort_values:
                        role['reasoning_effort'] = new_effort
                    else:
                        print(
                            f"Invalid effort '{new_effort}', keeping previous."
                        )
                elif not current_effort:
                    role['reasoning_effort'] = ""

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
            for i, (key_id, key) in enumerate(keys.items(), 1):
                from Agent.providers import parse_key_id
                provider, base_url = parse_key_id(key_id)
                if provider:
                    print(f"  {i}. [{provider}] {base_url} -> {mask_key(key)}")
                else:
                    # Legacy format (bare base_url)
                    print(f"  {i}. {key_id} -> {mask_key(key)}")
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
            from Agent.providers import (
                KNOWN_PROVIDERS, suggest_base_url, make_key_id,
            )
            print(f"\nKnown providers: {', '.join(KNOWN_PROVIDERS)}")
            provider = input("Provider: ").strip()
            if not provider:
                print("Provider cannot be empty.")
                continue
            if provider not in KNOWN_PROVIDERS:
                print(f"Unknown provider '{provider}'.")
                continue

            # Autofill base_url from the provider default; user can override.
            suggested = suggest_base_url(provider)
            base_url = input(f"Base URL [{suggested}]: ").strip()
            if not base_url:
                base_url = suggested
            if not base_url:
                print("Base URL cannot be empty (provider has no default).")
                continue

            key = input("API Key: ").strip()
            if not key:
                print("API Key cannot be empty.")
                continue

            key_id = make_key_id(provider, base_url)
            keys = load_keys()
            keys[key_id] = key
            keys_file.parent.mkdir(parents=True, exist_ok=True)
            with open(keys_file, "w") as f:
                json.dump(keys, f, indent=2)
            print(f"Key for [{provider}] {base_url} saved.")

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

    if getattr(args, "import_skill_dir", None):
        if not args.role:
            print("Error: role is required when using --import-skill-dir", file=sys.stderr)
            sys.exit(1)
        try:
            target = Path(args.import_skill_dir)
            # If the target itself contains a SKILL.md, import it as a single skill.
            # Otherwise treat it as a container of skill subdirectories.
            if (target / "SKILL.md").exists() or (target / "skill.md").exists():
                name = manager.import_from_skill_dir(args.role, str(target))
                print(f"Imported skill '{name}' for role '{args.role}' from {target}")
            elif target.is_dir():
                imported = manager.import_skill_dirs(args.role, str(target))
                if imported:
                    print(f"Imported {len(imported)} skill(s) for role '{args.role}':")
                    for name in imported:
                        print(f"  - {name}")
                else:
                    print(f"No skill directories (with SKILL.md) found in {target}")
            else:
                print(f"Error: {target} is not a directory", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"Error importing skill directory: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if getattr(args, "export_skill_dir", None):
        if not args.role:
            print("Error: role is required when using --export-skill-dir", file=sys.stderr)
            sys.exit(1)
        if not args.name:
            print("Error: --name is required when using --export-skill-dir", file=sys.stderr)
            sys.exit(1)
        try:
            out_path = manager.export_to_skill_dir(args.role, args.name, args.export_skill_dir)
            print(f"Exported skill '{args.name}' for role '{args.role}' to {out_path}")
        except Exception as e:
            print(f"Error exporting skill directory: {e}", file=sys.stderr)
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


def handle_mcp_command(args):
    """Manage configured MCP servers in ~/.config/raggie/mcp_servers.json."""
    from Agent.config import ensure_config_exists

    config_file = ensure_config_exists("mcp_servers.json")
    with open(config_file, "r") as f:
        servers = json.load(f)

    if args.list:
        if not servers:
            print("No MCP servers configured. Use 'raggie mcp --add <name> ...' to add one.")
            return
        print(f"Configured MCP servers ({config_file}):\n")
        for name, cfg in servers.items():
            kind = "stdio" if "command" in cfg else "http" if "url" in cfg else "unknown"
            target = cfg.get("command", cfg.get("url", ""))
            trust = " [trusted]" if cfg.get("trust") else ""
            print(f"  {name} ({kind}){trust}")
            print(f"    {target} {cfg.get('args', []) if kind == 'stdio' else ''}".rstrip())
        return

    if args.add:
        name = args.add
        if name in servers:
            print(f"Server '{name}' already exists. Remove it first with --remove.")
            return
        cfg = {}
        if args.url:
            cfg["url"] = args.url
        elif args.cmd:
            cfg["command"] = args.cmd
            cfg["args"] = list(args.args or [])
            if args.env:
                env = {}
                for pair in args.env:
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        env[k] = v
                if env:
                    cfg["env"] = env
        else:
            print("Error: --add requires either --command (stdio) or --url (HTTP).")
            return
        if args.trust:
            cfg["trust"] = True
        servers[name] = cfg
        with open(config_file, "w") as f:
            json.dump(servers, f, indent=2)
        print(f"Added MCP server '{name}'. Run 'raggie mcp --test {name}' to verify.")
        return

    if args.remove:
        name = args.remove
        if name not in servers:
            print(f"No server named '{name}' is configured.")
            return
        del servers[name]
        with open(config_file, "w") as f:
            json.dump(servers, f, indent=2)
        print(f"Removed MCP server '{name}'.")
        return

    if args.test:
        name = args.test
        if name not in servers:
            print(f"No server named '{name}' is configured.")
            return
        import mcp_client
        manager = mcp_client.McpManager()
        count = manager.connect({name: servers[name]})
        if count == 0:
            print(f"Failed to connect to '{name}'.")
            return
        print(f"Connected to '{name}' (protocol negotiated by SDK).")
        print(f"Discovered {len(manager.tool_names)} tools:")
        for tname in manager.tool_names:
            print(f"  {tname}")
        manager.shutdown()
        return

    print("Use --list, --add, --remove, or --test. See 'raggie mcp --help'.")


def handle_config_command(args):
    """Manage config schema migrations in ~/.config/raggie."""
    from Agent.migrations import LATEST_VERSION

    action = getattr(args, "action", None) or "status"
    current = get_schema_version()

    if action == "status":
        print(f"Config dir: {USER_CONFIG_DIR}")
        print(f"Schema version: {current}")
        print(f"Latest version:  {LATEST_VERSION}")
        if current < LATEST_VERSION:
            pending = run_migrations(dry_run=True)
            print(f"\nPending migrations ({len(pending)}):")
            for from_v, to_v, desc in pending:
                print(f"  v{from_v} -> v{to_v}: {desc}")
            print("\nRun 'raggie config migrate' to apply.")
        else:
            print("\nConfig is up to date.")
        return

    if action == "migrate":
        if current >= LATEST_VERSION:
            print(f"Config is already at the latest schema version ({LATEST_VERSION}).")
            return
        if args.dry_run:
            pending = run_migrations(dry_run=True)
            print(f"Would apply {len(pending)} migration(s):")
            for from_v, to_v, desc in pending:
                print(f"  v{from_v} -> v{to_v}: {desc}")
            print("\nNo files were modified (dry run).")
            return
        applied = run_migrations(dry_run=False)
        if not applied:
            print("No migrations to apply.")
            return
        print(f"Applied {len(applied)} migration(s):")
        for from_v, to_v, desc in applied:
            print(f"  v{from_v} -> v{to_v}: {desc}")
        print(f"\nConfig is now at schema version {get_schema_version()}.")


def main():
    args = parse_args()

    # Process-wide debug flag: agents (main and subagents) default to it.
    import io_backend
    io_backend.set_debug(getattr(args, "debug", False))

    # Switch to the isolated dev data directory before anything touches the
    # database / git repo / code index, so a dev build never shares or wipes
    # the production ".raggie" state.
    if getattr(args, "dev", False):
        from raggie_dirs import enable_dev_mode
        enable_dev_mode()

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

    # Handle mcp command
    if getattr(args, "command", None) == "mcp":
        handle_mcp_command(args)
        return

    # Handle config command
    if getattr(args, "command", None) == "config":
        handle_config_command(args)
        return

    # Ensure config files exist and apply any pending schema migrations.
    # Runs for both ACP and interactive/non-interactive agent modes.
    init_config()

    # ACP agent modes: headless protocol servers, no interactive terminal
    if getattr(args, "acp_stdio", False) or getattr(args, "acp_http", False):
        from acp_server import run_stdio, run_http
        role = args.role or "code"
        dev = getattr(args, "dev", False)
        if args.acp_stdio:
            run_stdio(role, debug=args.debug, auto_approve=args.acp_auto_approve, dev=dev)
        else:
            run_http(role, port=args.acp_port, debug=args.debug, auto_approve=args.acp_auto_approve, dev=dev)
        return

    # Web UI mode: `raggie code --web` serves the web UI + ACP-over-HTTP API
    # rooted at the current directory.
    if getattr(args, "web", False):
        if args.prompt:
            print("Error: --prompt cannot be combined with --web", file=sys.stderr)
            sys.exit(1)
        from acp_server import run_web
        run_web(
            args.role or "code",
            port=args.acp_port,
            debug=args.debug,
            auto_approve=args.acp_auto_approve,
            dev=getattr(args, "dev", False),
        )
        return

    # Resolve and prepare project directory
    project_dir = Path(args.project_dir).resolve()
    if not project_dir.exists():
        project_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(str(project_dir))

    # Check if the raggie data dir exists   if so, the user has already confirmed
    # this is a project directory (or raggie created it). Skip the warning.
    from raggie_dirs import get_raggie_dir_name
    cwd = os.getcwd()
    raggie_dir_name = get_raggie_dir_name()
    has_raggie = os.path.exists(os.path.join(cwd, raggie_dir_name))

    if not has_raggie:
        # Check if the directory has subdirectories   if it's flat,
        # it's small enough to index without risk, skip the prompt.
        has_subdirs = any(os.path.isdir(os.path.join(cwd, d)) for d in os.listdir(cwd))
        if has_subdirs:
            console.print(
                f"[yellow]Warning:[/yellow] '{cwd}' doesn't look like a raggie project found here "
                f"(no {raggie_dir_name} folder found).\n"
                f"If this isn't your actual project directory the system here will scan unrelated files and can take a long time if there were so many."
            )
            try:
                response = input("\nDo you want to create a new project here? (y/N): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                response = "n"

            if response not in ("y", "yes"):
                console.print(
                    "Please cd into your project directory and try again.\n"
                    "To start a new project: raggie code <project-name>"
                )
                sys.exit(0)
    
    # Initialize database
    init_db()
    
    # Auto-detect interactive mode: if no prompt provided, use interactive mode
    interactive_mode = not args.prompt

    # Build the agent for a chat id and attach tools, commands and MCP servers.
    def _build_agent(chat_id):
        from Agent.agent import Agent
        try:
            agent = Agent(args.role, chat_id=chat_id, debug=args.debug)
        except Exception as e:
            print(f"\nError: {e}", file=sys.stderr)
            print("\nRun 'raggie setup' to configure your roles and API keys.", file=sys.stderr)
            sys.exit(1)
        setup_toolcalls(agent.tool_registry)
        setup_commands(agent.command_registry)
        try:
            import mcp_client
            mcp_client.setup(agent.tool_registry)
        except Exception as e:
            print(f"Warning: MCP server setup failed: {e}", file=sys.stderr)
        return agent

    if interactive_mode:
        # Interactive loop: Ctrl+C on the master prompt goes back to the chat
        # selection screen (run_interactive returns BACK_TO_CHAT_SELECT).
        # Ctrl+C on the selection screen itself exits the app (select_chat
        # handles it with sys.exit).
        from interactive import run_interactive, BACK_TO_CHAT_SELECT
        while True:
            chat_id = select_chat(args.role)
            if chat_id is None:
                chat_id = create_chat(args.role)
            agent = _build_agent(chat_id)
            if run_interactive(agent, args.role) != BACK_TO_CHAT_SELECT:
                break
        return

    # Non-interactive mode: use latest chat or create new one
    from Agent.chat_history_db import list_chats
    chats = list_chats(args.role)
    if chats:
        chat_id = chats[0]['id']  # Use most recent chat
    else:
        chat_id = create_chat(args.role)

    agent = _build_agent(chat_id)

    if not args.prompt:
        print("Error: prompt is required in non-interactive mode")
        from cli import _create_agent_parser
        _create_agent_parser().print_help()
        sys.exit(1)

    from interactive import run_non_interactive
    run_non_interactive(agent, args.prompt, thinking_mode=getattr(args, 'thinking_mode', None))


if __name__ == "__main__":
    main()
