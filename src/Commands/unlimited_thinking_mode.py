def handle(args, agent):
    """Secret command to set truly unlimited thinking-mode depth."""
    from Agent.thinking_modes import UNLIMITED_THINKING_MODE
    from Agent.chat_history_db import set_session_thinking_mode

    set_session_thinking_mode(agent.session_id, UNLIMITED_THINKING_MODE)
    print("Thinking mode: Unlimited")
    return ""
