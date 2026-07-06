from .utils import BLUE, GREEN, YELLOW, RED, RESET


def handle(arguments, toolcall_id):
    """Ask the user a question, optionally with predefined options."""
    from prompt_toolkit import prompt

    question = arguments.get("question", "")
    options = arguments.get("options", [])
    allow_multiple = arguments.get("allow_multiple", False)

    if not question:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'question' is required",
        }

    try:
        print(f"\n{BLUE}Agent has a question:{RESET}")
        print(f"{YELLOW}{question}{RESET}")
        print()

        if not options:
            # Free-form question
            user_input = prompt("Your answer: ", multiline=True).strip()
            print()
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"User answered: {user_input}",
            }

        # Display numbered options
        print(f"{BLUE}Options:{RESET}")
        for i, opt in enumerate(options):
            label = opt.get("label", f"Option {i + 1}")
            description = opt.get("description", "")
            print(f"  {GREEN}{i + 1}.{RESET} {label}")
            if description:
                print(f"     {description}")
        print()

        if allow_multiple:
            hint = "Enter one or more numbers (comma-separated), or type your own answer"
        else:
            hint = "Enter a number, or type your own answer"

        user_input = prompt(f"{hint}: ", multiline=True).strip()
        print()

        if not user_input:
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": "User skipped the question (no answer provided)",
            }

        # Try to parse as number(s)
        selected_labels = []
        try:
            if allow_multiple:
                indices = [int(x.strip()) for x in user_input.split(",")]
                for idx in indices:
                    if 1 <= idx <= len(options):
                        selected_labels.append(options[idx - 1].get("label", f"Option {idx}"))
                    else:
                        selected_labels.append(f"(invalid: {idx})")
            else:
                idx = int(user_input)
                if 1 <= idx <= len(options):
                    selected_labels.append(options[idx - 1].get("label", f"Option {idx}"))
                else:
                    selected_labels.append(f"(invalid: {idx})")
            answer = ", ".join(selected_labels)
            print(f"{GREEN}User selected: {answer}{RESET}\n")
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"User selected: {answer}",
            }
        except ValueError:
            # User typed a custom answer
            print(f"{GREEN}User answered: {user_input}{RESET}\n")
            return {
                "role": "tool",
                "tool_call_id": toolcall_id,
                "content": f"User answered: {user_input}",
            }
    except (KeyboardInterrupt, EOFError):
        print(f"\n{RED}User cancelled the question{RESET}\n")
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "User cancelled the question (Ctrl+C)",
        }
    except Exception as e:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Failed to ask user: {str(e)}",
        }
