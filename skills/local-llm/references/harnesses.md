# Agent harnesses with local models

> Harness: "the software layer between the model and the task that constructs
> the context the model sees, mediates its tool calls, validates its outputs,
> and decides when to retry, escalate, or stop." (Zhang et al. 2026)

## Evidence

- **FineEnvs, *The ultimate guide to multi-harness RL*** (HF + Liquid AI, Sep 2026,
  huggingface.co/spaces/FineEnvs/multi-harness-rl). LFM2.5-2.6B base, pass@1 on
  250 data-analysis tasks: Mini-SWE-Agent **62.1**, Codex 40.0, OpenCode 33.6,
  Claude Code **33.2**. GRPO through OpenCode only: OpenCode 34→58, small gains
  elsewhere. Mixing 4 harnesses: 50/49/54 across OpenCode/Claude Code/Codex,
  31% fewer tool calls, overall gain within noise. Lesson: a model fits the
  harness it was trained on. Tool names, argument names, context layout and
  stop conditions all overfit.
- **Lewis, *Same Model, Different Harness*** (arXiv 2608.26218). Qwen3.6-35B-A3B
  Q4 on llama-server. A mechanical context policy plus a stall detector raised
  SWE-bench Verified (20,480-token window) F2P 28%→49% and solutions 43→72,
  and SWE-bench Pro (49K) 15%→33%. The effect is ~0 at a 262K window. Cost:
  ~2× turns and prompt tokens. It transfers without retuning to Devstral,
  Qwen3.8-27B and Nemotron. Code: github.com/sydches/yuj.
- **neuralnoise harness-bench** (WIP, Apr 2026, M3 Max 128 GB, 10 models at Q4 ×
  16 tasks). Pi 76.9% (163 s), Qwen Code 75.0% (191 s), Claude Code 66.2% (306 s),
  OpenCode 63.8% (271 s, and it read the hidden grader in 14 cells), Aider 62.5%
  (384 s). Interactions: gpt-oss-120b collapses in OpenCode; Qwen3.6-27B
  collapses in Aider.
- Counterpoints: SWE-Serve (arXiv 2609.26777) found no gain from model-specific
  harnesses over mini-SWE-agent for frontier models; BankerToolBench found a
  modest accuracy effect but a large cost effect. The harness matters most for
  **small models in small windows**.

## Context rules (what the good harnesses do)

1. **Small scaffolding.** Tokens before the task starts: Claude Code ~25K
   (23 tools), OpenCode ~10K, Pi a short prompt with 4 default tools
   (read, bash, edit, write), mini-swe-agent bash only. At `-c 32768`
   this decides whether there is room left for the task.
2. **Shorten old tool output, keep the newest whole.** Lewis policy: start at
   50% of the window, keep the last 4 tool results intact, keep the head and tail
   of older ones with an omission marker, and halve the cap as age doubles.
   Keep the full record on disk.
3. **Stall detection without a model call:** same command + same failure,
   then tell the model to change approach.
4. **Truncate at admission:** `ls -R`, test logs and build output must be capped
   before entering context.
5. **Stable prefix.** Every history rewrite costs a re-prefill (see server.md
   § Prompt cache). Rules 2 and 5 conflict. Shortening older results in coarse
   steps (not every turn) keeps most turns cache-friendly.
6. **Thinking off or budgeted.** Reasoning tokens share the window.
7. **Same output cap in evaluation as in use** (FineEnvs: a mismatch taught the
   model answers that got cut off).

## Ranking for small local setups

Exact configs: `harness-configs.md`.


| Harness | Use when | Config notes |
|---|---|---|
| **Pi** (`@earendil-works/pi-coding-agent`, Node ≥ 22.19) | default for any local model | 4 default tools; set `contextWindow`/`maxTokens` in models.json (defaults 128000/16384); compaction defaults (16384/20000) wrong at 32K; built-in llama.cpp provider needs router mode, single-model via models.json; `context` extension hook can implement tool-result shortening; no permission system → container |
| **Qwen Code** (`qwen`) | Qwen models | `OPENAI_BASE_URL/OPENAI_API_KEY/OPENAI_MODEL` or `modelProviders` in `~/.qwen/settings.json` with `contextWindowSize`; `autoCompactThreshold` 0.75; docker/podman sandbox |
| **mini-swe-agent** | ≤ 9B models, research, reproducible evals | bash only, linear history, Python; the SWE-bench reference harness; easy to add Lewis-style truncation |
| **OpenCode** (V2 config, repo now anomalyco/opencode) | Gemma 4; when a TUI with LSP is wanted | set `limit.context/output`, `compaction` (buffer ≥ 16K!), `tool_output` (defaults 2000 lines / 50 KiB), deny test paths in `permissions`; custom agent with short `system` for small models; reads graders if visible |
| **Claude Code** | learning, comparing, the user's habits | see below; heaviest scaffolding |
| **Hermes Agent** | to watch | desktop one-click local setup manages its own llama.cpp; reports of corrupted output with Qwen GGUFs; docs want ≥ 64K context |
| **Aider** | chat-style editing, not agents | prose edit blocks, not tool calls; slowest |

## Claude Code against llama-server

Verified in the official docs (code.claude.com env-vars, model-config,
llm-gateway-*, headless, cli-reference), 2026-11-07. Requires a recent
Claude Code; check `claude --version`.

```bash
export CLAUDE_CONFIG_DIR="$HOME/.claude-local"        # NEVER the shared ~/.claude
export ANTHROPIC_BASE_URL="http://127.0.0.1:9931"     # origin, no /v1
export ANTHROPIC_API_KEY="local"                      # not also ANTHROPIC_AUTH_TOKEN
export ANTHROPIC_MODEL="local"                        # = --alias
export ANTHROPIC_DEFAULT_HAIKU_MODEL="local"          # background calls
export ANTHROPIC_DEFAULT_SONNET_MODEL="local" ANTHROPIC_DEFAULT_OPUS_MODEL="local"
export CLAUDE_CODE_SUBAGENT_MODEL="local"
export CLAUDE_CODE_MAX_CONTEXT_TOKENS=32768           # = -c ; custom IDs otherwise assume 200K
export CLAUDE_CODE_MAX_OUTPUT_TOKENS=4096
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1
export CLAUDE_CODE_ATTRIBUTION_HEADER=0
export CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT=1
export NO_PROXY="127.0.0.1,localhost"
# if prefill is slow: API_FORCE_IDLE_TIMEOUT=0 ; if thinking is rejected: CLAUDE_CODE_DISABLE_THINKING=1
claude --bare --tools "Bash,Read,Edit"
```

- `--bare`: no hooks, skills, plugins, MCP, memory or CLAUDE.md; Bash/Read/Edit
  only; auth via `ANTHROPIC_API_KEY` only.
- `CLAUDE_CODE_AUTO_COMPACT_WINDOW` is clamped to ≥ 100K, so it is useless at 32K.
  If llama-server's overflow error is not recognised, run `/compact` by hand.
- It sends `HEAD /api/hello`, `count_tokens` and background requests,
  sometimes in parallel. A single-slot server has crashed under this in the
  past (dev.to "Ghost in the CLI"). Use `-np 2`, or a serializing proxy, if it happens.
- Messages format plus a custom model ID means the full feature set gets sent
  (adaptive thinking, effort, context management). Expect 400s, and fix them
  with the DISABLE variables.

## Evaluating harnesses yourself

- 10–20 small tasks from the user's own work, each with an automatic check
  (a test, an expected file). Run each model in 2–3 harnesses with identical
  `-c`, output cap and time limit. Count pass, time, tool calls, and look for
  grader peeking.
- Harbor (github.com/harbor-framework/harbor, adapters for 40+ harnesses) and
  the FineEnvs OpenEnv capture proxy can automate this against any local endpoint.
- A single seed is noisy at 16 tasks; trust trends, not single cells.
