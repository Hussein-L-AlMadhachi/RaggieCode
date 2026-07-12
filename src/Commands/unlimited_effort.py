def handle(args, agent):
    """Secret command to set truly unlimited effort depth."""
    from Agent.effort_levels import UNLIMITED_EFFORT
    from Agent.chat_history_db import set_session_effort

    set_session_effort(agent.session_id, UNLIMITED_EFFORT)
    print("Effort: Unlimited")
    return ""
