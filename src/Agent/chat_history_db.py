import sqlite3
import sys
import json
import re
from pathlib import Path
from typing import List, Dict, Optional
from prompt_toolkit import prompt


DB_PATH = Path(".raggie/.raggie.chat")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Initialize the chat history database with required tables."""
    # Ensure parent directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            parent_session_id INTEGER,
            redirect_session_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (redirect_session_id) REFERENCES sessions(id) ON DELETE SET NULL
        )
    """)

    # Migrate old sessions table: add redirect_session_id column if missing
    cursor.execute("PRAGMA table_info(sessions)")
    session_columns = [col[1] for col in cursor.fetchall()]
    if "redirect_session_id" not in session_columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN redirect_session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_calls TEXT,
            tool_call_id TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(role, name)
        )
    """)

    # Migrate old schema (role as PRIMARY KEY, no name column) to new schema
    cursor.execute("PRAGMA table_info(skills)")
    columns = [col[1] for col in cursor.fetchall()]
    if "name" not in columns and "role" in columns:
        cursor.execute("ALTER TABLE skills RENAME TO skills_old")
        cursor.execute("""
            CREATE TABLE skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                name TEXT NOT NULL,
                content TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(role, name)
            )
        """)
        cursor.execute("""
            INSERT INTO skills (role, name, content, updated_at)
            SELECT role, role, content, updated_at FROM skills_old
        """)
        cursor.execute("DROP TABLE skills_old")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_id TEXT NOT NULL,
            role TEXT NOT NULL,
            session_id INTEGER,
            change_type TEXT NOT NULL,
            file_path TEXT,
            description TEXT,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS todo_lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS todo_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            todo_list_id INTEGER NOT NULL,
            goal TEXT NOT NULL,
            requirements TEXT,
            notes TEXT,
            context TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            order_index INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (todo_list_id) REFERENCES todo_lists(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            operation TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS handovers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            new_session_id INTEGER,
            handover_text TEXT NOT NULL,
            token_usage INTEGER,
            context_window INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (new_session_id) REFERENCES sessions(id) ON DELETE SET NULL
        )
    """)
    
    conn.commit()
    conn.close()


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
    """Generate a title from a user message (first 50 chars + ... if longer)."""
    if not message:
        return "Untitled"
    
    # Remove leading/trailing whitespace
    message = message.strip()
    
    # Take first 50 characters
    if len(message) <= 50:
        return message
    else:
        return message[:50] + "..."


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


def create_session(chat_id: int, parent_session_id: Optional[int] = None) -> int:
    """Create a new session for a given chat and return its ID."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO sessions (chat_id, parent_session_id)
        VALUES (?, ?)
    """, (chat_id, parent_session_id))
    
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return session_id


def get_latest_session(chat_id: int) -> Optional[int]:
    """Get the most recent session ID for a given chat, or None if no sessions exist."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id FROM sessions
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (chat_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else None


def get_or_create_session(chat_id: int, parent_session_id: Optional[int] = None) -> int:
    """Get the active session for a chat (following redirects), or create one if none exists."""
    session_id = get_active_session(chat_id)
    if session_id is None:
        session_id = create_session(chat_id, parent_session_id)
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
        content = str(content)
    else:
        content = ""
    
    tool_calls = message.get("tool_calls")
    tool_call_id = message.get("tool_call_id")
    if tool_call_id is not None:
        tool_call_id = str(tool_call_id)
    
    # Convert tool_calls to JSON string if present
    tool_calls_json = json.dumps(tool_calls) if tool_calls else None
    
    cursor.execute("""
        INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id)
        VALUES (?, ?, ?, ?, ?)
    """, (session_id, role, content, tool_calls_json, tool_call_id))
    
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


def load_messages(session_id: int) -> List[Dict]:
    """Load all messages for a given session, ordered by timestamp."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT role, content, tool_calls, tool_call_id
        FROM messages
        WHERE session_id = ?
        ORDER BY timestamp ASC
    """, (session_id,))
    
    messages = []
    for row in cursor.fetchall():
        message = {
            "role": str(row[0]) if row[0] is not None else "user",
            "content": str(row[1]) if row[1] is not None else "",
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
        
        # Skip empty messages (no content, no tool_calls, no tool_call_id)
        if not message.get("content") and not message.get("tool_calls") and not message.get("tool_call_id"):
            continue
        
        messages.append(message)
    
    conn.close()
    return messages


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
                  notes: Optional[str] = None, order_index: int = 0,
                  context: Optional[str] = None) -> int:
    """Add a task to a todo list and return its ID."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO todo_tasks (todo_list_id, goal, requirements, notes, context, status, order_index)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
    """, (todo_list_id, goal, requirements, notes, context, order_index))
    
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
        SELECT id, goal, requirements, notes, context, status, order_index, created_at, updated_at
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
            "created_at": row[7],
            "updated_at": row[8]
        })
    
    conn.close()
    return tasks


def get_active_todo_list(session_id: int) -> Optional[Dict]:
    """Get the active (pending, in_progress, or rejected) todo list for a session."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, session_id, status, created_at, updated_at
        FROM todo_lists
        WHERE session_id = ? AND status IN ('pending', 'in_progress', 'rejected')
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


def get_active_todo_list_for_chat(chat_id: int) -> Optional[Dict]:
    """Get the active (pending, in_progress, or rejected) todo list for a chat.

    Looks across all sessions belonging to the chat, so todo lists
    created in a previous session (before handover or restart) are
    still found for resumption.
    """
    conn = _get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT tl.id, tl.session_id, tl.status, tl.created_at, tl.updated_at
        FROM todo_lists tl
        JOIN sessions s ON tl.session_id = s.id
        WHERE s.chat_id = ? AND tl.status IN ('pending', 'in_progress', 'rejected')
        ORDER BY tl.id DESC
        LIMIT 1
    """, (chat_id,))

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


def update_task_status(task_id: int, status: str):
    """Update the status of a task."""
    conn = _get_conn()
    cursor = conn.cursor()
    
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
    """Get the next pending task for a todo list."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, goal, requirements, notes, context, status, order_index, created_at, updated_at
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
            "created_at": result[7],
            "updated_at": result[8]
        }
    return None


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


def get_old_session_ids(chat_id: int, active_session_id: int) -> List[int]:
    """Get session IDs for a chat that precede the active session, ordered oldest first.

    These are sessions whose messages should be displayed as read-only context
    but NOT included in the agent's chat_history.
    """
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM sessions
        WHERE chat_id = ? AND id != ?
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

    # Get the latest session for this chat
    cursor.execute("""
        SELECT id, redirect_session_id FROM sessions
        WHERE chat_id = ?
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
