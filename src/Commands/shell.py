import subprocess


def handle(args, agent):
    """Handle the ! shell command.

    Runs *args* as a shell command and returns the combined output.

    Args:
        args: The shell command string (everything after ``!``).
        agent: The Agent instance (unused).

    Returns:
        Empty string (agent does nothing; output is printed directly).
    """
    if not args:
        return ""
    try:
        result = subprocess.run(
            args, shell=True, capture_output=True, text=True
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
    except Exception as e:
        print(f"Error executing command: {e}")
    return ""
