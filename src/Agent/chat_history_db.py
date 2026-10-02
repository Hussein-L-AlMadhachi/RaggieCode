import sqlite3
import sys
import json
import html
import re
from pathlib import Path
from typing import List, Dict, Optional
from prompt_toolkit import prompt

from raggie_dirs import get_chat_db_path


# Backwards-compat override hook. Tests patch this to redirect the chat DB
# to a temp path; production code leaves it None and uses get_chat_db_path().
DB_PATH = None


def _resolve_db_path():
    return DB_PATH if DB_PATH is not None else get_chat_db_path()


def _get_conn():
    db_path = _resolve_db_path()
    ensure_db_file(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_db_file(db_path):
    """Create the data dir and the chat DB file (with schema) if missing.

    sqlite raises "unable to open database file" the moment a connection is
    opened against a path whose parent dir or file does not exist. The web ui
    queries the DB before any session exists, so a missing file must be created
    on the spot instead of surfacing that error to the user. If creation
    actually fails (read-only dir, bad path, ...) the underlying OSError or
    migration error is propagated.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        init_db(db_path)


def init_db(db_path=None):
    """Initialize the chat history database via yoyo migrations."""
    db_path = Path(db_path) if db_path is not None else Path(_resolve_db_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    from db_migrations import run_yoyo_migrations
    run_yoyo_migrations(str(db_path), CHAT_DB_MIGRATIONS_DIR)


# Directory containing yoyo migration files for the chat history DB.
CHAT_DB_MIGRATIONS_DIR = str(Path(__file__).parent / "migrations" / "chat_db")


def create_chat(role: str, title: Optional[str] = None) -> int:
    """Create a new chat for a given role and return its ID."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    # Use role as default title if none provided (will be updated on first message)
    if title is None:
        title = role
    
    cursor.execute("""
        INSERT INTO chats (role, title)
        VALUES (?, ?)
    """, (role, title))
    
    chat_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return chat_id


def update_chat_title(chat_id: int, title: str):
    """Update the title of a chat."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE chats
        SET title = ?
        WHERE id = ?
    """, (title, chat_id))
    
    conn.commit()
    conn.close()


def generate_title(message: str) -> str:
    """Generate a chat title from the first user message.

    The full message is kept (whitespace-normalized to single spaces so it
    can render as a one-line title); the frontend does the visual
    truncation. The clamp below is purely a safeguard for the database,
    not for display.
    """
    if not message:
        return "Untitled"

    # Newlines would break the single-line title rendering; collapse them.
    message = " ".join(message.split())

    if len(message) <= 2000:
        return message
    return message[:2000] + "..."


def list_chats(role: str) -> List[Dict]:
    """Get all chats for a given role with their titles and metadata."""
    conn = _get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM chats
        WHERE id IN (
            SELECT c.id
            FROM chats c
            JOIN sessions s ON c.id = s.chat_id
            WHERE c.role = ?
            AND s.parent_session_id IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM messages m
                WHERE m.session_id = s.id
                    AND m.role = 'user'
            )
        )
    """, (role,))

    cursor.execute("""
        SELECT id, title, created_at, updated_at
        FROM chats
        WHERE role = ?
        ORDER BY id DESC
    """, (role,))

    chats = []
    for row in cursor.fetchall():
        chats.append({
            "id": row[0],
            "title": row[1],
            "created_at": row[2],
            "updated_at": row[3]
        })

    conn.close()
    return chats


def sanitize_fts_query(query: str) -> str:
    """Build a safe FTS5 MATCH expression from a free-form query.

    Keeps word characters, prefixes every token with a wildcard so partial
    matches hit (like a substring search), and drops anything dangerous
    (quotes, operators).
    """
    tokens = re.findall(r"[\w]+", query)
    if not tokens:
        return ""
    return " ".join(f"{token}*" for token in tokens)


def search_user_messages(query: str, role: str, limit: int = 10) -> List[Dict]:
    """Full-text search over user messages (SQLite FTS5).

    Returns matches ordered by relevance with a highlighted snippet, so UIs
    can jump the user straight to the matching message.
    """
    match_query = sanitize_fts_query(query)
    if not match_query:
        return []

    conn = _get_conn()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT s.chat_id, c.title, m.id, m.content,
               snippet(messages_fts, 0, ?, ?, '...', 12),
               c.updated_at
        FROM messages_fts f
        JOIN messages m ON m.id = f.rowid
        JOIN sessions s ON s.id = m.session_id
        JOIN chats c ON c.id = s.chat_id
        WHERE messages_fts MATCH ?
          AND m.role = 'user'
          AND c.role = ?
          AND s.parent_session_id IS NULL
        ORDER BY rank
        LIMIT ?
        """,
        (
            "\x02", "\x03",
            match_query,
            role,
            int(limit),
        ),
    )

    results = []
    for row in cursor.fetchall():
        chat_id, title, message_id, _content, snippet_text, updated_at = row

        # Snippet markers travel via the FTS function; any message content that
        # looks like markup is neutralized by HTML-escaping everything, then only
        # the two control markers are turned into <mark> tags. This keeps the
        # front-end's {@html} rendering injection-safe even for truncated tags
        # or adversarial content.
        safe_snippet = html.escape(snippet_text or "", quote=False)
        safe_snippet = safe_snippet.replace("\x02", "<mark>").replace("\x03", "</mark>")
        results.append({
            "chatId": chat_id,
            "title": title or "Untitled",
            "messageId": message_id,
            "snippet": safe_snippet,
            "updatedAt": updated_at,
        })

    conn.close()
    return results


def select_chat(role: str) -> Optional[int]:
    """Let the user select a chat from available chats for a given role."""
    chats = list_chats(role)
    if not chats:
        return None

    print(f"Available chats for role '{role}':")
    print("-" * 50)
    for i, chat in enumerate(chats, 1):
        title = chat['title'] if chat['title'] else 'Untitled'
        print(f"{i}. {title}")
    print("-" * 50)
    print()
    print("press ctrl+c to exit at any point")
    print("Options: <number> to select, 'n' for new chat, 'del <number>' to delete, 'del all' to delete all")

    while True:
        try:
            import io_backend
            io_backend._flush_stdin()
            choice = prompt("Select a chat: ").strip()
        except KeyboardInterrupt:
            print()
            print("Agent: Goodbye")
            sys.exit(0)
        except EOFError:
            print()
            print("Agent: Goodbye")
            sys.exit(0)

        if choice.lower() == 'n':
            return None

        # Handle delete command: del <number> or del all
        del_match = re.match(r'^del\s+(.+)$', choice, re.IGNORECASE)
        if del_match:
            target = del_match.group(1).strip().lower()

            # del all - delete all chats for this role
            if target == 'all':
                try:
                    confirm = prompt(f"Delete ALL {len(chats)} chats for role '{role}'? (y/n): ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print("\nDelete cancelled.")
                    continue
                if confirm in ('y', 'yes'):
                    for chat in chats:
                        delete_chat(chat['id'])
                    print(f"Deleted {len(chats)} chats.\n\n")
                    return None
                else:
                    print("Delete cancelled.")
                    continue

            # del <number> - delete a specific chat
            try:
                delete_idx = int(target) - 1
                if 0 <= delete_idx < len(chats):
                    chat_to_delete = chats[delete_idx]
                    try:
                        confirm = prompt(f"Delete chat '{chat_to_delete['title']}'? (y/n): ").strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        print("\nDelete cancelled.")
                        continue
                    if confirm in ('y', 'yes'):
                        delete_chat(chat_to_delete['id'])
                        print("Chat deleted.\n\n")
                        # Refresh chat list
                        chats = list_chats(role)
                        if not chats:
                            return None
                        print(f"Available chats for role '{role}':")
                        print("-" * 50)
                        for i, chat in enumerate(chats, 1):
                            title = chat['title'] if chat['title'] else 'Untitled'
                            print(f"{i}. {title}")
                        print("-" * 50)
                        print()
                        print("press ctrl+c to exit at any point")
                        print("Options: <number> to select, 'n' for new chat, 'del <number>' to delete, 'del all' to delete all")
                        continue
                    else:
                        print("Delete cancelled.")
                        continue
                else:
                    print("Invalid chat number. Try again.")
            except (ValueError, IndexError):
                print("Invalid delete format. Use 'del <number>' (e.g., del 1) or 'del all'.")
            continue

        # Handle selection
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(chats):
                return chats[choice_idx]['id']
            else:
                print("Invalid chat number. Try again.")
        except ValueError:
            print("Please enter a valid number, 'n', or 'del <number>'.")


def get_chat_role(chat_id: int) -> Optional[str]:
    """Get the role associated with a chat ID."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT role FROM chats
        WHERE id = ?
    """, (chat_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else None

def get_chat_preview(chat_id: int) -> Optional[Dict]:
    """Get the most recent user or assistant message in a chat, as a preview.

    Returns {"role": ..., "text": ...} or None when the chat has no messages.
    """
    conn = _get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.role, m.content
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE s.chat_id = ? AND m.role IN ('user', 'assistant')
        ORDER BY m.id DESC
        LIMIT 1
    """, (chat_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None
    return {"role": row[0], "text": row[1]}


def create_session(chat_id: int, parent_session_id: Optional[int] = None, toolcall_id: Optional[str] = None, thinking_mode: Optional[int] = None, depth: int = 0) -> int:
    """Create a new session for a given chat and return its ID."""
    conn = _get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO sessions (chat_id, parent_session_id, toolcall_id, effort, depth)
        VALUES (?, ?, ?, ?, ?)
    """, (chat_id, parent_session_id, toolcall_id, thinking_mode, depth))

    session_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return session_id


def get_latest_session(chat_id: int) -> Optional[int]:
    """Get the most recent main-agent session ID for a given chat, or None if no sessions exist."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id FROM sessions
        WHERE chat_id = ? AND parent_session_id IS NULL
        ORDER BY id DESC
        LIMIT 1
    """, (chat_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else None


def get_or_create_session(chat_id: int, parent_session_id: Optional[int] = None, thinking_mode: Optional[int] = None) -> int:
    """Get the active session for a chat (following redirects), or create one if none exists."""
    session_id = get_active_session(chat_id)
    if session_id is None:
        session_id = create_session(chat_id, parent_session_id, thinking_mode=thinking_mode)
    elif thinking_mode is not None:
        set_session_thinking_mode(session_id, thinking_mode)
    return session_id


def save_message(session_id: int, message: Dict):
    """Save a message to the database."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    # Ensure all values are strings before saving
    role = message.get("role")
    if role is not None:
        role = str(role)
    else:
        role = "user"
    
    content = message.get("content")
    if content is not None:
        if isinstance(content, (list, dict)):
            content = json.dumps(content)
        else:
            content = str(content)
    else:
        content = ""
    
    tool_calls = message.get("tool_calls")
    tool_call_id = message.get("tool_call_id")
    if tool_call_id is not None:
        tool_call_id = str(tool_call_id)

    # Convert tool_calls to JSON string if present
    tool_calls_json = json.dumps(tool_calls) if tool_calls else None

    # Persist reasoning_content (DeepSeek thinking mode requires it back)
    reasoning_content = message.get("reasoning_content")
    reasoning_content_str = str(reasoning_content) if reasoning_content else None

    cursor.execute("""
        INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, reasoning_content)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (session_id, role, content, tool_calls_json, tool_call_id, reasoning_content_str))
    
    # Update session's updated_at timestamp
    cursor.execute("""
        UPDATE sessions
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (session_id,))
    
    # Update chat's updated_at timestamp
    cursor.execute("""
        UPDATE chats
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = (SELECT chat_id FROM sessions WHERE id = ?)
    """, (session_id,))
    
    conn.commit()
    conn.close()


def load_messages_page(session_ids, before_id=None, limit=30):
    """Load one page of messages ending at *before_id* (exclusive), newest first.

    *session_ids* may be a single int or a list of main-agent session IDs
    (e.g. [oldest_handed_over_session, ..., active_session]) whose messages
    are displayed as one continuous history. Message ids are globally
    increasing across sessions, so cross-session pagination stays correct.

    Returns (messages_chronological, oldest_id, has_more) where messages is a
    list of raw message dicts (oldest first) each carrying its DB "id".
    Handover-related messages carry kind="handover_prompt" (the machine-
    generated internal prompt) or kind="handover_doc" (the agent-written
    handover document).
    """
    if isinstance(session_ids, (int, str)):
        session_ids = [int(session_ids)]
    params = list(session_ids)
    placeholders = ",".join("?" * len(session_ids))

    conn = _get_conn()
    cursor = conn.cursor()

    if before_id is not None:
        cursor.execute(f"""
            SELECT id, session_id, role, content, tool_calls, tool_call_id, reasoning_content
            FROM messages
            WHERE session_id IN ({placeholders}) AND id < ?
            ORDER BY id DESC
            LIMIT ?
        """, (*params, before_id, limit))
    else:
        cursor.execute(f"""
            SELECT id, session_id, role, content, tool_calls, tool_call_id, reasoning_content
            FROM messages
            WHERE session_id IN ({placeholders})
            ORDER BY id DESC
            LIMIT ?
        """, (*params, limit))

    rows = list(cursor.fetchall())

    has_more = False
    if rows:
        # rows are newest-first: rows[0] is the newest message of the page,
        # rows[-1] the oldest. has_more must ask "is anything older than the
        # oldest message we returned?" - checking against the newest would
        # flag has_more=True even when this page holds the whole history.
        oldest_row_id = rows[-1][0]
        cursor.execute(
            f"SELECT 1 FROM messages WHERE session_id IN ({placeholders}) AND id < ? LIMIT 1",
            (*params, oldest_row_id),
        )
        has_more = cursor.fetchone() is not None

    # Newest-first from SQL; reverse to chronological order.
    rows.reverse()

    # Handover texts for these sessions: the agent-written summary saved as a
    # user message at the top of the handover target session.
    handover_texts = {}
    if rows:
        cursor.execute(
            f"SELECT new_session_id, handover_text FROM handovers WHERE new_session_id IN ({placeholders})",
            params,
        )
        handover_texts = {row[0]: row[1] for row in cursor.fetchall()}

    conn.close()

    messages = []
    for row in rows:
        content_str = str(row[3]) if row[3] is not None else ""
        content = content_str
        try:
            parsed = json.loads(content_str)
            if (isinstance(parsed, list) and parsed
                    and all(isinstance(item, dict) and "type" in item for item in parsed)):
                content = parsed
        except (json.JSONDecodeError, TypeError):
            pass

        message = {
            "id": int(row[0]),
            "session_id": int(row[1]),
            "role": str(row[2]) if row[2] is not None else "user",
            "content": content,
        }

        if row[4]:
            try:
                message["tool_calls"] = json.loads(row[4])
            except (json.JSONDecodeError, TypeError):
                message["tool_calls"] = None

        if row[5]:
            message["tool_call_id"] = str(row[5])

        if row[6]:
            message["reasoning_content"] = str(row[6])

        # Skip empty messages (no content, no tool_calls, no tool_call_id)
        if not message.get("content") and not message.get("tool_calls") and not message.get("tool_call_id"):
            continue

        handover_kind = _handover_message_kind(
            message["role"], content_str, handover_texts.get(int(row[1]))
        )
        if handover_kind:
            message["kind"] = handover_kind

        messages.append(message)

    oldest_id = min(int(row[0]) for row in rows) if rows else None
    return messages, oldest_id, has_more


HANDOVER_PROMPT_PREFIX = "Without using any more tool calls, give me a handover instruction"


def _handover_message_kind(role, content, handover_text_for_session):
    """Classify a handover-related message, or return None.

    The machine-generated handover prompt is internal plumbing   callers can
    hide it. The agent-written handover document is worth showing to the user.
    """
    if role != "user":
        return None
    if content.lstrip().startswith(HANDOVER_PROMPT_PREFIX):
        return "handover_prompt"
    if handover_text_for_session and content == handover_text_for_session:
        return "handover_doc"
    return None


def repair_message_sequence(messages: List[Dict]) -> List[Dict]:
    """Move each tool response to directly follow the assistant message that requested it.

    A crash or interrupt can leave a session where an assistant message with
    tool_calls is followed by user/other messages, with the tool responses
    appended later. The chat API requires every tool response to directly
    follow its assistant tool_calls message, so pull each one forward.
    """
    result = []
    owner = {}   # tool_call_id -> position of owning assistant message in result
    placed = {}  # assistant position -> number of its tool responses already placed
    for msg in messages:
        tool_call_id = msg.get("tool_call_id")
        if tool_call_id is not None and tool_call_id in owner:
            asst_pos = owner.pop(tool_call_id)
            insert_at = asst_pos + 1 + placed.get(asst_pos, 0)
            result.insert(insert_at, msg)
            placed = {k + 1 if k >= insert_at else k: v for k, v in placed.items()}
            placed[asst_pos] = placed.get(asst_pos, 0) + 1
            owner = {k: v + 1 if v >= insert_at else v for k, v in owner.items()}
        else:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                asst_pos = len(result)
                for tc in msg["tool_calls"]:
                    tcid = tc.get("id")
                    if tcid:
                        owner[tcid] = asst_pos
                placed[asst_pos] = 0
            result.append(msg)
    return result


def validate_message_sequence(messages: List[Dict]) -> List[str]:
    """Return a list of API-contract violations in the message sequence (empty if valid).

    Checks the two invariants the chat API enforces:
    - content must be a string or a content-block list
    - every assistant tool_calls entry must be answered by a tool response
      (role "tool", or role "user" with tool_call_id for vision outputs) before
      any other message follows
    """
    errors = []
    pending: List[str] = []
    for i, msg in enumerate(messages):
        content = msg.get("content")
        if content is not None and not isinstance(content, (str, list)):
            errors.append(f"messages[{i}]: content is {type(content).__name__}, expected str or list")

        tool_call_id = msg.get("tool_call_id")
        if tool_call_id and msg.get("role") in ("tool", "user"):
            if tool_call_id in pending:
                pending.remove(tool_call_id)
            else:
                errors.append(f"messages[{i}]: tool response without matching tool_call")
            continue

        if pending:
            errors.append(f"messages[{i}]: {msg.get('role')} message arrived before tool responses to {pending}")
            pending = []

        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            pending = [tc.get("id") for tc in msg["tool_calls"]]

    if pending:
        errors.append(f"unanswered tool_calls at end of history: {pending}")
    return errors


def load_messages(session_id: int) -> List[Dict]:
    """Load all messages for a given session in insertion order."""
    conn = _get_conn()
    cursor = conn.cursor()

    # Order by id, not timestamp: timestamps can tie (same-second inserts),
    # which makes the ordering of tool_calls vs tool responses nondeterministic.
    cursor.execute("""
        SELECT role, content, tool_calls, tool_call_id, reasoning_content
        FROM messages
        WHERE session_id = ?
        ORDER BY id ASC
    """, (session_id,))
    
    messages = []
    for row in cursor.fetchall():
        content_str = str(row[1]) if row[1] is not None else ""
        content = content_str
        try:
            parsed = json.loads(content_str)
            # Only restore structured content for vision-style content-block
            # lists (e.g. [{"type": "text", ...}, {"type": "image_url", ...}]).
            # Any other JSON value (a tool result that happens to be valid JSON,
            # like a package.json dump) must stay a plain string, or the API
            # rejects it with "content should be a string or a list".
            if (isinstance(parsed, list) and parsed
                    and all(isinstance(item, dict) and "type" in item for item in parsed)):
                content = parsed
        except (json.JSONDecodeError, TypeError):
            pass

        message = {
            "role": str(row[0]) if row[0] is not None else "user",
            "content": content,
        }
        
        # Parse tool_calls from JSON if present
        if row[2]:
            try:
                message["tool_calls"] = json.loads(row[2])
            except (json.JSONDecodeError, TypeError):
                message["tool_calls"] = None
        
        # Add tool_call_id if present
        if row[3]:
            message["tool_call_id"] = str(row[3])

        # Restore reasoning_content if present (DeepSeek thinking mode)
        if row[4]:
            message["reasoning_content"] = str(row[4])
        
        # Skip empty messages (no content, no tool_calls, no tool_call_id)
        if not message.get("content") and not message.get("tool_calls") and not message.get("tool_call_id"):
            continue
        
        messages.append(message)

    conn.close()
    return repair_message_sequence(messages)


def delete_chat(chat_id: int):
    """Delete a chat and all its associated sessions and messages."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    # Delete messages for all sessions in this chat
    cursor.execute("""
        DELETE FROM messages
        WHERE session_id IN (SELECT id FROM sessions WHERE chat_id = ?)
    """, (chat_id,))
    
    # Delete sessions for this chat
    cursor.execute("""
        DELETE FROM sessions
        WHERE chat_id = ?
    """, (chat_id,))
    
    # Delete the chat itself
    cursor.execute("""
        DELETE FROM chats
        WHERE id = ?
    """, (chat_id,))
    
    conn.commit()
    conn.close()


def get_session_role(session_id: int) -> Optional[str]:
    """Get the role associated with a session by joining sessions -> chats."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.role FROM chats c
        JOIN sessions s ON s.chat_id = c.id
        WHERE s.id = ?
    """, (session_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def is_subagent_session(session_id: int) -> bool:
    """Check if a session is a subagent session (has a parent_session_id)."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT parent_session_id FROM sessions WHERE id = ?
    """, (session_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None and result[0] is not None


def get_child_sessions(parent_session_id: int) -> List[Dict]:
    """Get all child (subagent) sessions for a given parent session, ordered by id ASC."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, chat_id, parent_session_id
        FROM sessions
        WHERE parent_session_id = ?
        ORDER BY id ASC
    """, (parent_session_id,))
    sessions = []
    for row in cursor.fetchall():
        sessions.append({
            "id": row[0],
            "chat_id": row[1],
            "parent_session_id": row[2],
        })
    conn.close()
    return sessions


def get_child_session_by_toolcall(parent_session_id: int, toolcall_id: str) -> Optional[Dict]:
    """Get the child (subagent) session matching a specific toolcall_id."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, chat_id, parent_session_id, toolcall_id
        FROM sessions
        WHERE parent_session_id = ? AND toolcall_id = ?
        LIMIT 1
    """, (parent_session_id, toolcall_id))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "chat_id": row[1],
        "parent_session_id": row[2],
        "toolcall_id": row[3],
    }


def resolve_session_id(session_id: int) -> int:
    """Follow the redirect_session_id chain to find the active session.

    Returns the session_id itself if it has no redirect.
    """
    conn = _get_conn()
    cursor = conn.cursor()
    current_id = session_id
    visited = set()
    try:
        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            cursor.execute(
                "SELECT redirect_session_id FROM sessions WHERE id = ?",
                (current_id,),
            )
            result = cursor.fetchone()
            if result and result[0] is not None:
                current_id = result[0]
            else:
                break
    finally:
        conn.close()
    return current_id


def get_session_info(session_id: int) -> Optional[Dict]:
    """Get session metadata: parent_session_id, toolcall_id, and depth."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT parent_session_id, toolcall_id, depth FROM sessions WHERE id = ?",
        (session_id,),
    )
    result = cursor.fetchone()
    conn.close()
    if not result:
        return None
    return {
        "parent_session_id": result[0],
        "toolcall_id": result[1],
        "depth": result[2] or 0,
    }


def is_session_finished(session_id: int) -> bool:
    """Check if a session has completed (last message is an assistant response without tool_calls).

    Follows the redirect chain to check the active session.
    """
    active_id = resolve_session_id(session_id)
    messages = load_messages(active_id)
    if not messages:
        return False
    last_msg = messages[-1]
    return last_msg.get("role") == "assistant" and not last_msg.get("tool_calls")


def add_change(prompt_id: str, role: str, session_id: Optional[int], change_type: str, 
                file_path: Optional[str], description: str, details: Optional[str] = None) -> int:
    """Add a change record to the database and return its ID."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO changes (prompt_id, role, session_id, change_type, file_path, description, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (prompt_id, role, session_id, change_type, file_path, description, details))
    
    change_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return change_id


def get_changes_by_prompt(prompt_id: str) -> List[Dict]:
    """Get all changes for a specific prompt ID."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, prompt_id, role, session_id, change_type, file_path, description, details, timestamp
        FROM changes
        WHERE prompt_id = ?
        ORDER BY timestamp ASC
    """, (prompt_id,))
    
    changes = []
    for row in cursor.fetchall():
        changes.append({
            "id": row[0],
            "prompt_id": row[1],
            "role": row[2],
            "session_id": row[3],
            "change_type": row[4],
            "file_path": row[5],
            "description": row[6],
            "details": row[7],
            "timestamp": row[8]
        })
    
    conn.close()
    return changes


def get_all_changes(limit: Optional[int] = None, offset: int = 0) -> List[Dict]:
    """Get all changes globally, optionally with pagination."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    query = """
        SELECT id, prompt_id, role, session_id, change_type, file_path, description, details, timestamp
        FROM changes
        ORDER BY timestamp DESC
    """
    
    if limit:
        query += f" LIMIT {limit} OFFSET {offset}"
    
    cursor.execute(query)
    
    changes = []
    for row in cursor.fetchall():
        changes.append({
            "id": row[0],
            "prompt_id": row[1],
            "role": row[2],
            "session_id": row[3],
            "change_type": row[4],
            "file_path": row[5],
            "description": row[6],
            "details": row[7],
            "timestamp": row[8]
        })
    
    conn.close()
    return changes


def get_changes_by_role(role: str, limit: Optional[int] = None) -> List[Dict]:
    """Get all changes for a specific role."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    query = """
        SELECT id, prompt_id, role, session_id, change_type, file_path, description, details, timestamp
        FROM changes
        WHERE role = ?
        ORDER BY timestamp DESC
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    cursor.execute(query, (role,))
    
    changes = []
    for row in cursor.fetchall():
        changes.append({
            "id": row[0],
            "prompt_id": row[1],
            "role": row[2],
            "session_id": row[3],
            "change_type": row[4],
            "file_path": row[5],
            "description": row[6],
            "details": row[7],
            "timestamp": row[8]
        })
    
    conn.close()
    return changes


def get_changes_by_session(session_id: int) -> List[Dict]:
    """Get all changes for a specific session."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, prompt_id, role, session_id, change_type, file_path, description, details, timestamp
        FROM changes
        WHERE session_id = ?
        ORDER BY timestamp ASC
    """, (session_id,))
    
    changes = []
    for row in cursor.fetchall():
        changes.append({
            "id": row[0],
            "prompt_id": row[1],
            "role": row[2],
            "session_id": row[3],
            "change_type": row[4],
            "file_path": row[5],
            "description": row[6],
            "details": row[7],
            "timestamp": row[8]
        })
    
    conn.close()
    return changes


def get_all_changes_by_session_chain(session_id: int) -> List[Dict]:
    """Get all changes across the session redirect chain.

    When a session is handed over, changes are recorded on different sessions
    in the chain. This function gathers them all.
    """
    conn = _get_conn()
    cursor = conn.cursor()

    # Collect all session IDs in the redirect chain
    session_ids = [session_id]
    current_id = session_id
    visited = set()
    try:
        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            cursor.execute(
                "SELECT redirect_session_id FROM sessions WHERE id = ?",
                (current_id,),
            )
            result = cursor.fetchone()
            if result and result[0] is not None:
                current_id = result[0]
                session_ids.append(current_id)
            else:
                break
    finally:
        conn.close()

    all_changes = []
    for sid in session_ids:
        all_changes.extend(get_changes_by_session(sid))

    all_changes.sort(key=lambda c: c.get("timestamp", ""))
    return all_changes


def create_todo_list(session_id: int) -> int:
    """Create a new todo list for a session and return its ID."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO todo_lists (session_id, status)
        VALUES (?, 'pending')
    """, (session_id,))
    
    todo_list_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return todo_list_id


def add_todo_task(todo_list_id: int, goal: str, requirements: Optional[str] = None,
                  notes: Optional[str] = None, order_index: int = None,
                  context: Optional[str] = None, insert_after: Optional[int] = None) -> int:
    """Add a task to a todo list and return its ID.

    Position is controlled by insert_after (1-based display number):
    - insert_after omitted / None → append at end
    - insert_after = 0 → insert at the beginning (before task 1)
    - insert_after = N → insert after task N (shifts subsequent tasks down)

    order_index is deprecated and ignored if insert_after is provided.
    """
    conn = _get_conn()
    cursor = conn.cursor()

    if insert_after is not None:
        # Get current tasks ordered by order_index to map display number → order_index
        cursor.execute("""
            SELECT order_index FROM todo_tasks
            WHERE todo_list_id = ?
            ORDER BY order_index ASC
        """, (todo_list_id,))
        rows = cursor.fetchall()

        if not rows:
            # Empty list   insert at index 0
            new_order_index = 0
        elif insert_after >= len(rows):
            # Insert after the last task   append at end
            new_order_index = rows[-1][0] + 1
        elif insert_after <= 0:
            # Insert at the beginning
            new_order_index = rows[0][0]
            cursor.execute("""
                UPDATE todo_tasks SET order_index = order_index + 1
                WHERE todo_list_id = ?
            """, (todo_list_id,))
        else:
            # Insert after task N (1-based): get the order_index of the Nth task
            target_order_index = rows[insert_after - 1][0]
            new_order_index = target_order_index + 1
            # Shift all tasks after the target down by 1
            cursor.execute("""
                UPDATE todo_tasks SET order_index = order_index + 1
                WHERE todo_list_id = ? AND order_index > ?
            """, (todo_list_id, target_order_index))
    elif order_index is not None:
        # Legacy: explicit order_index with auto-shift
        cursor.execute("""
            UPDATE todo_tasks SET order_index = order_index + 1
            WHERE todo_list_id = ? AND order_index >= ?
        """, (todo_list_id, order_index))
        new_order_index = order_index
    else:
        # Default: append at end
        cursor.execute("""
            SELECT MAX(order_index) FROM todo_tasks WHERE todo_list_id = ?
        """, (todo_list_id,))
        result = cursor.fetchone()
        new_order_index = (result[0] + 1) if result and result[0] is not None else 0

    cursor.execute("""
        INSERT INTO todo_tasks (todo_list_id, goal, requirements, notes, context, status, order_index)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
    """, (todo_list_id, goal, requirements, notes, context, new_order_index))

    task_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return task_id


def get_todo_list(todo_list_id: int) -> Optional[Dict]:
    """Get a todo list by ID."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, session_id, status, created_at, updated_at
        FROM todo_lists
        WHERE id = ?
    """, (todo_list_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            "id": result[0],
            "session_id": result[1],
            "status": result[2],
            "created_at": result[3],
            "updated_at": result[4]
        }
    return None


def get_todo_tasks(todo_list_id: int) -> List[Dict]:
    """Get all tasks for a todo list, ordered by order_index."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, goal, requirements, notes, context, status, order_index, toolcall_id, cancel_reason, created_at, updated_at
        FROM todo_tasks
        WHERE todo_list_id = ?
        ORDER BY order_index ASC
    """, (todo_list_id,))
    
    tasks = []
    for row in cursor.fetchall():
        tasks.append({
            "id": row[0],
            "goal": row[1],
            "requirements": row[2],
            "notes": row[3],
            "context": row[4],
            "status": row[5],
            "order_index": row[6],
            "toolcall_id": row[7],
            "cancel_reason": row[8],
            "created_at": row[9],
            "updated_at": row[10]
        })
    
    conn.close()
    return tasks


def get_active_todo_list(session_id: int) -> Optional[Dict]:
    """Get the active (pending or approved) todo list for a session."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, session_id, status, created_at, updated_at
        FROM todo_lists
        WHERE session_id = ? AND status IN ('pending', 'approved')
        ORDER BY id DESC
        LIMIT 1
    """, (session_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            "id": result[0],
            "session_id": result[1],
            "status": result[2],
            "created_at": result[3],
            "updated_at": result[4]
        }
    return None


def get_todo_task(task_id: int) -> Optional[Dict]:
    """Get a single todo task by ID, including its parent todo_list_id.

    Returns the full task dict (same shape as get_next_pending_task rows)
    or None if no task exists with the given ID.
    """
    conn = _get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, todo_list_id, goal, requirements, notes, context, status, order_index, toolcall_id, cancel_reason, created_at, updated_at
        FROM todo_tasks
        WHERE id = ?
    """, (task_id,))

    result = cursor.fetchone()
    conn.close()

    if result:
        return {
            "id": result[0],
            "todo_list_id": result[1],
            "goal": result[2],
            "requirements": result[3],
            "notes": result[4],
            "context": result[5],
            "status": result[6],
            "order_index": result[7],
            "toolcall_id": result[8],
            "cancel_reason": result[9],
            "created_at": result[10],
            "updated_at": result[11]
        }
    return None


def get_chat_id_for_session(session_id: int) -> Optional[int]:
    """Get the chat_id associated with a session."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT chat_id FROM sessions WHERE id = ?
    """, (session_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def migrate_todo_lists(old_session_id: int, new_session_id: int):
    """Move all todo lists from old_session_id to new_session_id (used during handover)."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE todo_lists
        SET session_id = ?, updated_at = CURRENT_TIMESTAMP
        WHERE session_id = ?
    """, (new_session_id, old_session_id))
    conn.commit()
    conn.close()


def update_todo_list_status(todo_list_id: int, status: str):
    """Update the status of a todo list."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE todo_lists
        SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (status, todo_list_id))
    
    conn.commit()
    conn.close()


def update_task_status(task_id: int, status: str, cancel_reason: Optional[str] = None):
    """Update the status of a task. Optionally store a cancel_reason when cancelling."""
    conn = _get_conn()
    cursor = conn.cursor()

    if cancel_reason is not None:
        cursor.execute("""
            UPDATE todo_tasks
            SET status = ?, cancel_reason = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, cancel_reason, task_id))
    else:
        cursor.execute("""
            UPDATE todo_tasks
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, task_id))

    conn.commit()
    conn.close()


def delete_todo_list(todo_list_id: int):
    """Delete a todo list and all its tasks."""
    conn = _get_conn()
    cursor = conn.cursor()

    # Delete all tasks first
    cursor.execute("""
        DELETE FROM todo_tasks
        WHERE todo_list_id = ?
    """, (todo_list_id,))

    # Delete the todo list itself
    cursor.execute("""
        DELETE FROM todo_lists
        WHERE id = ?
    """, (todo_list_id,))

    conn.commit()
    conn.close()


def get_next_pending_task(todo_list_id: int) -> Optional[Dict]:
    """Get the next pending or in_progress task for a todo list.

    Returns in_progress tasks first (for crash recovery resumption),
    then pending tasks.
    """
    conn = _get_conn()
    cursor = conn.cursor()

    # Check for an in_progress task first (crash recovery)
    cursor.execute("""
        SELECT id, goal, requirements, notes, context, status, order_index, toolcall_id, cancel_reason, created_at, updated_at
        FROM todo_tasks
        WHERE todo_list_id = ? AND status = 'in_progress'
        ORDER BY order_index ASC
        LIMIT 1
    """, (todo_list_id,))

    result = cursor.fetchone()

    if not result:
        # No in_progress task   get the next pending one
        cursor.execute("""
            SELECT id, goal, requirements, notes, context, status, order_index, toolcall_id, cancel_reason, created_at, updated_at
            FROM todo_tasks
            WHERE todo_list_id = ? AND status = 'pending'
            ORDER BY order_index ASC
            LIMIT 1
        """, (todo_list_id,))

        result = cursor.fetchone()

    conn.close()

    if result:
        return {
            "id": result[0],
            "goal": result[1],
            "requirements": result[2],
            "notes": result[3],
            "context": result[4],
            "status": result[5],
            "order_index": result[6],
            "toolcall_id": result[7],
            "cancel_reason": result[8],
            "created_at": result[9],
            "updated_at": result[10]
        }
    return None


def set_task_toolcall_id(task_id: int, toolcall_id: str):
    """Store the toolcall_id used when starting a task, for crash recovery resumption."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE todo_tasks SET toolcall_id = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (toolcall_id, task_id))
    conn.commit()
    conn.close()


def record_session_file(session_id: int, file_path: str, operation: str):
    """Record a file modification in a session."""
    conn = _get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO session_files (session_id, file_path, operation)
        VALUES (?, ?, ?)
    """, (session_id, file_path, operation))

    conn.commit()
    conn.close()


def get_session_files(session_id: int) -> List[Dict]:
    """Get all file modifications recorded for a session, ordered by timestamp."""
    conn = _get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, session_id, file_path, operation, timestamp
        FROM session_files
        WHERE session_id = ?
        ORDER BY timestamp ASC
    """, (session_id,))

    files = []
    for row in cursor.fetchall():
        files.append({
            "id": row[0],
            "session_id": row[1],
            "file_path": row[2],
            "operation": row[3],
            "timestamp": row[4]
        })

    conn.close()
    return files


def get_all_session_files_chain(session_id: int) -> List[Dict]:
    """Get all file modifications across the session redirect chain.

    When a session is handed over, file modifications are recorded on different
    sessions in the chain. This function gathers them all.
    """
    conn = _get_conn()
    cursor = conn.cursor()

    session_ids = [session_id]
    current_id = session_id
    visited = set()
    try:
        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            cursor.execute(
                "SELECT redirect_session_id FROM sessions WHERE id = ?",
                (current_id,),
            )
            result = cursor.fetchone()
            if result and result[0] is not None:
                current_id = result[0]
                session_ids.append(current_id)
            else:
                break
    finally:
        conn.close()

    all_files = []
    for sid in session_ids:
        all_files.extend(get_session_files(sid))

    all_files.sort(key=lambda f: f.get("timestamp", ""))
    return all_files


def get_old_session_ids(chat_id: int, active_session_id: int) -> List[int]:
    """Get session IDs for a chat that precede the active session, ordered oldest first.

    These are sessions whose messages should be displayed as read-only context
    but NOT included in the agent's chat_history.
    """
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM sessions
        WHERE chat_id = ? AND id != ? AND parent_session_id IS NULL
        ORDER BY id ASC
    """, (chat_id, active_session_id))
    session_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return session_ids


def set_redirect_session_id(session_id: int, redirect_session_id: int):
    """Set the redirect_session_id on a session, pointing to the new active session."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE sessions
        SET redirect_session_id = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (redirect_session_id, session_id))
    conn.commit()
    conn.close()


def get_session_thinking_mode(session_id: int) -> Optional[int]:
    """Get the thinking mode stored on a session."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT effort FROM sessions WHERE id = ?", (session_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def set_session_thinking_mode(session_id: int, thinking_mode: int):
    """Set the thinking mode on a session."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET effort = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (thinking_mode, session_id))
    conn.commit()
    conn.close()


def get_session_depth(session_id: int) -> int:
    """Get the depth stored on a session (0 for main sessions, increments for subagents)."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT depth FROM sessions WHERE id = ?", (session_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result and result[0] is not None else 0


def get_redirect_session_id(session_id: int) -> Optional[int]:
    """Get the redirect_session_id for a session, if any."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT redirect_session_id FROM sessions WHERE id = ?
    """, (session_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result and result[0] is not None else None


def get_active_session(chat_id: int) -> Optional[int]:
    """Get the active session for a chat by following the redirect chain.

    Returns the latest session that does NOT have a redirect_session_id set,
    or the session at the end of the redirect chain.
    """
    conn = _get_conn()
    cursor = conn.cursor()

    # Get the latest main-agent session for this chat (exclude subagent sessions)
    cursor.execute("""
        SELECT id, redirect_session_id FROM sessions
        WHERE chat_id = ? AND parent_session_id IS NULL
        ORDER BY id DESC
        LIMIT 1
    """, (chat_id,))
    result = cursor.fetchone()
    conn.close()

    if not result:
        return None

    session_id = result[0]
    redirect_id = result[1]

    # Follow the redirect chain
    visited = set()
    while redirect_id is not None and redirect_id not in visited:
        visited.add(redirect_id)
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, redirect_session_id FROM sessions WHERE id = ?
        """, (redirect_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            break
        session_id = row[0]
        redirect_id = row[1]

    return session_id


def save_handover(session_id: int, new_session_id: int, handover_text: str,
                  token_usage: Optional[int] = None, context_window: Optional[int] = None) -> int:
    """Save a handover record to the database and return its ID."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO handovers (session_id, new_session_id, handover_text, token_usage, context_window)
        VALUES (?, ?, ?, ?, ?)
    """, (session_id, new_session_id, handover_text, token_usage, context_window))
    handover_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return handover_id


def get_handover(handover_id: int) -> Optional[Dict]:
    """Get a handover record by ID."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, session_id, new_session_id, handover_text, token_usage, context_window, created_at
        FROM handovers
        WHERE id = ?
    """, (handover_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "session_id": row[1],
        "new_session_id": row[2],
        "handover_text": row[3],
        "token_usage": row[4],
        "context_window": row[5],
        "created_at": row[6],
    }


def get_handovers_by_session(session_id: int) -> List[Dict]:
    """Get all handover records for a given session."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, session_id, new_session_id, handover_text, token_usage, context_window, created_at
        FROM handovers
        WHERE session_id = ?
        ORDER BY created_at ASC
    """, (session_id,))
    handovers = []
    for row in cursor.fetchall():
        handovers.append({
            "id": row[0],
            "session_id": row[1],
            "new_session_id": row[2],
            "handover_text": row[3],
            "token_usage": row[4],
            "context_window": row[5],
            "created_at": row[6],
        })
    conn.close()
    return handovers


def get_root_session_id(session_id: int) -> int:
    """Traverse up the parent_session_id chain to find the root session.

    Returns the session_id itself if it has no parent.
    """
    conn = _get_conn()
    cursor = conn.cursor()
    current_id = session_id
    visited = set()
    try:
        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            cursor.execute(
                "SELECT parent_session_id FROM sessions WHERE id = ?",
                (current_id,),
            )
            result = cursor.fetchone()
            if result and result[0] is not None:
                current_id = result[0]
            else:
                break
    finally:
        conn.close()
    return current_id


def is_global_todo_enabled(session_id: int) -> bool:
    """Check if globalTodo is enabled for the role associated with this session."""
    role = get_session_role(session_id)
    if not role:
        return False
    from Agent.config import load_roles
    roles = load_roles()
    return roles.get(role, {}).get("globalTodo", False)


def resolve_todo_session_id(session_id: int) -> int:
    """If globalTodo is enabled, return the root session ID; otherwise return session_id."""
    if is_global_todo_enabled(session_id):
        return get_root_session_id(session_id)
    return session_id


# -- command whitelist ------------------------------------------------------

def get_command_whitelist(role: str) -> List[str]:
    """Return the list of whitelisted shell commands for a role."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT command FROM command_whitelist WHERE role = ? ORDER BY command",
        (role,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


def add_to_command_whitelist(role: str, command: str) -> bool:
    """Add a command to the role's whitelist. Returns True if inserted, False if it already existed."""
    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO command_whitelist (role, command) VALUES (?, ?)",
            (role, command),
        )
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_from_command_whitelist(role: str, command: str) -> bool:
    """Remove a command from the role's whitelist. Returns True if a row was deleted."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM command_whitelist WHERE role = ? AND command = ?",
        (role, command),
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def is_command_whitelisted(role: str, command: str) -> bool:
    """True when the exact command string is in the role's whitelist."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM command_whitelist WHERE role = ? AND command = ?",
        (role, command),
    )
    found = cursor.fetchone() is not None
    conn.close()
    return found


def clear_command_whitelist(role: str) -> int:
    """Remove all whitelisted commands for a role. Returns the number of rows deleted."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM command_whitelist WHERE role = ?",
        (role,),
    )
    conn.commit()
    deleted = cursor.rowcount
    conn.close()
    return deleted
