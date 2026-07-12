import os
import json
import shutil
import platform
from datetime import date

from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown

from .config import load_roles, load_tools, load_keys
from .tools import ToolRegistry
from .command import CommandRegistry
from .chat_history_db import init_db, get_or_create_session, load_messages, save_message, update_chat_title, generate_title, get_active_todo_list, get_todo_tasks, create_session, set_redirect_session_id, save_handover, get_old_session_ids, is_subagent_session, get_session_effort, get_session_info, resolve_session_id, migrate_todo_lists
from .git_manager import GitManager
from skills import SkillManager
from indexing.code_index_sdk import CodeIndexSDK


def _tool_summary(name, args):
    parts = [f"{k}: {str(v)[:60]}" for k, v in args.items()]
    return f"{name}   {' '.join(parts)}"


class Agent:

    def __init__(self, role, chat_id=None, session_id=None, debug=False):
        self.roles = load_roles()
        self.tools = load_tools()
        self.tool_registry = ToolRegistry()
        self.tool_registry.agent_role = role
        self.command_registry = CommandRegistry()

        self.agent_role = role
        self.debug = debug
        self.console = Console()

        if role not in self.roles:
            raise ValueError(f"Role '{role}' is not defined in roles.json")

        base_url = self.roles[role].get("base_url", "")
        if not base_url:
            raise ValueError(f"No base_url found for role '{role}' in roles")

        keys = load_keys()
        api_key = keys.get(base_url, "")
        if not api_key:
            raise ValueError(
                f"No API key found for base_url '{base_url}' in your keys. make sure you used the correct urls in roles and keys section when you ran `raggie setup` "
                f"If your model doesn't require a key (e.g. local AI), set it to 'nokey'."
            )


        self.client = OpenAI(api_key=api_key, base_url=base_url)

        self.reasoning = self.roles[role].get("reasoning", False)
        self.streaming = self.roles[role].get("stream", False)

        self.system_prompt = self._build_system_prompt(role)

        # Initialize database
        init_db()

        # Set chat_id
        self.chat_id = chat_id

        # Get or create session for this chat
        if session_id is None and chat_id is not None:
            self.session_id = get_or_create_session(chat_id, parent_session_id=None)
        elif session_id is not None:
            self.session_id = resolve_session_id(session_id)
        else:
            raise ValueError("Either chat_id or session_id must be provided")

        # Load chat history from database
        self.chat_history = load_messages(self.session_id)

        # Track if this is a new session (no messages yet)
        self.is_new_session = len(self.chat_history) == 0

        # Track if this is a subagent session (skip git commit on finish)
        self.is_subagent = is_subagent_session(self.session_id)

        # Inject system prompt if not already present (for new sessions)
        if self.is_new_session or not any(msg.get("role") == "system" for msg in self.chat_history):
            self.chat_history.insert(0, {"role": "system", "content": self.system_prompt})

        # Initialize code indexer for tracking changes
        self.code_indexer = CodeIndexSDK(
            db_path=".raggie/.code_index.raggie",
            root_dir=os.getcwd()
        )

        # Share code indexer with tool registry for selective re-indexing
        self.tool_registry.code_indexer = self.code_indexer

        # Initialize git manager for commit/undo/redo operations
        self.git_manager = GitManager(root_dir=os.getcwd())

        # Index the codebase at the start of each conversation
        try:
            with self.console.status("[bold green]Indexing codebase...", spinner="dots"):
                self.code_indexer.index_directory()
        except (KeyboardInterrupt, EOFError):
            self.console.print("\n[yellow]Indexing interrupted. Using existing index.[/yellow]")
            self.code_indexer._connect()

        # Display previous chat history if it exists (skip for subagents — they
        # share the chat_id but don't need the parent's conversation printed)
        if self.chat_history and not self.is_subagent:
            self._display_chat_history()
        
        # Check for incomplete todo list and offer resumption
        self._check_incomplete_todo_list()



    def _build_system_prompt(self, role):
        """Build the system prompt from file or direct prompt, including skills."""
        from Tools.utils import RED, RESET
        role_system_prompt = ""

        # Load system prompt from file if specified, otherwise use direct prompt
        if "system_prompt_file" in self.roles[role]:
            prompt_file_name = self.roles[role]["system_prompt_file"]
            # Resolve relative paths to ~/.config/raggie, absolute paths as-is
            if os.path.isabs(prompt_file_name):
                prompt_file_path = prompt_file_name
            else:
                from Agent.config import USER_CONFIG_DIR, DEFAULT_CONFIG_DIR
                # Use just the basename so old paths like "src/config/foo.md" still resolve
                base_name = os.path.basename(prompt_file_name)
                prompt_file_path = USER_CONFIG_DIR / base_name
                # Copy from source defaults if not present in user config
                if not prompt_file_path.exists():
                    default_path = DEFAULT_CONFIG_DIR / base_name
                    if default_path.exists():
                        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(default_path, prompt_file_path)
            
            try:
                with open(prompt_file_path, 'r', encoding='utf-8') as f:
                    role_system_prompt = f.read()
            except FileNotFoundError:
                raise ValueError(f"System prompt file not found: {prompt_file_path}")
        else:
            role_system_prompt = self.roles[role]["system_prompt"]
        
        system_prompt = f"{role_system_prompt}\n\ntoday is {date.today()} current directory is {os.getcwd()} and the host system is \"{str(platform.uname())}\""
        
        # Advertise all available skills as brief summaries in the system prompt
        skill_manager = SkillManager()
        all_skills = skill_manager.list_skills()
        if all_skills:
            skills_section = "## Available Skills\n\nThe following skills are available. Use the GetSkill tool with the skill name to fetch the full skill content before working with it. (this will have instructions for you so you can operate better)\n\n"
            for skill in all_skills:
                skills_section += f"- **{skill['role']}/{skill['name']}**: {skill['summary']}\n"
            system_prompt = f"{system_prompt}\n\n{skills_section}"
        
        # Optionally load AGENTS.md if it exists in the project root (cwd)
        agents_md_path = os.path.join(os.getcwd(), "AGENTS.md")
        if os.path.exists(agents_md_path):
            try:
                with open(agents_md_path, 'r', encoding='utf-8') as f:
                    agents_content = f.read().strip()
                if agents_content:
                    system_prompt = f"{system_prompt}\n\n{agents_content}"
            except Exception as e:
                print(f"{RED}Warning: Failed to read AGENTS.md: {e}{RESET}")
        
        return system_prompt



    def _display_chat_history(self):
        """Display the previous chat history to the user."""
        G = "\033[32m"
        B = "\033[34m"
        R = "\033[0m"
        DIM = "\033[2m"

        # Display messages from old (handed-over) sessions as read-only text
        old_session_ids = get_old_session_ids(self.chat_id, self.session_id)
        for old_sid in old_session_ids:
            old_messages = load_messages(old_sid)
            if not old_messages:
                continue
            print(f"\n{DIM}--- Session #{old_sid} (handed over, not in context) ---{R}")
            for msg in old_messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if role == "system" and not self.debug:
                    continue
                if role == "user" and content:
                    print(f"{DIM}You: {content}{R}")
                elif role == "assistant":
                    if content:
                        print(f"{DIM}Agent: {content}{R}")
                    if msg.get("tool_calls") and self.debug:
                        for tc in msg["tool_calls"]:
                            func_name = tc.get("function", {}).get("name", "unknown")
                            print(f"{DIM}  [tool] {func_name}{R}")
                elif role == "tool":
                    if self.debug:
                        print(f"{DIM}  [tool output] {content[:100]}{R}")
            print(f"{DIM}--- End of session #{old_sid} ---{R}\n")

        # Display current session's chat history (these ARE in the context)
        for msg in self.chat_history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            # Skip system messages unless debug mode is enabled
            if role == "system" and not self.debug:
                continue
            
            if role == "user":
                print(f"\n\n{G}You:{R}")
                if content:
                    print(content)
            elif role == "assistant":
                print(f"\n\n{G}Agent: {R}")
                if content:
                    self.console.print(Markdown(content))
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        func_name = tc.get("function", {}).get("name", "unknown")
                        func_args = tc.get("function", {}).get("arguments", "{}")
                        try:
                            args_parsed = json.loads(func_args)
                        except json.JSONDecodeError:
                            args_parsed = {}
                        print(f"{B}  [tool] {_tool_summary(func_name, args_parsed)}{R}")
            elif role == "tool":
                pass
            else:
                print(f"\n{role.capitalize()}:")
                if content:
                    print(content)
        
        print("\n" + "=" * 60 + "\n")



    def _check_incomplete_todo_list(self):
        """Check for incomplete todo list and offer resumption."""
        from prompt_toolkit import prompt
        from Tools.utils import BLUE, GREEN, YELLOW, RED, RESET
        from Agent.chat_history_db import resolve_todo_session_id

        try:
            todo_session_id = resolve_todo_session_id(self.session_id)
            active_todo = get_active_todo_list(todo_session_id)
            if active_todo and active_todo['status'] in ('pending', 'in_progress', 'rejected'):
                tasks = get_todo_tasks(active_todo['id'])
                pending_tasks = [t for t in tasks if t['status'] == 'pending']
                in_progress_tasks = [t for t in tasks if t['status'] == 'in_progress']
                
                if pending_tasks or in_progress_tasks:
                    print(f"\n{BLUE}Incomplete todo list found ({active_todo['id']}){RESET}")
                    print("=" * 60)
                    for task in tasks:
                        status_color = GREEN if task['status'] == 'completed' else YELLOW if task['status'] == 'in_progress' else RESET
                        print(f"{status_color}[{task['status']}] {YELLOW}{task['order_index'] + 1}.{RESET} {task['goal']}{RESET}")
                    print("=" * 60)
                    
                    if active_todo['status'] == 'rejected':
                        print(f"{YELLOW}This todo list was previously rejected.{RESET}")
                    
                    user_input = prompt("Resume this todo list? (y/n): ").strip().lower()
                    if user_input == 'y':
                        print(f"{GREEN}Resuming todo list...{RESET}")
                        # The agent will need to call ExecuteNextTask to continue
                    else:
                        reason = prompt(f"{YELLOW}Reason for skipping (optional, press Enter to skip): {RESET}").strip()
                        if reason:
                            print(f"{YELLOW}Skipping todo list resumption. Reason: {reason}{RESET}")
                        else:
                            print(f"{YELLOW}Skipping todo list resumption.{RESET}")
        except Exception as e:
            print(f"{RED}Warning: Failed to check for incomplete todo list: {e}{RESET}")



    def setup_tools(self, callback):
        callback(self.tool_registry)



    def _get_tools(self, role):
        tools_required = self.roles[role]["tools"]
        formatted_tools = []

        for tool in tools_required:
            if tool not in self.tools:
                print(f"Warning: tool '{tool}' required by role '{role}' is not defined in tools.json, skipping")
                continue
            formatted_tools.append(self.tools[tool])
        return formatted_tools

    def _tool_error(self, toolcall_id, message):
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": message,
        }



    def _has_dangling_tool_work(self):
        if not self.chat_history:
            return False

        last_msg = self.chat_history[-1]
        if last_msg.get("role") == "tool":
            return True

        # Vision messages (role "user" with tool_call_id) are also tool responses
        if last_msg.get("role") == "user" and last_msg.get("tool_call_id"):
            return True

        return last_msg.get("role") == "assistant" and bool(last_msg.get("tool_calls"))

    def _get_pending_toolcalls(self):
        """Find tool calls from the last assistant message that don't have tool responses yet.

        This handles the case where an assistant message contains multiple tool_calls
        but only some were executed before a crash/interrupt.
        """
        last_assistant_idx = None
        for i in range(len(self.chat_history) - 1, -1, -1):
            msg = self.chat_history[i]
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                last_assistant_idx = i
                break

        if last_assistant_idx is None:
            return []

        assistant_msg = self.chat_history[last_assistant_idx]
        tool_calls = assistant_msg.get("tool_calls", [])

        responded_ids = set()
        for msg in self.chat_history[last_assistant_idx + 1:]:
            tcid = msg.get("tool_call_id")
            if tcid:
                responded_ids.add(tcid)

        return [tc for tc in tool_calls if tc.get("id") not in responded_ids]



    def _execute_tool_call(self, toolcall_id, tool_name, tool_arguments):
        yield ("tool_call", tool_name, tool_arguments)

        try:
            args_dict = json.loads(tool_arguments)
        except json.JSONDecodeError as err:
            error_msg = self._tool_error(toolcall_id, f"Invalid tool arguments: {err}")
            self.chat_history.append(error_msg)
            save_message(self.session_id, error_msg)
            return

        try:
            tool_output = self.tool_registry.call(
                tool_name, args_dict, toolcall_id, self.session_id
            )

            if self.debug:
                print(f"\n[DEBUG] Tool output for {tool_name}:")
                print(tool_output.get("content", ""))
                print()

            if "image_data" in tool_output:
                image_data = tool_output["image_data"]
                vision_content = [
                    {
                        "type": "text",
                        "text": tool_output.get("content", "Analyze this image:")
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image_data['mime_type']};base64,{image_data['base64_data']}"
                        }
                    }
                ]
                vision_msg = {
                    "role": "user",
                    "content": vision_content,
                    "tool_call_id": toolcall_id,
                }
                self.chat_history.append(vision_msg)
                save_message(self.session_id, vision_msg)
            else:
                self.chat_history.append(tool_output)
                save_message(self.session_id, tool_output)
        except Exception as err:
            error_msg = self._tool_error(toolcall_id, str(err))
            self.chat_history.append(error_msg)
            save_message(self.session_id, error_msg)



    def resume_dangling_tool_work(self):
        if not self._has_dangling_tool_work():
            return

        last_msg = self.chat_history[-1]
        if last_msg.get("role") == "assistant" and last_msg.get("tool_calls"):
            for toolcall in last_msg["tool_calls"]:
                function = toolcall.get("function", {})
                yield from self._execute_tool_call(
                    toolcall.get("id"),
                    function.get("name"),
                    function.get("arguments", "{}"),
                )
        elif last_msg.get("tool_call_id"):
            pending = self._get_pending_toolcalls()
            for toolcall in pending:
                function = toolcall.get("function", {})
                yield from self._execute_tool_call(
                    toolcall.get("id"),
                    function.get("name"),
                    function.get("arguments", "{}"),
                )

        yield from self.start()



    def _yield_reasoning(self, response):
        """Yield reasoning content from a non-streaming response if reasoning is enabled."""
        if self.reasoning:
            reasoning_content = getattr(response, "reasoning_content", None) or ""
            if reasoning_content:
                yield ("reasoning", reasoning_content)



    def _yield_reasoning_chunk(self, delta):
        """Yield a reasoning chunk from a streaming response if reasoning is enabled."""
        if self.reasoning and getattr(delta, "reasoning_content", None):
            yield ("reasoning_chunk", delta.reasoning_content)



    def _stream_completion(self, model):
        """Stream a chat completion, yielding chunk events.

        Sets self._agent_msg and self._total_tokens.
        On error, yields ("error", ...) and leaves self._agent_msg as None.
        """
        self._agent_msg = None
        self._total_tokens = 0
        content = ""
        tool_calls_accum = []

        try:
            stream = self.client.chat.completions.create(
                model=model,
                messages=self.chat_history,
                tools=self._get_tools(self.agent_role),
                stream=True,
                stream_options={"include_usage": True},
            )
            for chunk in stream:
                if hasattr(chunk, "usage") and chunk.usage:
                    self._total_tokens = chunk.usage.total_tokens or 0
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                yield from self._yield_reasoning_chunk(delta)

                if delta.content:
                    content += delta.content
                    yield ("response_chunk", delta.content)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        while len(tool_calls_accum) <= idx:
                            tool_calls_accum.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        if tc.id:
                            tool_calls_accum[idx]["id"] = tc.id
                        if tc.type:
                            tool_calls_accum[idx]["type"] = tc.type
                        if tc.function:
                            if tc.function.name:
                                tool_calls_accum[idx]["function"]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_accum[idx]["function"]["arguments"] += tc.function.arguments
        except Exception as err:
            yield ("error", str(err))
            return

        agent_msg = {
            "role": "assistant",
            "content": content or None,
        }
        if tool_calls_accum:
            agent_msg["tool_calls"] = tool_calls_accum
        self.chat_history.append(agent_msg)
        save_message(self.session_id, agent_msg)

        if content:
            yield ("response_end", content)

        self._agent_msg = agent_msg



    def _non_stream_completion(self, model):
        """Make a non-streaming chat completion, yielding events.

        Sets self._agent_msg and self._total_tokens.
        On error, yields ("error", ...) and leaves self._agent_msg as None.
        """
        self._agent_msg = None
        self._total_tokens = 0

        try:
            with self.console.status("[bold green]Thinking...", spinner="dots"):
                chat = self.client.chat.completions.create(
                    model=model,
                    messages=self.chat_history,
                    tools=self._get_tools(self.agent_role),
                )
        except Exception as err:
            yield ("error", str(err))
            return

        if not chat.choices or len(chat.choices) == 0:
            yield ("error", "no choices in response")
            return

        if hasattr(chat, 'usage') and chat.usage:
            self._total_tokens = chat.usage.total_tokens or 0

        response = chat.choices[0].message

        yield from self._yield_reasoning(response)

        agent_msg = {
            "role": response.role,
            "content": response.content,
        }

        if hasattr(response, "tool_calls") and response.tool_calls:
            agent_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in response.tool_calls
            ]
        self.chat_history.append(agent_msg)
        save_message(self.session_id, agent_msg)

        content = response.content or ""
        if content:
            yield ("response", content)

        self._agent_msg = agent_msg



    def _stream_handover(self, model):
        """Stream a handover completion, yielding chunk events.

        Sets self._handover_text on success.
        On error, yields ("error", ...) and leaves self._handover_text as None.
        """
        self._handover_text = None
        handover_text = ""
        try:
            stream = self.client.chat.completions.create(
                model=model,
                messages=self.chat_history,
                stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    handover_text += delta.content
                    yield ("response_chunk", delta.content)
        except Exception as err:
            self.chat_history.pop()
            yield ("error", f"Handover failed: {err}")
            return

        if not handover_text:
            self.chat_history.pop()
            yield ("error", "Handover failed: no content in response")
            return

        self._handover_text = handover_text



    def _non_stream_handover(self, model):
        """Make a non-streaming handover completion.

        Sets self._handover_text on success.
        On error, yields ("error", ...) and leaves self._handover_text as None.
        """
        self._handover_text = None
        try:
            with self.console.status("[bold green]Generating handover instructions...", spinner="dots"):
                chat = self.client.chat.completions.create(
                    model=model,
                    messages=self.chat_history,
                )
        except Exception as err:
            self.chat_history.pop()
            yield ("error", f"Handover failed: {err}")
            return

        if not chat.choices or len(chat.choices) == 0:
            self.chat_history.pop()
            yield ("error", "Handover failed: no choices in response")
            return

        handover_response = chat.choices[0].message
        self._handover_text = handover_response.content or ""



    def _perform_handover(self, total_tokens: int, context_window: int):
        """Perform a handover to a new session when the context window is nearly full.

        Sends a handover prompt to the agent (without tools), saves the response,
        creates a new session, stores the handover record, and switches to the
        new session so the agent can seamlessly continue working.
        """
        BLUE = "\033[34m"
        YELLOW = "\033[33m"
        DIM = "\033[2m"
        RESET = "\033[0m"

        # Find the last real user message (not the handover prompt we're about to add)
        last_user_prompt = ""
        for msg in reversed(self.chat_history):
            if msg.get("role") == "user" and msg.get("content"):
                last_user_prompt = msg["content"]
                break

        print(f"{YELLOW}\n[handover] Context window nearly full ({total_tokens}/{context_window} tokens). Initiating handover...{RESET}")
        if last_user_prompt:
            print(f"{DIM}Continuing task: {last_user_prompt}{RESET}")

        handover_prompt = (
            "Without using any more tool calls, give me a handover instruction for the next agent session.\n\n"
            "Focus ONLY on the current task you are working on right now. Do NOT summarize previous tasks that are already completed.\n\n"
            f"The user's most recent request was:\n\"\"\"\n{last_user_prompt}\n\"\"\"\n\n"
            "Include:\n\n"
            "1. The user's most recent request (copy it verbatim from above)\n"
            "2. Current state of the code: what you've changed so far for THIS task\n"
            "3. Important files and symbols involved in THIS task\n"
            "4. Errors, blockers, or failed attempts on THIS task\n"
            "5. Exact next step you would take\n\n"
            "Be specific. Do not write vague phrases like \"continue debugging\" without explaining where and how."
        )

        handover_user_msg = {"role": "user", "content": handover_prompt}
        self.chat_history.append(handover_user_msg)

        model = self.roles[self.agent_role]["model"]
        if self.streaming:
            for event in self._stream_handover(model):
                if event[0] == "error":
                    yield event
                    return
        else:
            for event in self._non_stream_handover(model):
                if event[0] == "error":
                    yield event
                    return

        if self._handover_text is None:
            return

        handover_text = self._handover_text

        save_message(self.session_id, handover_user_msg)

        handover_agent_msg = {"role": "assistant", "content": handover_text}
        self.chat_history.append(handover_agent_msg)
        save_message(self.session_id, handover_agent_msg)

        session_info = get_session_info(self.session_id)
        if session_info is None:
            session_info = {"parent_session_id": None, "toolcall_id": None, "depth": 0}

        new_session_id = create_session(
            self.chat_id,
            parent_session_id=session_info.get("parent_session_id"),
            toolcall_id=session_info.get("toolcall_id"),
            effort=get_session_effort(self.session_id),
            depth=session_info.get("depth", 0),
        )

        save_handover(self.session_id, new_session_id, handover_text, total_tokens, context_window)

        set_redirect_session_id(self.session_id, new_session_id)

        migrate_todo_lists(self.session_id, new_session_id)

        system_msg = {"role": "system", "content": self.system_prompt}
        save_message(new_session_id, system_msg)

        handover_user_msg_new = {"role": "user", "content": handover_text}
        save_message(new_session_id, handover_user_msg_new)

        self.session_id = new_session_id
        self.chat_history = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": handover_text},
        ]
        self.is_new_session = False

        print(f"{BLUE}[handover] New session {new_session_id} created. Continuing...{RESET}")



    def start(self, prompt=None):
        if self.agent_role not in self.roles:
            yield ("error", f"role '{self.agent_role}' is not defined")
            return

        if prompt is not None:
            # Check for registered commands
            should_process, effective_prompt = self.command_registry.try_handle(prompt, self)
            if not should_process:
                return
            prompt = effective_prompt

            user_msg = {"role": "user", "content": prompt}
            self.chat_history.append(user_msg)
            save_message(self.session_id, user_msg)
            
            # Update chat title with first user message if this is a new session
            if self.is_new_session and not self.is_subagent:
                title = generate_title(prompt)
                update_chat_title(self.chat_id, title)
                self.is_new_session = False
            
        model = self.roles[self.agent_role]["model"]
        context_window = self.roles[self.agent_role].get("context_window")
        HANDOVER_THRESHOLD = 50000

        while True:
            if self.streaming:
                yield from self._stream_completion(model)
            else:
                yield from self._non_stream_completion(model)

            if self._agent_msg is None:
                return

            agent_msg = self._agent_msg
            total_tokens = self._total_tokens

            BLUE = "\033[34m"
            RESET = "\033[0m"
            if not agent_msg.get("tool_calls"):

                # Check if handover is needed before returning (main agent only)
                if not self.is_subagent and context_window and total_tokens > 0 and (context_window - total_tokens) < HANDOVER_THRESHOLD:
                    yield from self._perform_handover(total_tokens, context_window)
                    continue

                # Commit changes after agent's final response (main agent only — subagents skip this)
                if not self.is_subagent:
                    try:
                        # Build commit message: user message + number of tool calls + agent response
                        user_message = prompt if prompt else "continuation"
                        tool_call_count = len([msg for msg in self.chat_history if msg.get("role") == "tool"])
                        commit_message = f"User: {user_message[:100]}... | Tool calls: {tool_call_count} | Agent response"

                        print(f"{BLUE}\ntracking changes...{RESET}")
                        self.git_manager.add_changed_files()
                        commit_id = self.git_manager.commit(commit_message)
                    except Exception as commit_err:
                        # Don't fail the agent if commit fails, just log it
                        self.console.print(f"[yellow]Warning: Failed to commit changes: {commit_err}[/yellow]")
                        return

                    print(f"{BLUE}type /undo to undo the last code changes{RESET}")
                return

            history_len_before_tools = len(self.chat_history)

            for toolcall in agent_msg["tool_calls"]:
                yield from self._execute_tool_call(
                    toolcall["id"],
                    toolcall["function"]["name"],
                    toolcall["function"]["arguments"],
                )

            # Estimate tokens added by tool results to avoid overshooting the context window
            # on the next API call. total_tokens is from the previous response and doesn't
            # include tool result messages that were just appended to chat_history.
            new_msgs = self.chat_history[history_len_before_tools:]
            tool_result_chars = sum(len(str(msg.get("content", ""))) for msg in new_msgs)
            estimated_total = total_tokens + tool_result_chars // 4

            # Check if handover is needed after tool calls, before next API call (main agent only)
            if not self.is_subagent and context_window and estimated_total > 0 and (context_window - estimated_total) < HANDOVER_THRESHOLD:
                yield from self._perform_handover(estimated_total, context_window)
                continue
