---
name: local-llm
description: "Use when running, configuring, benchmarking or debugging a LOCAL LLM — llama.cpp (llama-server, llama-bench, GGUF, quantization, --n-cpu-moe, MTP, router mode), Ollama, LM Studio, vLLM on a consumer GPU — and above all when wiring a local model into an agent harness (Pi, OpenCode, Qwen Code, mini-swe-agent, Claude Code via ANTHROPIC_BASE_URL, Aider, Hermes): tool calls showing up as text, malformed tool arguments, slow prefill, KV prefix-cache misses, context too small, choosing a model or quant for a given VRAM/RAM budget."
---

# Local LLMs: engine, model, harness

## Mental model

A local agent is three layers. Debug them in this order, because each one hides
the next:

1. **Engine** (llama-server): does the model load, at what speed, with what
   context, and is the prompt cache reused between turns?
2. **Wire format** (chat template, tool parser, reasoning field): does a tool
   call come back as a structured `tool_calls` entry, or as text?
3. **Harness** (what builds the context and runs tools): how many tokens of
   scaffolding, how it handles old tool output, retries, stalls, compaction.

**The harness is not a detail.** The same weights score 62% vs 33% across
harnesses (FineEnvs, 2.6B model). A context-management change alone took
Qwen3.6-35B-A3B from 43 to 72 SWE-bench solutions at a 20K window, and the gain
vanished at 262K (arXiv 2608.26218). The smaller the model and the window, the
more the harness decides the result. Details: `references/harnesses.md`.

## Before recommending anything

1. **Read the machine, don't assume it:** `nvidia-smi`, `free -g`, the RAM speed
   (`sudo dmidecode -t memory`, which the user runs), the llama.cpp build
   (`git -C <llama.cpp> describe --tags`). Project memory may already hold a
   machine profile; check it.
2. **Verify flags against the installed binary**, not against memory or blogs:
   `llama-server --help | grep -A1 -- '<flag>'`. llama.cpp changes defaults
   often. Since ~b11521 the default port is **9931** (was 8080), `--jinja` is
   on by default, and `-fa` takes `on|off|auto`.
3. A llama.cpp built with CUDA in a non-standard prefix may only find
   `libcudart` through `LD_LIBRARY_PATH` from `~/.bashrc`. Non-interactive
   shells fail with "libcudart.so.N: cannot open shared object file". Either
   prefix the command (`LD_LIBRARY_PATH=$CUDA_HOME/lib64 …`) or rebuild with
   `-DCMAKE_BUILD_RPATH=$CUDA_HOME/lib64`.

## Workflow

1. **Size the model to the memory** (`references/models.md`). Dense models must
   fit in VRAM. MoE models can put experts in RAM with `--n-cpu-moe N`, at a
   speed bounded by RAM bandwidth. Weights ≥ 4-bit for agents.
2. **Start the server with agent-safe flags** (`references/server.md`):
   `-fa on -ctk q8_0 -ctv q8_0 -np 1 --jinja`, an explicit `-c` and `--alias`,
   thinking off or budgeted, `--host 127.0.0.1` only.
3. **Probe before any harness:** `python3 -I scripts/llm_probe.py --url
   http://127.0.0.1:9931`. It checks health and context, a structured tool
   call, prefix-cache reuse across two turns (`cache_n`), prefill and
   generation tok/s, and the Anthropic `/v1/messages` endpoint. Fix every FAIL
   here; a harness only blurs them.
4. **Pick the harness** for the model size and window (`references/harnesses.md`).
   Light first (Pi, mini-swe-agent, Qwen Code), heavy last (Claude Code).
5. **Evaluate on the user's own small task set in ≥ 2 harnesses.** Harness
   rankings do not transfer between models. Keep the output-token cap and
   context identical across runs. Measure with `llama-bench` and the probe,
   not with blog numbers.

## Hard rules

- **Never `--host 0.0.0.0`** without `--api-key` and the user's explicit request.
- **Never route the user's main Claude Code config to a local model.** Use a
  separate `CLAUDE_CONFIG_DIR` (e.g. `~/.claude-local`). A shared
  `settings.json` behind symlinks reroutes every account.
- **KV cache q8_0 at most, never q4_0** for tool use (official llama.cpp
  warning). **No Q3/IQ3 or lower weights** for agents: they produce malformed
  calls.
- **Download models to a large data disk**, not to a small root partition.
  `hf download` and `llama-server -hf` cache in `~/.cache/huggingface` unless
  `HF_HOME` is set.
- **Report measured numbers as measured, estimates as estimates.** Most
  tok/s figures online are bandwidth estimates or measured on other hardware.
- **Turn speculative decoding (MTP/draft) off while debugging tool calls.**
  It is a known cause of truncated or looping calls.

## Quick diagnosis

| Symptom | First suspect | See |
|---|---|---|
| `<tool_call>` / `<function=` in the reply text | template or parser: `--jinja` off, broken embedded template, old build | troubleshooting.md §1 |
| Tool arguments are invalid JSON | quant too low, KV q4, MTP on, temperature too high | §2 |
| Every turn is slow, not just the first | prefix cache missed: the harness rewrites history, timestamps, `-np` > 1 with a small `-sps`, hybrid model without checkpoints | §3 |
| Harness hangs, then times out | cold prefill of a 10–25K-token system prompt; raise the harness timeout and measure prefill tok/s | §3 |
| Model loops on the same failing command | harness has no stall detection; use a harness with it, or prompt it | harnesses.md |
| Context overflow mid-task | `-c` too small for the harness scaffolding; old tool output never shortened | harnesses.md §context |
| HTTP 400 from Claude Code | beta fields/thinking params; `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`, `CLAUDE_CODE_DISABLE_THINKING=1` | harnesses.md §Claude Code |
| OOM at first long prompt | `-ub` too high, too few experts on CPU; raise `--n-cpu-moe` by 1–2 | server.md |

## References

- `references/server.md`: llama-server recipes, flag meanings, MoE offload tuning, MTP, router mode, prompt cache.
- `references/models.md`: model and quant choice by VRAM/RAM, with evidence.
- `references/harnesses.md`: harness evidence, ranking, configs (Pi, OpenCode, Qwen Code, mini-swe-agent, Claude Code), context-management rules.
- `references/troubleshooting.md`: symptom → cause → fix.
- `scripts/llm_probe.py`: stdlib-only endpoint probe (run with `python3 -I`).
- Sources are cited where they are used in each reference file. Numbers are
  dated (Nov 2026); re-check model and flag facts before relying on them.
- External engine reference, current as of Oct 2026: ScaleDockHQ/llm-skills
  (`llama-cpp`, `gguf-quantization`, MIT). Avoid the Orchestra/Hermes
  `llama-cpp` skills for flags: they are outdated (port 8080, `make LLAMA_CUDA=1`).
