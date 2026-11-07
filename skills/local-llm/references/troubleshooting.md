# Troubleshooting local LLM agents

Run `scripts/llm_probe.py` first. It separates engine and template problems
from harness problems.

## 1. Tool calls arrive as text

Symptoms: `<tool_call>`, `<function=…>`, `{"name": …}` or Harmony channel
markers inside `message.content`, and `tool_calls` empty.

1. `--jinja` on? It is the default in recent builds, but older builds and
   wrappers turn it off. Qwen3–3.6, Qwen3-Coder and DeepSeek-R1 distills need it.
2. Server log: `Chat format: Generic` means no native parser matched. It
   still works, but uses more tokens and is less reliable. Look for a
   model-specific template.
3. A broken embedded template (this happened with some Qwen3 and Gemma 4
   quants): serve a fixed one with `--chat-template-file fixed.jinja`, taken
   from the original HF repo or an Unsloth discussion.
4. Update llama.cpp: parsers for new models (Gemma 4, Qwen3.6 XML tool calls)
   landed after their release.
5. The harness must send `tools` in OpenAI format and must not send an empty
   `tools: []` (some servers return 400).
6. Ollama users: Ollama applies its own templates. Problems there do not
   imply llama-server has them, and vice versa.

## 2. Malformed or wrong tool arguments

- Weights below 4 bits, or KV `q4_0`: go to UD-Q4_K_XL/Q5_K and KV q8_0.
- Speculative decoding: remove `--spec-type`/draft model and test again.
- Sampling: use the model card's recommended temperature and top_p.
  Agents usually want them lower than chat does.
- A tool schema too complex for the model: fewer tools, flatter arguments.
- A model trained on another harness's tool names (see harnesses.md, FineEnvs).
  Try the harness native to the model family.

## 3. Slow turns

Measure, don't guess: the probe prints prefill and generation tok/s and
`cache_n` for a repeated prefix.

- **Cold prefill:** first turn = system prompt + tool schemas. 25K tokens at
  500 tok/s is 50 s. Raise the harness timeouts (OpenCode `headerTimeout`,
  Claude Code `API_FORCE_IDLE_TIMEOUT=0`). Choose a lighter harness.
  Raise `-ub` (512 → 1024/2048) if VRAM allows.
- **Every turn slow:** the prefix cache misses.
  - `cache_n` ≈ 0 on turn 2 means the prompt changed early: timestamp, attribution
    block (`CLAUDE_CODE_ATTRIBUTION_HEADER=0`), tool order, history rewrite.
  - `-np > 1`: the request landed in a different slot. Use `-np 1` or set `id_slot`.
  - Hybrid model (Qwen3.5/3.6): rewinds stop at checkpoints; lower
    `--checkpoint-min-step`.
  - Try `--cache-reuse 256`.
- **Generation slow with MoE offload:** RAM-bandwidth bound. Fewer experts on
  CPU (lower `--n-cpu-moe`, shorter `-c` to free VRAM), CPU power profile
  `performance`, `-t` = physical cores, close RAM-hungry apps, check that
  swap is not in use (`free -m`, `vmstat 1`).

## 4. Memory

- OOM at load: raise `--n-cpu-moe`, lower `-c`, KV q8_0.
- OOM at the first long prompt: compute buffers grow with `-ub`; lower it, or
  free ~1 GB more VRAM.
- System freezes or swaps: offloaded experts plus apps exceed RAM. Pick a
  smaller quant (IQ4_XS), `--mlock` to fail fast, or a model that fits in VRAM.
- `libcudart.so.N` not found: `LD_LIBRARY_PATH` only set in interactive shells;
  rebuild with `-DCMAKE_BUILD_RPATH`.

## 5. Agent behaviour

- Loops on the same failing command: no stall detection. Use a harness that has
  one, or add a rule: "if the same command fails twice, change approach".
- Gives up early or claims success: verify with tests. The harness should run
  the check, not trust the model.
- Reads tests or graders: hide graders outside the workspace (OpenCode was
  seen doing this).
- Context overflow mid-task: tool output too large. Cap it at admission, and
  set the harness context limit to the real `-c`.
