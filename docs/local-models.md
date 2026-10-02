# Local models

Raggie works with any local server that exposes an OpenAI-compatible Chat Completions endpoint. Several are built in as providers:

| Provider | Default base URL |
|---|---|
| `ollama` | `http://localhost:11434/v1` |
| `lm-studio` | `http://localhost:1234/v1` |
| `vllm` | `http://localhost:8000/v1` |
| `llama-cpp` | `http://localhost:8080/v1` |
| `text-generation-webui` | `http://localhost:5000/v1` |
| `jan` | `http://localhost:1337/v1` |
| `gpt4all` | `http://localhost:4891/v1` |
| `litellm` | `http://localhost:4000/v1` |

## The general recipe

Every local setup is the same three steps:

1. **Start the server** with a model that supports tool calling.
2. **Add a key** with `raggie keys`: choose the provider, press Enter to accept its default base URL, and type `nokey` as the API key.
3. **Edit the role** with `raggie roles`: set the model name, the same provider, and a context window that matches the model.

`raggie setup` runs steps 2 and 3 back to back.

The resulting files look like this (Ollama shown):

`~/.config/raggie/keys.json`

```json
{
  "ollama:http://localhost:11434/v1": "nokey"
}
```

`~/.config/raggie/roles.json`

```json
{
  "code": {
    "model": "qwen2.5:14b",
    "provider": "ollama",
    "base_url": "http://localhost:11434/v1",
    "context_window": 32768,
    "reasoning_effort": "",
    "tools": ["..."],
    "system_prompt_file": "coder_system_prompt.md"
  }
}
```

The key id is `provider:base_url`, and the base URL has to match the role's `base_url` character for character, including any trailing slash. Using `raggie keys` and `raggie roles` keeps them in sync.

## Ollama

```bash
ollama pull qwen2.5:14b
ollama serve          # usually already running
```

Then follow the recipe with provider `ollama` and the model name exactly as `ollama list` shows it.

## vLLM

```bash
pip install vllm
vllm serve Qwen/Qwen2.5-14B-Instruct --enable-auto-tool-choice --tool-call-parser hermes
```

Provider `vllm`, model `Qwen/Qwen2.5-14B-Instruct`.

## LM Studio

1. Download a tool-calling model in LM Studio.
2. Open the **Local Server** tab, load the model and start the server.
3. Follow the recipe with provider `lm-studio`. The model name must match the identifier LM Studio shows for the loaded model.

## A server on another host or port

Give the non-default URL when adding the key, and use the same URL as the role's `base_url`:

```json
{
  "ollama:http://192.168.1.50:11434/v1": "nokey"
}
```

For a server that is not in the provider list, pick the provider whose behavior is closest. Any of the local providers is a safe choice for a plain OpenAI-compatible server.

## Notes

- **Tool calling is required.** Raggie drives everything through function calls. A model without tool-call support cannot use any tools. Qwen2.5 (7B+), Llama 3.1 (8B+) and Mistral (7B+) are known to work.
- **Set `context_window` honestly.** It controls when [context handover](planning-and-subagents.md#context-handover) kicks in. Handover starts when the remaining room drops below half the window (capped at 90,000 tokens), so with a 32k model it starts around 16k tokens used. Set it too high and requests fail before handover can happen.
- **Small windows fill fast.** The system prompt plus 30 tool definitions take several thousand tokens before you type anything. Models with 32k context or more give a much better experience.
- **Reasoning effort is not sent** to local providers, because their servers reject the parameter. Thinking models such as DeepSeek-R1 distills still work: their reasoning content is preserved across turns.
- **`nokey`** is just a placeholder so the key lookup succeeds. Local servers ignore it.
