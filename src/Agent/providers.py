"""Provider-specific API behavior definitions.

Different LLM providers have different quirks when using the OpenAI-compatible
chat completions API. This module centralizes those differences so the agent
can adapt its request/response handling per provider.

A role in roles.json may specify a ``"provider"`` field (e.g. ``"deepseek"``,
``"z.ai"``, ``"openai"``, ``"grok"``, ``"qwen"``, ``"litellm"``, ``"ollama"``).
If omitted, the provider is inferred from the role's ``base_url``.

Behaviors controlled per provider:

  pass_reasoning_back:
    If True, assistant messages in the conversation history must include the
    ``reasoning_content`` field when sent back to the API. DeepSeek requires
    this with tool calls; z.ai recommends it for coding (preserved thinking);
    Grok needs it for cache hits; Qwen defaults to preserve_thinking=true.

  reasoning_required_on_assistant:
    If True, EVERY assistant message must carry a ``reasoning_content`` field
    when tools are in play   even turns where the model produced no thinking
    text and turns without tool calls. DeepSeek returns 400 ("The
    reasoning_content in the thinking mode must be passed back to the API")
    when any assistant message is missing it, so an empty placeholder is
    injected for messages that have none (handover summaries, history from a
    non-thinking run, cancelled streams).

  thinking_mode:
    How to enable/disable thinking mode via the request. Values:
      - None: thinking cannot be toggled (always on, e.g. Grok)
      - "extra_body": pass via OpenAI SDK extra_body dict
      The thinking_key, thinking_enabled, and thinking_disabled fields
    specify the parameter name and values.

  reasoning_effort_values:
    List of valid reasoning_effort values for this provider.

  reasoning_effort_default:
    Default reasoning_effort value when the role doesn't specify one.

  forbidden_params:
    Parameters that must NOT be sent to this provider (e.g. Grok reasoning
    models reject presence_penalty, frequency_penalty, stop).
"""

from typing import Dict, List, Any, Optional


# Known provider identifiers.
KNOWN_PROVIDERS = [
    "deepseek", "z.ai", "openai", "grok", "qwen", "moonshot",
    "opencode-go", "opencode-zen",
    "litellm",
    # Local LLM providers (OpenAI-compatible endpoints)
    "ollama", "lm-studio", "llama-cpp", "vllm",
    "text-generation-webui", "jan", "gpt4all",
]


PROVIDER_BEHAVIORS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        # DeepSeek thinking mode: reasoning_content must be passed back when
        # tool calls are involved between turns. Without it, the API rejects
        # with 400 "reasoning_content must be passed back".
        "pass_reasoning_back": True,
        # ...and it must be present on *every* assistant message, including
        # ones that did not call a tool, so missing values get a placeholder.
        "reasoning_required_on_assistant": True,
        # Enable/disable thinking via extra_body={"thinking": {"type": ...}}
        "thinking_mode": "extra_body",
        "thinking_key": "thinking",
        "thinking_enabled": {"type": "enabled"},
        "thinking_disabled": {"type": "disabled"},
        "reasoning_effort_supported": True,
        "reasoning_effort_values": ["low", "medium", "high"],
        "reasoning_effort_default": "high",
        "forbidden_params": [],
    },
    "z.ai": {
        # z.ai (GLM) supports "Preserved Thinking" for coding scenarios:
        # set clear_thinking=false and pass back reasoning_content unmodified.
        # This is recommended for coding/agent use.
        "pass_reasoning_back": True,
        "thinking_mode": "extra_body",
        "thinking_key": "thinking",
        "thinking_enabled": {"type": "enabled"},
        "thinking_disabled": {"type": "disabled"},
        "reasoning_effort_supported": True,
        "reasoning_effort_values": [
            "none", "minimal", "low", "medium", "high", "xhigh", "max",
        ],
        "reasoning_effort_default": "high",
        "forbidden_params": [],
    },
    "openai": {
        # OpenAI Chat Completions API does NOT return reasoning_content at
        # all (reasoning is only available via the Responses API). So there's
        # nothing to pass back. reasoning_effort controls thinking depth.
        "pass_reasoning_back": False,
        "thinking_mode": None,  # no thinking toggle, just reasoning_effort
        "reasoning_effort_supported": True,
        "reasoning_effort_values": [
            "none", "minimal", "low", "medium", "high", "xhigh", "max",
        ],
        "reasoning_effort_default": "medium",
        "forbidden_params": [],
    },
    "grok": {
        # Grok reasoning models always think   cannot be disabled. The
        # reasoning_content (encrypted) should be passed back for cache
        # hits. presence_penalty, frequency_penalty, stop are forbidden.
        "pass_reasoning_back": True,
        "thinking_mode": None,  # always on, cannot toggle
        "reasoning_effort_supported": True,
        "reasoning_effort_values": ["low", "medium", "high", "xhigh"],
        "reasoning_effort_default": "high",
        "forbidden_params": ["presence_penalty", "frequency_penalty", "stop"],
    },
    "qwen": {
        # Qwen (DashScope): reasoning_content returned in thinking mode.
        # qwen3.8-max has preserve_thinking=true by default   must pass back
        # complete reasoning_content. Enable thinking via extra_body.
        "pass_reasoning_back": True,
        "thinking_mode": "extra_body",
        "thinking_key": "enable_thinking",
        "thinking_enabled": True,
        "thinking_disabled": False,
        "reasoning_effort_supported": True,
        "reasoning_effort_values": ["low", "medium", "high"],
        "reasoning_effort_default": "high",
        "forbidden_params": [],
    },
    "moonshot": {
        # Moonshot AI (Kimi) at https://api.moonshot.ai/v1 (global) or
        # https://api.moonshot.cn/v1 (China). Thinking models return
        # reasoning_content, and multi-turn conversations / tool calls must
        # pass complete assistant messages back as-is including
        # reasoning_content (Preserved Thinking).
        #
        # There is no single thinking toggle we can safely send:
        #   - kimi-k3 does NOT support the thinking parameter at all
        #   - kimi-k2.7-code always thinks and only accepts
        #     {"type": "enabled", "keep": "all"} ("disabled" errors)
        #   - kimi-k2.6 supports thinking.type enabled/disabled, but only
        #     k2.x models accept it
        # So we never send thinking; models keep their native default
        # (k3/k2.7-code always think, k2.6 thinks by default).
        #
        # reasoning_effort (top-level) is only supported by kimi-k3 with
        # values "low"/"high"/"max" (default "max"). k2.x models reject it,
        # so the default is None: effort is only sent when the role
        # explicitly configures one (k3 roles set it, k2.x roles leave it
        # empty). Switching effort mid-session invalidates Kimi prefix-cache
        # hits   pick one level per conversation.
        "pass_reasoning_back": True,
        "thinking_mode": None,
        "reasoning_effort_supported": True,
        "reasoning_effort_values": ["low", "high", "max"],
        "reasoning_effort_default": None,
        "forbidden_params": [],
        # Kimi's prompt caching is keyed by a top-level prompt_cache_key
        # body param. The docs recommend it for coding agents ("typically
        # a session id... if the session is exited and later resumed, this
        # value should remain the same") and it is required for Kimi Code
        # Plan. Sent as kwargs["prompt_cache_key"] = <session_id>.
        "session_body_param": "prompt_cache_key",
    },
    "opencode-go": {
        # OpenCode Go (https://opencode.ai/zen/go/v1) is an OpenAI-compatible
        # proxy that serves many underlying models (DeepSeek, GLM, Kimi, Grok,
        # Qwen, etc.) behind a single subscription. It transparently forwards
        # reasoning_content from thinking models, and DeepSeek-via-Go requires
        # reasoning_content pass-back just like native DeepSeek. There is no
        # single thinking toggle since each underlying model handles thinking
        # natively; we only pass reasoning_effort and pass back
        # reasoning_content.
        #
        # Go requires a stable x-opencode-session header per conversation for
        # routing optimization and prompt caching. See:
        # https://opencode.ai/docs/go/#where-can-i-use-it
        "pass_reasoning_back": True,
        "thinking_mode": None,  # underlying model handles thinking natively
        "reasoning_effort_supported": True,
        "reasoning_effort_values": [
            "none", "minimal", "low", "medium", "high", "xhigh", "max",
        ],
        "reasoning_effort_default": "high",
        "forbidden_params": [],
        "session_header": "x-opencode-session",
    },
    "opencode-zen": {
        # OpenCode Zen (https://opencode.ai/zen/v1) is the pay-as-you-go
        # counterpart to OpenCode Go. Same OpenAI-compatible Chat Completions
        # surface, same reasoning_content forwarding, but with a fuller model
        # catalog (GPT, Claude, Gemini, Grok, DeepSeek, GLM, Kimi, Qwen, etc.)
        # and per-token billing instead of a flat subscription. Behaves
        # identically to opencode-go from raggie's perspective.
        #
        # Zen also expects x-opencode-session for routing/caching.
        "pass_reasoning_back": True,
        "thinking_mode": None,  # underlying model handles thinking natively
        "reasoning_effort_supported": True,
        "reasoning_effort_values": [
            "none", "minimal", "low", "medium", "high", "xhigh", "max",
        ],
        "reasoning_effort_default": "high",
        "forbidden_params": [],
        "session_header": "x-opencode-session",
    },
    "litellm": {
        # LiteLLM (https://github.com/BerriAI/litellm) is a proxy that exposes
        # a unified OpenAI-compatible Chat Completions API for 100+ LLM
        # providers (OpenAI, Anthropic, Bedrock, Azure, DeepSeek, Cohere,
        # local Ollama/vLLM, etc.) behind a single endpoint. Typically run
        # self-hosted at http://localhost:4000/v1, but also available as a
        # managed cloud service. It transparently forwards reasoning_content
        # from thinking models (e.g. DeepSeek-R1) and passes reasoning_effort
        # through to underlying providers that support it. There is no single
        # thinking toggle since each underlying model handles thinking
        # natively; we only pass reasoning_effort and pass back
        # reasoning_content.
        "pass_reasoning_back": True,
        "thinking_mode": None,  # underlying model handles thinking natively
        "reasoning_effort_supported": True,
        "reasoning_effort_values": [
            "none", "minimal", "low", "medium", "high", "xhigh", "max",
        ],
        "reasoning_effort_default": "high",
        "forbidden_params": [],
    },
    # ------------------------------------------------------------------
    # Local LLM providers
    # These expose OpenAI-compatible Chat Completions endpoints on localhost.
    # They can run thinking models (e.g. DeepSeek-R1 distills) that emit
    # reasoning_content, so pass_reasoning_back is True to preserve it across
    # turns. None of them have an API-level thinking toggle or reasoning_effort
    # parameter   sending those would cause 400 errors, so reasoning_effort
    # is not supported.
    # ------------------------------------------------------------------
    "ollama": {
        # Ollama (http://localhost:11434/v1). Runs models locally.
        # Returns reasoning_content for thinking models (e.g. deepseek-r1).
        "pass_reasoning_back": True,
        "thinking_mode": None,
        "reasoning_effort_supported": False,
        "reasoning_effort_values": [],
        "reasoning_effort_default": None,
        "forbidden_params": [],
    },
    "lm-studio": {
        # LM Studio (http://localhost:1234/v1). GUI-based local model runner.
        # Returns reasoning_content for thinking models.
        "pass_reasoning_back": True,
        "thinking_mode": None,
        "reasoning_effort_supported": False,
        "reasoning_effort_values": [],
        "reasoning_effort_default": None,
        "forbidden_params": [],
    },
    "llama-cpp": {
        # llama.cpp / llama-cpp-python server (http://localhost:8080/v1).
        # The underlying server for many local setups. Returns
        # reasoning_content for thinking models when supported.
        "pass_reasoning_back": True,
        "thinking_mode": None,
        "reasoning_effort_supported": False,
        "reasoning_effort_values": [],
        "reasoning_effort_default": None,
        "forbidden_params": [],
    },
    "vllm": {
        # vLLM (http://localhost:8000/v1). High-throughput inference engine.
        # Returns reasoning_content for thinking models.
        "pass_reasoning_back": True,
        "thinking_mode": None,
        "reasoning_effort_supported": False,
        "reasoning_effort_values": [],
        "reasoning_effort_default": None,
        "forbidden_params": [],
    },
    "text-generation-webui": {
        # text-generation-webui / oobabooga (http://localhost:5000/v1).
        # Popular GUI for running local models. Returns reasoning_content
        # for thinking models.
        "pass_reasoning_back": True,
        "thinking_mode": None,
        "reasoning_effort_supported": False,
        "reasoning_effort_values": [],
        "reasoning_effort_default": None,
        "forbidden_params": [],
    },
    "jan": {
        # Jan (http://localhost:1337/v1). Desktop app for local models.
        # Returns reasoning_content for thinking models.
        "pass_reasoning_back": True,
        "thinking_mode": None,
        "reasoning_effort_supported": False,
        "reasoning_effort_values": [],
        "reasoning_effort_default": None,
        "forbidden_params": [],
    },
    "gpt4all": {
        # GPT4All (http://localhost:4891/v1). Desktop app for local models.
        # Returns reasoning_content for thinking models.
        "pass_reasoning_back": True,
        "thinking_mode": None,
        "reasoning_effort_supported": False,
        "reasoning_effort_values": [],
        "reasoning_effort_default": None,
        "forbidden_params": [],
    },
}


# Default behavior for unknown / unspecified providers.
_DEFAULT_BEHAVIOR = {
    "pass_reasoning_back": False,
    "thinking_mode": None,
    "reasoning_effort_supported": False,
    "reasoning_effort_values": [],
    "reasoning_effort_default": None,
    "forbidden_params": [],
}


# Map base_url substrings to provider IDs for inference when the role doesn't
# specify a provider explicitly. Checked in order; first match wins.
_BASE_URL_PATTERNS = [
    ("api.deepseek.com", "deepseek"),
    ("api.z.ai", "z.ai"),
    ("api.openai.com", "openai"),
    ("api.x.ai", "grok"),
    ("dashscope.aliyuncs.com", "qwen"),
    ("dashscope-intl.aliyuncs.com", "qwen"),
    # Moonshot AI (Kimi)   global and China endpoints.
    ("api.moonshot.ai", "moonshot"),
    ("api.moonshot.cn", "moonshot"),
    # Order matters: zen/go must be checked before zen.
    ("opencode.ai/zen/go", "opencode-go"),
    ("opencode.ai/zen", "opencode-zen"),
    # LiteLLM proxy   default port 4000.
    (":4000", "litellm"),
    # Local LLM providers   match on the distinctive localhost ports.
    # Using ":<port>" catches both "localhost:<port>" and "127.0.0.1:<port>".
    (":11434", "ollama"),
    (":1234", "lm-studio"),
    (":1337", "jan"),
    (":4891", "gpt4all"),
    (":8080", "llama-cpp"),
    (":8000", "vllm"),
    (":5000", "text-generation-webui"),
]


# Default base_url for each known provider. Used to suggest a base_url when
# the user specifies a provider but leaves base_url blank, and as the fallback
# in Agent.__init__ when base_url is omitted from roles.json.
_PROVIDER_DEFAULT_URLS: Dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "z.ai": "https://api.z.ai/api/paas/v4/",
    "openai": "https://api.openai.com/v1",
    "grok": "https://api.x.ai/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "moonshot": "https://api.moonshot.ai/v1",
    "opencode-go": "https://opencode.ai/zen/go/v1",
    "opencode-zen": "https://opencode.ai/zen/v1",
    "litellm": "http://localhost:4000/v1",
    "ollama": "http://localhost:11434/v1",
    "lm-studio": "http://localhost:1234/v1",
    "llama-cpp": "http://localhost:8080/v1",
    "vllm": "http://localhost:8000/v1",
    "text-generation-webui": "http://localhost:5000/v1",
    "jan": "http://localhost:1337/v1",
    "gpt4all": "http://localhost:4891/v1",
}


def suggest_base_url(provider: str) -> str:
    """Return the default base_url for a known provider, or "" if unknown."""
    return _PROVIDER_DEFAULT_URLS.get(provider, "")


# Separator used in keys.json entries: "provider:base_url" -> "api_key".
# A colon is safe because none of our provider IDs contain one.
_KEY_ID_SEPARATOR = ":"


def make_key_id(provider: str, base_url: str) -> str:
    """Build a keys.json key id from a provider and base_url.

    Format: ``"provider:base_url"`` (e.g. ``"ollama:http://localhost:11434/v1"``).
    This lets users store multiple keys for the same provider with different
    base URLs (e.g. self-hosted in different places).
    """
    return f"{provider}{_KEY_ID_SEPARATOR}{base_url}"


def parse_key_id(key_id: str) -> tuple:
    """Split a keys.json key id into (provider, base_url).

    Returns ("", key_id) if the id doesn't contain the separator (legacy
    format   treated as a bare base_url with unknown provider). Also
    returns ("", key_id) when the part before the first ":" is not a known
    provider (e.g. "https://..." is a URL scheme, not a provider prefix).
    """
    if _KEY_ID_SEPARATOR not in key_id:
        return "", key_id
    provider, _, base_url = key_id.partition(_KEY_ID_SEPARATOR)
    # Only treat as "provider:base_url" if the prefix is a known provider.
    # Otherwise it's a legacy bare URL whose scheme contains ":" (e.g.
    # "https://...").
    if provider in KNOWN_PROVIDERS:
        return provider, base_url
    return "", key_id


def infer_provider(base_url: str) -> str:
    """Guess the provider from a base_url, returning "" if unknown."""
    if not base_url:
        return ""
    url_lower = base_url.lower()
    for pattern, provider in _BASE_URL_PATTERNS:
        if pattern in url_lower:
            return provider
    return ""


def resolve_provider(role_config: Dict) -> str:
    """Determine the effective provider for a role.

    Uses the explicit ``provider`` field if set; otherwise infers from
    ``base_url``. Returns "" if neither yields a known provider.
    """
    provider = role_config.get("provider", "") or ""
    if provider:
        return provider
    return infer_provider(role_config.get("base_url", ""))


def resolve_base_url(role_config: Dict) -> str:
    """Determine the effective base_url for a role.

    Uses the explicit ``base_url`` field if set; otherwise falls back to the
    default URL for the role's provider. Returns "" if neither yields a URL
    (e.g. provider is unknown and base_url is blank).
    """
    base_url = role_config.get("base_url", "") or ""
    if base_url:
        return base_url
    provider = resolve_provider(role_config)
    return suggest_base_url(provider)


def resolve_user_agent(role_config: Dict) -> str:
    """Determine the custom User-Agent header value for a role.

    Uses the explicit ``user_agent`` field if set, stripped of surrounding
    whitespace. Returns "" when the role has no custom value, meaning the
    default ``raggie/<version>`` header should be used.
    """
    return (role_config.get("user_agent") or "").strip()


def get_behavior(provider: str) -> Dict[str, Any]:
    """Return the behavior flags for a provider, falling back to defaults."""
    return PROVIDER_BEHAVIORS.get(provider, _DEFAULT_BEHAVIOR)


def filter_messages_for_provider(
    messages: List[Dict], provider: str, reasoning: bool = True
) -> List[Dict]:
    """Return a copy of messages adapted for the given provider.

    - For providers that require ``reasoning_content`` pass-back, assistant
      messages keep their ``reasoning_content``.
    - For providers that don't (e.g. OpenAI Chat Completions), it is stripped
      from every message so the API never sees an unexpected field.
    - For providers that require it on *every* assistant message while
      thinking is on (DeepSeek), assistant messages without one get an empty
      ``reasoning_content`` so the API never rejects the request.

    ``reasoning`` is the role's thinking-mode state: when thinking is off the
    provider returns no reasoning at all, so no placeholder is injected.

    The original list and its dicts are not mutated.
    """
    behavior = get_behavior(provider)
    pass_reasoning = behavior.get("pass_reasoning_back", False)
    require_reasoning = (
        pass_reasoning
        and reasoning
        and behavior.get("reasoning_required_on_assistant", False)
    )

    filtered = []
    for msg in messages:
        if pass_reasoning:
            # Keep reasoning_content on assistant messages; strip from others.
            if msg.get("role") != "assistant" and "reasoning_content" in msg:
                new_msg = {k: v for k, v in msg.items() if k != "reasoning_content"}
                filtered.append(new_msg)
            else:
                new_msg = dict(msg)
                if require_reasoning and new_msg.get("role") == "assistant":
                    # Missing or null both trip DeepSeek's 400; "" satisfies it.
                    if not new_msg.get("reasoning_content"):
                        new_msg["reasoning_content"] = ""
                filtered.append(new_msg)
        else:
            # Strip reasoning_content from all messages.
            if "reasoning_content" in msg:
                new_msg = {k: v for k, v in msg.items() if k != "reasoning_content"}
                filtered.append(new_msg)
            else:
                filtered.append(dict(msg))

    # Tool messages: keep only API-legal fields. Extra metadata (exit_code,
    # subagent_session_id, etc.) is for internal use and must not reach the API.
    _TOOL_KEEP = {"role", "content", "tool_call_id"}
    for i, msg in enumerate(filtered):
        if msg.get("role") == "tool" and not set(msg.keys()).issubset(_TOOL_KEEP):
            filtered[i] = {k: v for k, v in msg.items() if k in _TOOL_KEEP}

    return filtered


def build_completion_kwargs(
    provider: str,
    reasoning: bool,
    reasoning_effort: Optional[str] = None,
    session_id=None,
) -> Dict[str, Any]:
    """Build provider-specific extra kwargs for chat.completions.create.

    Returns a dict of extra keyword arguments to merge into the
    ``chat.completions.create()`` call. This includes:
      - ``extra_body``: provider-specific thinking mode parameters
      - ``reasoning_effort``: the reasoning effort level (if supported)
      - body-level session params (e.g. Kimi's ``prompt_cache_key``)

    Parameters:
      provider: The resolved provider ID (e.g. "deepseek", "z.ai").
      reasoning: Whether thinking/reasoning mode is enabled for this role.
      reasoning_effort: Optional effort level override from the role config.
        If None, uses the provider's default when reasoning is enabled.
      session_id: Optional stable session identifier. Providers that declare
        a ``session_body_param`` behavior get it sent as a top-level body
        field (e.g. Kimi's ``prompt_cache_key`` for prompt caching).

    Returns:
      Dict of extra kwargs. May be empty if the provider needs nothing extra.
    """
    behavior = get_behavior(provider)
    kwargs: Dict[str, Any] = {}
    extra_body: Dict[str, Any] = {}

    # --- Session-scoped body param (e.g. Kimi prompt_cache_key) ---
    if session_id is not None:
        body_param = behavior.get("session_body_param")
        if body_param:
            kwargs[body_param] = str(session_id)

    # --- Thinking mode enablement ---
    thinking_mode = behavior.get("thinking_mode")
    if thinking_mode == "extra_body":
        thinking_key = behavior.get("thinking_key")
        if thinking_key:
            if reasoning:
                extra_body[thinking_key] = behavior.get("thinking_enabled")
            else:
                extra_body[thinking_key] = behavior.get("thinking_disabled")

    # --- Reasoning effort ---
    if behavior.get("reasoning_effort_supported"):
        effort = reasoning_effort
        # For providers with a thinking toggle (deepseek, z.ai, qwen), only
        # send effort when thinking is enabled. For providers without a
        # toggle (openai, grok), always send the default effort.
        thinking_mode = behavior.get("thinking_mode")
        always_send_effort = thinking_mode is None
        if effort is None and (reasoning or always_send_effort):
            effort = behavior.get("reasoning_effort_default")
        if effort is not None:
            valid_values = behavior.get("reasoning_effort_values", [])
            if valid_values and effort not in valid_values:
                # Invalid effort falls back to provider default
                effort = behavior.get("reasoning_effort_default")
            if effort is not None:
                kwargs["reasoning_effort"] = effort

    if extra_body:
        kwargs["extra_body"] = extra_body

    return kwargs


def build_session_headers(provider: str, session_id) -> Dict[str, str]:
    """Build per-call extra_headers for providers that require a session header.

    Some providers (e.g. OpenCode Go/Zen) require a stable session ID header
    for routing optimization and prompt caching. This returns a dict suitable
    for passing as ``extra_headers`` to ``chat.completions.create()``.

    Parameters:
      provider: The resolved provider ID.
      session_id: A stable identifier for the current conversation (e.g. the
        raggie session_id).

    Returns:
      Dict of header name -> value. Empty if the provider doesn't need it.
    """
    if session_id is None:
        return {}
    header_name = get_behavior(provider).get("session_header")
    if not header_name:
        return {}
    return {header_name: str(session_id)}


def strip_forbidden_params(
    kwargs: Dict[str, Any], provider: str
) -> Dict[str, Any]:
    """Remove parameters forbidden by the provider (e.g. Grok rejects stop).

    Returns a new dict with forbidden params removed.
    """
    forbidden = get_behavior(provider).get("forbidden_params", [])
    if not forbidden:
        return dict(kwargs)
    return {k: v for k, v in kwargs.items() if k not in forbidden}
