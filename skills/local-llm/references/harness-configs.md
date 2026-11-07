# Harness configurations for a local llama-server

Target: llama-server on `http://127.0.0.1:9931`, `--alias local`, `-c 32768`.
Read from each project's docs on 2026-11-07. Harnesses change fast, so
re-check the docs if a key is rejected. Unless stated otherwise, every value
below comes from the docs. Lines marked *(inferred)* are composed from
documented keys but not shown as an example in the docs.

**Rule for every harness:** declare the real context window (`-c`) and a modest
output cap. Most of them assume 128K–200K for unknown models, compact far too
late, and then overflow.

## Pi (`@earendil-works/pi-coding-agent`)

Install: `npm install -g --ignore-scripts @earendil-works/pi-coding-agent`
(Node ≥ 22.19). Agent dir `~/.pi/agent` (override with `PI_CODING_AGENT_DIR`).

**Two ways to connect:**
1. The built-in llama.cpp provider needs **router mode**: start
   `llama serve --no-models-autoload -ngl all -c 32768` (the `llama` binary,
   no `-m`), then `/login llama.cpp` or `LLAMA_BASE_URL=http://127.0.0.1:9931`,
   then `/llama` to load and `/model` to select. It cannot drive a
   single-model server.
2. **Single-model `llama-server -m …`**: generic provider in
   `~/.pi/agent/models.json` *(inferred: the docs only show Ollama)*:

```json
{
  "providers": {
    "llamacpp": {
      "name": "llama-server",
      "baseUrl": "http://127.0.0.1:9931/v1",
      "api": "openai-completions",
      "apiKey": "local",
      "models": [{
        "id": "local",
        "reasoning": false,
        "input": ["text"],
        "contextWindow": 32768,
        "maxTokens": 4096,
        "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 }
      }]
    }
  }
}
```

- `contextWindow` defaults to **128000** and `maxTokens` to 16384. Always set both.
- `compat` (openai-completions): `chatTemplateKwargs` (e.g.
  `{"enable_thinking": false}`), `thinkingTokenBudgetField: "thinking_budget_tokens"`
  for llama.cpp, `requiresReasoningContentOnAssistantMessages` (Gemma 4 needs
  reasoning sent back on tool turns), `maxTokensField`.
- `samplingParams` per model (see models.md for the values from the model card).

**Compaction** (`~/.pi/agent/settings.json`): it triggers when
`contextTokens > contextWindow − reserveTokens`, keeps `keepRecentTokens` of the
newest entries, and has an LLM summarize the rest into Goal / Constraints /
Progress / Decisions / Next steps / Critical context + read/modified files.
Tool results are never cut mid-span, and no pruning step is documented. The
defaults (16384 / 20000) are wrong at 32K: compaction would fire at 16K and keep
everything. *(inferred)* For 32K:

```json
{ "compaction": { "enabled": true, "reserveTokens": 6144, "keepRecentTokens": 8192 } }
```

**Extensions** (`~/.pi/agent/extensions/*.ts`, TypeScript): `pi.registerTool({...})`;
request hooks in this order: `context` (returns `{messages}`, without the system
message), `context_with_system`, `before_provider_headers`,
`before_provider_request`; plus `tool_result` (patch content), `tool_call`
(block or rewrite), `session_before_compact` (custom summary). **`context` is
where the Lewis tool-result shortening policy (harnesses.md) can be
implemented.** Rewrite in coarse steps to keep the prefix cache warm.

Built-in read/bash output caps: not documented. Watch for huge outputs.
No permission system: run in a container or a scratch checkout.

## Qwen Code (`@qwen-code/qwen-code`)

Install: `npm install -g @qwen-code/qwen-code@latest` (Node ≥ 22).

Quick start with environment variables:
```bash
OPENAI_BASE_URL=http://127.0.0.1:9931/v1 OPENAI_API_KEY=local OPENAI_MODEL=local qwen
```

`~/.qwen/settings.json` (project: `.qwen/settings.json`). The provider block
follows the docs' vLLM pattern *(values inferred)*:

```json
{
  "modelProviders": { "openai": [{
    "id": "local", "envKey": "LOCAL_API_KEY", "baseUrl": "http://127.0.0.1:9931/v1",
    "generationConfig": { "contextWindowSize": 32768, "samplingParams": { "max_tokens": 4096 } }
  }]},
  "env": { "LOCAL_API_KEY": "local" },
  "security": { "auth": { "selectedType": "openai" } },
  "model": { "name": "local" },
  "context": { "autoCompactThreshold": 0.75 },
  "telemetry": { "enabled": false },
  "privacy": { "usageStatisticsEnabled": false }
}
```

- `generationConfig` must sit in the provider entry. A top-level
  `model.generationConfig` is ignored for provider models.
- `context.autoCompactThreshold` defaults to 0.85. Lower it to 0.75 at 32K so
  the summary call still fits.
- Approval: `--approval-mode plan|default|auto-edit|auto|yolo`.
- Sandbox: `-s` / `QWEN_SANDBOX=docker|podman` (image `qwen-code-sandbox`). Use it for yolo runs.
- Limits: `model.sessionTokenLimit`, `model.maxSessionTurns` (default −1 = none).

## mini-swe-agent

Install: `pip install mini-swe-agent` (or `uvx mini-swe-agent`, which leaves
nothing installed). Run with `mini`. Settings: `mini-extra config set KEY VALUE`.

Model block in a config yaml *(model name inferred from the docs' vLLM pattern)*:

```yaml
model:
  model_name: "openai/local"
  model_kwargs:
    custom_llm_provider: "openai"
    api_base: "http://127.0.0.1:9931/v1"
    drop_params: true
  cost_tracking: "ignore_errors"      # unknown local model: no price in the litellm registry
agent:
  step_limit: 100
  cost_limit: 0
```

- Key: litellm reads `OPENAI_API_KEY` (set any value). Or use a model registry
  (`LITELLM_MODEL_REGISTRY_PATH`, with `max_tokens`, `input_cost_per_token: 0`,
  …) instead of `ignore_errors`.
- Output truncation sits in `observation_template`: the default keeps output
  under 10,000 characters, otherwise it shows a 5,000-character head and tail.
  At 32K, lower it to ~4,000 / 1,500.
- `environment_class: docker` for isolation. Global caps:
  `MSWEA_GLOBAL_CALL_LIMIT`, `MSWEA_GLOBAL_COST_LIMIT`.
- Linear history, bash only: the easiest harness to modify, e.g. adding
  Lewis-style truncation of older observations.

## OpenCode (V2 config; repo moved to `anomalyco/opencode`)

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "local/local",
  "providers": { "local": {
    "name": "llama-server",
    "package": "@opencode/ai/providers/openai-compatible",
    "settings": { "baseURL": "http://127.0.0.1:9931/v1", "headerTimeout": 600000 },
    "compatibility": { "reasoningField": "reasoning_content" },
    "models": { "local": {
      "modelID": "local",
      "capabilities": { "tools": true, "input": ["text"], "output": ["text"] },
      "limit": { "context": 32768, "output": 4096 }
    }}
  }},
  "compaction": { "auto": true, "buffer": "25%", "keep": { "tokens": 6000 } },
  "tool_output": { "max_lines": 400, "max_bytes": 16384 },
  "permissions": [
    { "action": "read", "resource": "*/tests/*", "effect": "deny" }
  ]
}
```

- Compaction: `buffer` is the share of the window kept free (default 15%, at
  least 16K). The whole conversation is summarized and the last
  `keep.tokens` (default 15,000) are kept, with long tool output shortened.
  The 16K minimum buffer means compaction fires at ~16K on a 32K model *(inferred)*.
- `tool_output` defaults (2000 lines / 50 KiB) are far too large for 32K.
- Permissions: an array of `{action, resource, effect}` rules; the last match
  wins. The default allows everything, so deny test or grader paths explicitly.
  Shell commands (`cat tests/…`) and grep may bypass a `read` deny (not stated
  in the docs). Keep graders outside the workspace.
- Custom agents: `.opencode/agents/<name>.md` or `agents.<id>` with `system`
  (replaces the base prompt), `permissions`, `steps`. Use this to give a small
  model a short prompt and fewer tools (deny `execute` to remove Code Mode).
- Default system prompt and tool-schema size: not documented. Earlier
  measurements put it at ~10K tokens. Measure it on the first turn (probe or
  server log `prompt_n`).

## Claude Code

See harnesses.md § Claude Code (environment variables, `--bare`, separate
`CLAUDE_CONFIG_DIR`).
