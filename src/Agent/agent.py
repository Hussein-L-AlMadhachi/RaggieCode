import contextlib
import io
import os
import json
import shutil
import platform
from datetime import date

from openai import OpenAI
from rich.markdown import Markdown

from .config import load_roles, load_tools, load_keys
from .providers import (
    resolve_provider,
    resolve_base_url,
    resolve_user_agent,
    make_key_id,
    filter_messages_for_provider,
    build_completion_kwargs,
    build_session_headers,
    strip_forbidden_params,
)
from .tools import ToolRegistry

# Providers reserve up to 65536 output tokens per request, so a completion
# call fails with a 400 once its input is within that budget of the context
# window (input + output must fit). Hand over well before that point, with
# margin for the chars/3 tool-result token estimate.
HANDOVER_THRESHOLD = 90000
from .command import CommandRegistry
from .chat_history_db import init_db, get_or_create_session, load_messages, save_message, update_chat_title, generate_title, get_active_todo_list, get_todo_tasks, create_session, set_redirect_session_id, save_handover, get_old_session_ids, is_subagent_session, get_session_thinking_mode, get_session_info, resolve_session_id, migrate_todo_lists, repair_message_sequence, HANDOVER_PROMPT_PREFIX
from .git_manager import GitManager
from skills import SkillManager
from indexing.code_index_sdk import CodeIndexSDK
import io_backend
import mcp_client


def _tool_summary(name, args):
    parts = [f"{k}: {str(v)[:60]}" for k, v in args.items()]
    return f"{name}   {' '.join(parts)}"


def _tool_requires_index(entry):
    """True when a tools.json entry declares it needs the code index."""
    return bool(entry.get("indexing", False))


def _api_tool_schema(entry):
    """Return the tool schema sent to the completion API.

    Strips the local-only "indexing" flag without mutating the original
    tools.json entry.
    """
    if "indexing" not in entry:
        return entry
    return {k: v for k, v in entry.items() if k != "indexing"}


def calculate_function_complexity( branch_score, n_lines ):
    return round(branch_score / 30, 2) + (n_lines/100)

def function_severity_label(score):
    """Shared severity label for function complexity scores.

    Used by both the terminal text formatter and the structured payload
    for UIs, so the labels never drift apart.
    """
    if score > 5.5:
        return "VERY HIGH"
    if score > 3.5:
        return "HIGH"
    return "BLOATED"


def format_health_stats(funcs, bloated_objects, max_functions=3):
    """Format the health stats display shown after each agent response.

    Args:
        funcs: indexed function records (top-complexity order), each with
            .name, .file_path, .branch_count and .location.start_line/.end_line.
        bloated_objects: class bloat dicts from get_top_bloated_classes.
        max_functions: how many bloated functions to show at most.

    Returns a multi-line string listing the top bloated functions and the
    top 3 bloated objects, "the codebase is healthy" when data exists but
    nothing is flagged, or None when there is no data at all.
    """
    from Tools.utils import GREEN, YELLOW, RED, GRAY, RESET

    header = f"{YELLOW}health stats: (beta){RESET}"

    top_funcs = []
    for func in funcs:
        loc = func.location.end_line - func.location.start_line + 1
        score = calculate_function_complexity(func.branch_count, loc)
        if score <= 1.5:
            # Healthy function   not worth listing.
            continue
        label = function_severity_label(score)
        color = YELLOW if label == "BLOATED" else RED

        top_funcs.append((func, loc, score, color, label))
        if len(top_funcs) == max_functions:
            break

    top_objects = [b for b in bloated_objects if b["score"] >= 1.5][:3]

    if not top_funcs and not top_objects:
        if funcs or bloated_objects:
            return f"{header}\nthe codebase is healthy"
        return None

    lines = [header]

    if top_funcs:
        lines.append(f"  {YELLOW}top bloated functions:{RESET}")
        for i, (func, loc, score, color, label) in enumerate(top_funcs, 1):
            lines.append(
                f"    {i}. {func.name}()"
                f"  {GRAY}{func.file_path}:{func.location.start_line}{RESET}"
                f"  {color}{label}{RESET}"
            )

    if top_objects:
        lines.append(f"  {YELLOW}top bloated objects:{RESET}")
        for i, obj in enumerate(top_objects, 1):
            color = YELLOW if obj["severity"] == "LARGE" else RED
            lines.append(
                f"    {i}. {obj['name']}"
                f"  {GRAY}{obj['file_path']}:{obj['line']}{RESET}"
                f"  {color}{obj['severity']}{RESET}"
                f"  {GRAY}(score {obj['score']:.2f},"
                f" methods {obj['method_count']},"
                f" attributes {obj['attribute_count']},"
                f" lines {obj['class_loc']}){RESET}"
            )

    lines.append(f"\n  {GRAY}use /health to generate the full report{RESET}")
    return "\n".join(lines)

class Agent:

    def __init__(self, role, chat_id: int, session_id=None, debug=None):
        self.roles = load_roles()
        self.tools = load_tools()
        self.tool_registry = ToolRegistry()
        self.tool_registry.agent_role = role
        self.command_registry = CommandRegistry()

        self.agent_role = role
        # debug=None inherits the process-wide flag from io_backend, so
        # subagents (constructed without an explicit flag) match the CLI's
        # --debug setting.
        self.debug = io_backend.get_debug() if debug is None else bool(debug)
        self.console = io_backend.get_console()

        # Streaming completions are opt-in (terminal keeps non-streaming so
        # its output stays unchanged); ACP (web) sessions set this True so
        # the UI gets progressive chunks and cancel works mid-generation.
        self.stream = False

        if role not in self.roles:
            raise ValueError(f"Role '{role}' is not defined in roles.json")

        # Provider is mandatory   it drives API behavior. base_url is
        # optional; if blank it is inferred from the provider's default URL.
        self.provider = resolve_provider(self.roles[role])
        if not self.provider:
            raise ValueError(
                f"No provider found for role '{role}' in roles. "
                f"Set the 'provider' field to one of the known providers "
                f"(run 'raggie roles' to see the list)."
            )

        base_url = resolve_base_url(self.roles[role])
        if not base_url:
            raise ValueError(
                f"No base_url found for role '{role}' (provider '{self.provider}') "
                f"in roles. Set 'base_url' explicitly or use a known provider."
            )

        keys = load_keys()
        # Keys are stored as "provider:base_url" -> api_key. Look up by the
        # exact key id, then fall back to bare base_url (legacy format).
        key_id = make_key_id(self.provider, base_url)
        api_key = keys.get(key_id, "") or keys.get(base_url, "")
        if not api_key:
            raise ValueError(
                f"No API key found for '{key_id}' in your keys. "
                f"Make sure you added a key for provider '{self.provider}' "
                f"with base_url '{base_url}' when you ran `raggie setup`. "
                f"If your model doesn't require a key (e.g. local AI), "
                f"set it to 'nokey'."
            )


        # Set a custom user-agent so providers like OpenCode Go can identify
        # raggie as a coding agent (they require this instead of a generic SDK
        # user-agent for routing/abuse detection). A per-role ``user_agent``
        # config value overrides this default when non-empty.
        try:
            import importlib.metadata
            _raggie_version = importlib.metadata.version("raggiecode")
        except Exception:
            _raggie_version = "dev"
        user_agent = resolve_user_agent(self.roles[role]) or f"raggie/{_raggie_version}"
        default_headers = {
            "User-Agent": user_agent,
        }

        self.client = OpenAI(
            api_key=api_key, base_url=base_url,
            default_headers=default_headers,
        )

        # Reasoning is driven entirely by reasoning_effort: when no effort
        # is configured (empty/None), reasoning is off.
        self.reasoning_effort = self.roles[role].get("reasoning_effort", "") or ""
        self.reasoning = bool(self.reasoning_effort)

        self.system_prompt = self._build_system_prompt(role)

        # Initialize database
        init_db()

        # Set chat_id (every caller provides a real chat id; None is only
        # tolerated by the signature, never used at runtime)
        self.chat_id: int = chat_id

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

        # Whether this role uses the code index at all. When False, index-driven
        # tools are hidden and no code index is built or refreshed.
        self.indexing_enabled = bool(self.roles[role].get("indexing", True))

        # Initialize code indexer for tracking changes
        from raggie_dirs import get_code_index_db_path
        if self.indexing_enabled:
            self.code_indexer = CodeIndexSDK(
                db_path=str(get_code_index_db_path()),
                root_dir=os.getcwd()
            )

            # Share code indexer with tool registry for selective re-indexing
            self.tool_registry.code_indexer = self.code_indexer
        else:
            self.code_indexer = None
            self.tool_registry.code_indexer = None

        # Initialize git manager for commit/undo/redo operations
        self.git_manager = GitManager(root_dir=os.getcwd())

        # Index the codebase at the start of each conversation
        if self.indexing_enabled:
            try:
                with self.console.status("[bold green]Indexing codebase...", spinner="dots"):
                    self.code_indexer.index_directory()
            except (KeyboardInterrupt, EOFError):
                self.console.print("\n[yellow]Indexing interrupted. Using existing index.[/yellow]")
                self.code_indexer._connect()

        # Display previous chat history if it exists (skip for subagents   they
        # share the chat_id but don't need the parent's conversation printed)
        if self.chat_history and not self.is_subagent and not io_backend.is_headless():
            self._display_chat_history()

        # Check for incomplete todo list and offer resumption
        if not io_backend.is_headless():
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
        
        # Auto-discover Agent Skills from standard directories (.skills/, skills/, .claude/skills/)
        skill_manager = SkillManager()
        try:
            discovered = skill_manager.auto_discover(role)
            if discovered and not io_backend.is_headless():
                for name in discovered:
                    print(f"  [skill] auto-discovered: {name}")
        except Exception:
            pass

        # Advertise all available skills as brief summaries in the system prompt
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
                # The machine-generated handover prompt is internal plumbing.
                if role == "user" and content.lstrip().startswith(HANDOVER_PROMPT_PREFIX):
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
                        print(f"{DIM}  [tool output] {content}{R}")
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
        from Tools.utils import BLUE, GREEN, YELLOW, RED, RESET
        from Agent.chat_history_db import resolve_todo_session_id
        import io_backend

        try:
            todo_session_id = resolve_todo_session_id(self.session_id)
            active_todo = get_active_todo_list(todo_session_id)
            if active_todo and active_todo['status'] in ('pending', 'approved'):
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
                    
                    # io_backend.confirm enforces y/n in terminal mode and routes
                    # through the ACP permission handler in headless mode.
                    resume = io_backend.confirm("Resume this todo list?")
                    if resume:
                        print(f"{GREEN}Resuming todo list...{RESET}")
                        # The agent will need to call ExecuteNextTask to continue
                    else:
                        reason = io_backend.ask("Reason for skipping (optional): ").strip()
                        if reason:
                            print(f"{YELLOW}Skipping todo list resumption. Reason: {reason}{RESET}")
                        else:
                            print(f"{YELLOW}Skipping todo list resumption.{RESET}")
        except Exception as e:
            print(f"{RED}Warning: Failed to check for incomplete todo list: {e}{RESET}")



    def setup_tools(self, callback):
        callback(self.tool_registry)

    def set_cancel_check(self, fn):
        """Register a cooperative cancel check for this agent.

        Kept out of __init__ (and read defensively via getattr in
        _cancelled) so test stubs that skip Agent.__init__ keep working.
        """
        self._cancel_check = fn

    def _cancelled(self):
        """True when the registered cancel check says the turn is cancelled."""
        check = getattr(self, "_cancel_check", None)
        return bool(callable(check) and check())



    def _get_tools(self, role):
        tools_required = self.roles[role]["tools"]
        role_uses_index = bool(self.roles[role].get("indexing", True))
        formatted_tools = []

        for tool in tools_required:
            if tool not in self.tools:
                print(f"Warning: tool '{tool}' required by role '{role}' is not defined in tools.json, skipping")
                continue
            entry = self.tools[tool]
            # Hide index-driven tools entirely when the role opts out of indexing.
            if not role_uses_index and _tool_requires_index(entry):
                continue
            formatted_tools.append(_api_tool_schema(entry))
        formatted_tools.extend(mcp_client.get_api_schemas())
        return formatted_tools

    def _tool_error(self, toolcall_id, message):
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": message,
        }

    @staticmethod
    def _normalize_message_content(msg):
        """Ensure message content is a string or content-block list, as the API requires."""
        content = msg.get("content")
        if content is not None and not isinstance(content, (str, list)):
            msg["content"] = json.dumps(content)

    def _create_completion(self, **kwargs):
        """Single choke point for chat.completions.create.

        Repairs the tool_call/tool-response sequence and normalizes content on
        the in-memory history right before sending, so the API never receives
        an invalid conversation regardless of how the history was produced.

        Applies provider-specific message filtering (e.g. stripping or
        keeping reasoning_content) so each provider only sees fields it
        accepts.

        Also injects provider-specific thinking-mode and reasoning_effort
        parameters so each provider's API contract is satisfied.
        """
        self.chat_history = repair_message_sequence(self.chat_history)
        for msg in self.chat_history:
            self._normalize_message_content(msg)
        kwargs["messages"] = filter_messages_for_provider(
            self.chat_history, self.provider, getattr(self, "reasoning", False)
        )

        # Inject provider-specific thinking mode + reasoning_effort params,
        # plus session-scoped body params (e.g. Kimi's prompt_cache_key for
        # prompt caching   kept stable across a session and its resumes).
        provider_kwargs = build_completion_kwargs(
            self.provider,
            getattr(self, "reasoning", False),
            getattr(self, "reasoning_effort", "") or None,
            getattr(self, "session_id", None),
        )
        kwargs.update(provider_kwargs)

        # Remove params forbidden by this provider (e.g. Grok rejects stop).
        kwargs = strip_forbidden_params(kwargs, self.provider)

        # Inject provider-specific session headers (e.g. OpenCode Go/Zen
        # require x-opencode-session for routing and prompt caching).
        session_headers = build_session_headers(
            self.provider, getattr(self, "session_id", None)
        )
        if session_headers:
            kwargs["extra_headers"] = session_headers

        return self.client.chat.completions.create(**kwargs)



    def _has_dangling_tool_work(self):
        if not self.chat_history:
            return False

        # An assistant tool_calls message with missing responses anywhere in the
        # history (not just at the tail   a crash can be followed by stored user
        # messages) makes the sequence invalid for the API.
        if self._get_pending_toolcalls():
            return True

        last_msg = self.chat_history[-1]
        if last_msg.get("role") == "tool":
            return True

        # Vision messages (role "user" with tool_call_id) are also tool responses
        if last_msg.get("role") == "user" and last_msg.get("tool_call_id"):
            return True

        return False

    def _get_pending_toolcalls(self):
        """Find every tool call that has no tool response yet, across ALL
        assistant messages in the history.

        A crash/interrupt can leave an earlier assistant message dangling (its
        DispatchSubagent/ExecuteNextTask child never got a response) while
        later messages   a stored user prompt, or a later, already-answered
        assistant message   follow it. Only scanning the LAST assistant message
        would miss that earlier dangling call and silently orphan its subagent,
        so resume would continue the parent but never re-run the interrupted
        child's work.
        """
        responded_ids = set()
        for msg in self.chat_history:
            tcid = msg.get("tool_call_id")
            if tcid:
                responded_ids.add(tcid)

        pending = []
        for msg in self.chat_history:
            if msg.get("role") != "assistant":
                continue
            for tc in msg.get("tool_calls", []):
                if tc.get("id") not in responded_ids:
                    pending.append(tc)
        return pending



    def _execute_tool_call(self, toolcall_id, tool_name, tool_arguments):
        yield ("tool_call", tool_name, tool_arguments)

        try:
            args_dict = json.loads(tool_arguments)
        except json.JSONDecodeError as err:
            error_msg = self._tool_error(toolcall_id, f"Invalid tool arguments: {err}")
            self.chat_history.append(error_msg)
            save_message(self.session_id, error_msg)
            yield ("tool_result", tool_name, f"Invalid tool arguments: {err}", True)
            return

        try:
            tool_output = self.tool_registry.call(
                tool_name, args_dict, toolcall_id, self.session_id
            )
            # A tool returning non-string content (e.g. a dict) would make the
            # next API call fail; normalize before it enters the history.
            self._normalize_message_content(tool_output)

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
            yield ("tool_result", tool_name, str(tool_output.get("content", "")), False)
        except Exception as err:
            error_msg = self._tool_error(toolcall_id, str(err))
            self.chat_history.append(error_msg)
            save_message(self.session_id, error_msg)
            yield ("tool_result", tool_name, str(err), True)



    def resume_dangling_tool_work(self):
        """Continue an interrupted turn.

        Only does work when the history actually shows an interrupted turn:
        dangling tool calls (from a crash or a cancelled turn) are
        re-executed first, then the turn continues with a fresh model
        completion. A stored user message that never got a response (crash
        before the completion finished) is also continued.

        When there is no interrupted work   a brand-new chat or a turn that
        finished normally   nothing is yielded, so startup never fires a
        phantom completion with an empty prompt.
        """
        if self._has_dangling_tool_work():
            # Re-execute every tool call that never got a response, wherever
            # the dangling assistant message sits in the history.
            for toolcall in self._get_pending_toolcalls():
                # A cancel during resume must not kick off any new tool
                # execution; the call stays dangling for the next resume.
                if self._cancelled():
                    return

                function = toolcall.get("function", {})
                yield from self._execute_tool_call(
                    toolcall.get("id"),
                    function.get("name"),
                    function.get("arguments", "{}"),
                )

            # Executed tool responses are appended to the end of the history;
            # pull them up next to their assistant message so the sequence
            # sent to the API stays valid.
            self.chat_history = repair_message_sequence(self.chat_history)
        elif not self._ends_with_unanswered_user_message():
            return

        yield from self.start()

    def _ends_with_unanswered_user_message(self):
        """True when the last stored message is a plain user prompt.

        That means a turn was interrupted before the model completion
        finished (e.g. crash right after the prompt was saved), so
        resuming should continue it. A vision response (user role with a
        tool_call_id) is a tool output, not an unanswered prompt.
        """
        if not self.chat_history:
            return False
        last_msg = self.chat_history[-1]
        return last_msg.get("role") == "user" and not last_msg.get("tool_call_id")



    def _yield_reasoning(self, response):
        """Yield reasoning content from a non-streaming response if reasoning is enabled."""
        if self.reasoning:
            reasoning_content = getattr(response, "reasoning_content", None) or ""
            if reasoning_content:
                yield ("reasoning", reasoning_content)



    def _non_stream_completion(self, model):
        """Make a non-streaming chat completion, yielding events.

        Sets self._agent_msg and self._total_tokens.
        On error, yields ("error", ...) and leaves self._agent_msg as None.
        """
        self._agent_msg = None
        self._total_tokens = 0

        try:
            with self.console.status("[bold green]Thinking...", spinner="dots"):
                chat = self._create_completion(
                    model=model,
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

        # Persist reasoning_content so providers that require it back
        # (e.g. DeepSeek thinking mode) get it on the next turn.
        reasoning_content = getattr(response, "reasoning_content", None) or ""
        if reasoning_content:
            agent_msg["reasoning_content"] = reasoning_content

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

    def _stream_completion(self, model):
        """Make a streaming chat completion, yielding chunk events.

        Mirrors the _non_stream_completion contract: sets self._agent_msg
        and self._total_tokens; on error yields ("error", ...) and leaves
        self._agent_msg as None (partial streamed text is not persisted,
        keeping history consistent with the non-stream path).

        Emits ("reasoning_chunk", text) and ("response_chunk", text) while
        iterating so ACP sessions show progress and the per-session cancel
        flag can interrupt generation mid-stream.

        When the cancel check fires mid-stream, the stream is closed and
        the loop breaks out to the normal persistence path: the partially
        collected message is still persisted (with only tool calls whose
        arguments are complete/parseable) so the turn stays resumable via
        dangling tool-call work.

        Unlike the non-stream path, the full ("response", ...) and
        ("reasoning", ...) events are NOT re-emitted at the end: the chunks
        already carried the text and re-emitting it would duplicate it in
        the web UI. The agent message is still persisted and self._agent_msg
        is set, so the handover/tool-call loop in start() behaves the same.
        """
        self._agent_msg = None
        self._total_tokens = 0

        try:
            stream = self._create_completion(
                model=model,
                tools=self._get_tools(self.agent_role),
                stream=True,
            )
        except Exception as err:
            yield ("error", str(err))
            return

        content_parts = []
        reasoning_parts = []
        # index -> {id, type, function: {name, arguments}}; dicts keep
        # first-seen (insertion) order.
        tool_calls = {}
        cancelled = False

        try:
            for chunk in stream:
                # Cooperative cancel: stop mid-stream; the post-loop
                # persistence still runs so the turn stays resumable.
                if self._cancelled():
                    cancelled = True
                    close = getattr(stream, "close", None)
                    if callable(close):
                        close()
                    break

                usage = getattr(chunk, "usage", None)
                if usage is not None and getattr(usage, "total_tokens", None) is not None:
                    self._total_tokens = usage.total_tokens

                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                delta = choices[0].delta

                reasoning_text = getattr(delta, "reasoning_content", None)
                if reasoning_text:
                    reasoning_parts.append(reasoning_text)
                    yield ("reasoning_chunk", reasoning_text)

                content_text = getattr(delta, "content", None)
                if content_text:
                    content_parts.append(content_text)
                    yield ("response_chunk", content_text)

                for tc_delta in getattr(delta, "tool_calls", None) or []:
                    index = getattr(tc_delta, "index", 0)
                    entry = tool_calls.setdefault(
                        index,
                        {"id": "", "type": "", "function": {"name": "", "arguments": ""}},
                    )
                    tc_id = getattr(tc_delta, "id", None)
                    if tc_id:
                        entry["id"] = tc_id
                    tc_type = getattr(tc_delta, "type", None)
                    if tc_type:
                        entry["type"] = tc_type
                    function = getattr(tc_delta, "function", None)
                    if function is not None:
                        name = getattr(function, "name", None)
                        if name:
                            entry["function"]["name"] = name
                        arguments = getattr(function, "arguments", None)
                        if arguments:
                            entry["function"]["arguments"] += arguments
        except Exception as err:
            yield ("error", str(err))
            return

        content = "".join(content_parts)
        reasoning_content = "".join(reasoning_parts)

        agent_msg = {
            "role": "assistant",
            "content": content,
        }

        # Persist reasoning_content so providers that require it back
        # (e.g. DeepSeek thinking mode) get it on the next turn.
        if reasoning_content:
            agent_msg["reasoning_content"] = reasoning_content

        if tool_calls:
            entries = [tool_calls[index] for index in tool_calls]
            if cancelled:
                # A cancelled stream can truncate tool-call arguments
                # mid-JSON; keep only parseable ones so the resume path
                # never re-executes a partial call.
                kept = []
                for entry in entries:
                    try:
                        json.loads(entry["function"]["arguments"])
                    except json.JSONDecodeError:
                        continue
                    kept.append(entry)
                entries = kept
            if entries:
                agent_msg["tool_calls"] = entries

        self.chat_history.append(agent_msg)
        save_message(self.session_id, agent_msg)

        self._agent_msg = agent_msg

        if not self._total_tokens:
            # Some providers don't send usage without stream_options, and
            # several reject that param entirely, so fall back to an
            # estimate (handover logic tolerates estimates; it estimates
            # tool results the same way).
            self._total_tokens = sum(
                len(str(msg.get("content", ""))) for msg in self.chat_history
            ) // 4

    def _non_stream_handover(self, model):
        """Make a non-streaming handover completion.

        Sets self._handover_text on success.
        On error, yields ("error", ...) and leaves self._handover_text as None.
        """
        self._handover_text = None
        try:
            with self.console.status("[bold green]Generating handover instructions...", spinner="dots"):
                chat = self._create_completion(
                    model=model,
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

        # Set False here so start() can detect a failed handover and stop
        # instead of retrying the same oversized request.
        self._handover_failed = False

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

        # Surface the handover phases to streaming consumers (the web UI shows
        # session/status events as loader labels).
        yield ("status", "Generating handover instructions...")
        for event in self._non_stream_handover(model):
            if event[0] == "error":
                self._handover_failed = True
                yield event
                return

        if self._handover_text is None:
            self._handover_failed = True
            return

        handover_text = self._handover_text

        yield ("status", "Switching to new session...")

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
            thinking_mode=get_session_thinking_mode(self.session_id),
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

        # Surface the handover document to UIs the moment the handover
        # happens (terminal prints it; web renders the labelled doc panel).
        yield ("handover_doc", handover_text)

        # Handover complete: clear the loader; the next API call (or the
        # generic 'thinking' fallback in the UI) takes over from here.
        yield ("status_done",)

        print(f"{BLUE}[handover] New session {new_session_id} created. Continuing...{RESET}")


    def start(self, prompt=None):
        if self.agent_role not in self.roles:
            yield ("error", f"role '{self.agent_role}' is not defined")
            return

        if prompt is not None:
            # Refresh the code index before this turn so index-driven
            # tools and health stats reflect the latest file state.
            # Emitted as tuple events so headless/ACP consumers can show
            # indexing progress; the terminal printer ignores unknown kinds.
            if self.code_indexer is not None:
                yield ("status", "Indexing codebase...")
                self._reindex_before_message()
                yield ("status_done",)

            # Check for registered commands. Command handlers talk through
            # print()/console.print(); capture that output and emit it as a
            # notice event so headless UIs (web) can show it too.
            captured = io.StringIO()
            console = self.console
            old_console_file = console.file
            console.file = captured
            try:
                with contextlib.redirect_stdout(captured):
                    should_process, effective_prompt = self.command_registry.try_handle(prompt, self)
            finally:
                console.file = old_console_file
            notice_text = captured.getvalue()
            if notice_text.strip():
                yield ("notice", notice_text)
            if not should_process:
                return
            prompt = effective_prompt

            # Auto-commit current state before processing the prompt.
            # This ensures /undo always has a valid previous state to
            # restore, even on freshly initialized repos where the
            # initial commit has an empty tree.
            if not self.is_subagent:
                try:
                    self.git_manager.commit_if_changed(
                        f"Auto-snapshot before: {prompt[:100]}"
                    )
                except Exception:
                    pass  # Don't block the prompt if snapshot fails

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
        # Hand over before input gets within the provider's output-token
        # reserve of the context window, with margin for the chars/3
        # tool-result token estimate. Clamp for small context windows.
        handover_threshold = min(HANDOVER_THRESHOLD, (context_window or 0) // 2)

        while True:
            # Handover loops back here via `continue`, so a cancel arriving
            # during handover is caught on the next iteration too.
            if self._cancelled():
                return

            if getattr(self, "stream", False):
                yield from self._stream_completion(model)
            else:
                yield from self._non_stream_completion(model)

            if self._agent_msg is None:
                return

            # The completion persisted its message; stop before any tool
            # runs so the calls stay dangling (and resumable) on cancel.
            if self._cancelled():
                return

            agent_msg = self._agent_msg
            total_tokens = self._total_tokens

            BLUE = "\033[34m"
            RESET = "\033[0m"
            if not agent_msg.get("tool_calls"):

                # Check if handover is needed before returning (main agent only)
                if not self.is_subagent and context_window and total_tokens > 0 and (context_window - total_tokens) < handover_threshold:
                    yield from self._perform_handover(total_tokens, context_window)
                    if self._handover_failed:
                        return
                    continue

                # Commit changes after agent's final response (main agent only   subagents skip this)
                if not self.is_subagent:
                    try:
                        # Build commit message: user message + number of tool calls + agent response
                        user_message = prompt if prompt else "continuation"
                        tool_call_count = len([msg for msg in self.chat_history if msg.get("role") == "tool"])
                        commit_message = f"User: {user_message[:100]}... | Tool calls: {tool_call_count} | Agent response"

                        print(f"{BLUE}\ntracking changes...{RESET}")
                        self.git_manager.add_changed_files()
                        commit_id = self.git_manager.commit_if_changed(commit_message)
                        if commit_id is None:
                            print(f"{BLUE}no changes to track{RESET}")
                        else:
                            print(f"{BLUE}type /undo to undo the last code changes{RESET}")
                    except Exception as commit_err:
                        # Don't fail the agent if commit fails, just log it
                        self.console.print(f"[yellow]Warning: Failed to commit changes: {commit_err}[/yellow]")

                # Emit code health stats after final response (main agent only)
                if not self.is_subagent:
                    stats = self._build_health_stats()
                    if stats:
                        yield ("health_stats", stats)
                return

            history_len_before_tools = len(self.chat_history)

            for toolcall in agent_msg["tool_calls"]:
                # Drop out before the next tool call when a cancel lands.
                if self._cancelled():
                    return

                yield from self._execute_tool_call(
                    toolcall["id"],
                    toolcall["function"]["name"],
                    toolcall["function"]["arguments"],
                )

            # Estimate tokens added by tool results to avoid overshooting the context window
            # on the next API call. total_tokens is from the previous response and doesn't
            # include tool result messages that were just appended to chat_history.
            # Divide by 3 (not 4): tool results are mostly code/JSON, which tokenizes
            # at roughly 3 characters per token   //4 underestimated and caused 400s.
            new_msgs = self.chat_history[history_len_before_tools:]
            tool_result_chars = sum(len(str(msg.get("content", ""))) for msg in new_msgs)
            estimated_total = total_tokens + tool_result_chars // 3

            # Check if handover is needed after tool calls, before next API call (main agent only)
            if not self.is_subagent and context_window and estimated_total > 0 and (context_window - estimated_total) < handover_threshold:
                yield from self._perform_handover(estimated_total, context_window)
                if self._handover_failed:
                    return
                continue

    def _reindex_before_message(self):
        """Incrementally re-index the codebase before processing a user message.

        Incremental (mtime/hash based), so it is cheap when nothing changed.
        Never blocks the turn on failure.
        """
        if self.code_indexer is None:
            return
        try:
            with self.console.status("[bold green]Indexing codebase...", spinner="dots"):
                self.code_indexer.index_directory()
        except (KeyboardInterrupt, EOFError):
            self.console.print("\n[yellow]Indexing interrupted. Using existing index.[/yellow]")
            self.code_indexer._connect()
        except Exception as err:
            self.console.print(f"[yellow]Warning: pre-message indexing failed: {err}[/yellow]")

    def _load_health_data(self):
        """Load the raw health data (top functions + bloated classes).

        Returns (funcs, bloated) or None when there is no index data at all.
        """
        try:
            if self.code_indexer is None or self.code_indexer.conn is None:
                return None
        except Exception:
            return None

        try:
            funcs = self.code_indexer.get_top_complex_functions(limit=10)
        except Exception:
            funcs = None

        # Separate try so a bloat query failure never hides the function list.
        try:
            bloated = self.code_indexer.get_top_bloated_classes(limit=3, min_score=1.0)
        except Exception:
            bloated = None

        if funcs is None and bloated is None:
            return None

        return funcs or [], bloated or []

    def _build_health_stats(self):
        data = self._load_health_data()
        if data is None:
            return None
        return format_health_stats(*data)

    def _build_health_stats_payload(self):
        """Structured health stats for UIs (web modal).

        Returns {"healthy": bool, "functions": [...], "objects": [...]}
        or None when there is no index data.
        """
        data = self._load_health_data()
        if data is None:
            return None
        funcs, bloated = data

        functions = []
        for func in funcs:
            loc = func.location.end_line - func.location.start_line + 1
            score = calculate_function_complexity(func.branch_count, loc)
            if score <= 1.5:
                continue
            functions.append({
                "name": func.name,
                "file": func.file_path,
                "line": func.location.start_line,
                "score": round(score, 2),
                "severity": function_severity_label(score),
            })
            if len(functions) == 3:
                break

        objects = [
            {
                "name": obj["name"],
                "file": obj["file_path"],
                "line": obj["line"],
                "severity": obj["severity"],
                "score": round(obj["score"], 2),
                "methods": obj["method_count"],
                "attributes": obj["attribute_count"],
                "lines": obj["class_loc"],
            }
            for obj in bloated
            if obj["score"] >= 1.5
        ][:3]

        return {"healthy": not functions and not objects, "functions": functions, "objects": objects}

    def _write_full_complexity_report(self):
        """Write a full complexity report for all functions to a .txt file.

        Returns the file path on success, None on failure.
        """
        report = self._build_full_complexity_report()
        if report is None:
            return None

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(os.getcwd(), f"complexity_report_{timestamp}.txt")

        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report)
            return report_path
        except Exception:
            return None

    def _build_full_complexity_report(self):
        """Build the full complexity report text (same content as the .txt
        file /health writes). Returns None when there is nothing to report.
        """
        if self.code_indexer is None or self.code_indexer.conn is None:
            return None
        try:
            funcs = self.code_indexer.get_top_complex_functions(limit=10000)
            if not funcs:
                return None
        except Exception:
            return None

        from datetime import datetime
        lines = [
            f"Code Complexity Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Total functions with branches: {len(funcs)}",
            "",
        ]
        for i, func in enumerate(funcs, 1):
            loc = func.location.end_line - func.location.start_line + 1
            score = calculate_function_complexity( func.branch_count, loc )
            lines.append(
                f"{i:>4}. {func.name}()"
                f"\n      file: {func.file_path}:{func.location.start_line}"
                f"\n      complexity: {score}"
                f"\n      branches: {func.branch_count}"
                f"\n      lines: {loc}"
            )
            if func.type == "method" and func.parent_type:
                lines.append(f"      type: {func.parent_type} method")
            lines.append("")

        # Super-bloated class section. Wrapped so a query failure
        # never blocks the function complexity report.
        try:
            bloated_classes = self.code_indexer.get_top_bloated_classes(limit=25, min_score=0.0)
        except Exception:
            bloated_classes = None

        if bloated_classes is not None:
            lines.append("Class Bloat Report")
            lines.append("")
            if not bloated_classes:
                lines.append("No bloated classes detected (score < 1.0).")
                lines.append("")
            else:
                for i, bloated in enumerate(bloated_classes, 1):
                    lines.append(f"{i:>4}. {bloated['name']}")
                    lines.append(f"      file: {bloated['file_path']}:{bloated['line']}")
                    lines.append(f"      score: {bloated['score']} ({bloated['severity']})")
                    lines.append(
                        f"      methods: {bloated['method_count']}  "
                        f"attributes: {bloated['attribute_count']}  "
                        f"lines: {bloated['class_loc']}"
                    )
                    lines.append(
                        f"      fan-in: {bloated['fan_in']} callers "
                        f"from {bloated['caller_files']} files  "
                        f"fan-out: {bloated['fan_out']}"
                    )
                    lines.append("")

        return "\n".join(lines)
