def handle(args, agent):
    BLUE = "\033[34m"
    RESET = "\033[0m"

    redone_commit = agent.git_manager.redo_last_commit()
    if redone_commit:
        print(f"Redone to commit: {redone_commit}\n")
        print(f"{BLUE}type /undo to undo the last code changes{RESET}")
    else:
        print("Nothing to redo")
    return ""
