from .manager import SkillManager


def handle_get_skill(args, tool_call_id, agent_role=None):
    """Handle the GetSkill tool call — fetches the full content of a specific skill by name for the caller's role."""
    name = args.get("name")
    
    if not agent_role:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": "Error: could not determine agent role"
        }
    
    if not name:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": "Error: 'name' parameter is required"
        }
    
    manager = SkillManager()
    content = manager.get_skill(agent_role, name)
    
    if content is None:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": f"No skill found for role '{agent_role}' with name '{name}'. Use SetSkill to create one."
        }
    
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": f"Skill '{name}' for role '{agent_role}':\n\n{content}"
    }


def handle(args, tool_call_id, agent_role=None):
    """Handle the SetSkill tool call with user consent.
    
    The agent can only create/update skills for its own role.
    """
    name = args.get("name")
    content = args.get("content")
    
    if not agent_role:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": "Error: could not determine agent role"
        }
    
    if not name:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": "Error: 'name' parameter is required"
        }
    
    if not content:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": "Error: 'content' parameter is required"
        }
    
    # Check if skill already exists to provide better feedback
    manager = SkillManager()
    existing_skill = manager.get_skill(agent_role, name)
    action = "update" if existing_skill else "create"
    
    # Ask for user consent
    print(f"\n{'='*60}")
    print(f"Agent wants to {action} skill '{name}' for role: {agent_role}")
    print(f"{'='*60}")
    print(f"Proposed skill content:")
    print("-" * 60)
    print(content)
    print("-" * 60)
    
    consent = ""
    try:
        consent = input(f"\nDo you accept this {action} of '{name}' skill for role '{agent_role}'? (y/n): ").strip().lower()
    except KeyboardInterrupt:
        print()
        exit(0)
    except EOFError:
        print()
        exit(0)
    
    if consent == 'y' or consent == 'yes':
        try:
            manager.set_skill(agent_role, name, content)
            return {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": f"Successfully {action}d skill '{name}' for role '{agent_role}'"
            }
        except Exception as e:
            return {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": f"Error {action}ing skill: {str(e)}"
            }
    else:
        try:
            reason = input(f"Reason for refusal (optional, press Enter to skip): ").strip()
        except (KeyboardInterrupt, EOFError):
            reason = ""
        if reason:
            return {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": f"Skill {action} rejected by user. Reason: {reason}"
            }
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": f"Skill {action} rejected by user"
        }
