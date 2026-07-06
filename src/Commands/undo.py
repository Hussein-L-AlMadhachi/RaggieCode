def handle(args, agent):
    previous_commit = agent.git_manager.undo_last_commit()

    BLUE = "\033[34m"
    RESET = "\033[0m"

    if previous_commit:
        print(f"Undid to commit: {previous_commit}\n")
        print(f"{BLUE}type /redo to redo the last code changes{RESET}")

    else:
        print("No previous commit to undo")
    return ""
