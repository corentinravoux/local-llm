# llama-server for agents

Flags verified against `llama-server --help` of build b12189 (2026-11-07).
Re-verify on the installed build: defaults move.

## Baseline agent server

```bash
llama-server \
  -m /path/model.gguf  --alias local \
  -c 32768 \                       # explicit; 0 = model max (often far beyond VRAM)
  -ngl 99 \                        # all layers on GPU (MoE: combine with --n-cpu-moe)
  -fa on \                         # flash attention: needed for quantized V cache
  -ctk q8_0 -ctv q8_0 \            # halves KV memory; q4_0 harms tool calling
  -np 1 \                          # one slot: predictable memory, whole cache for one agent
  --jinja \                        # default on; model's own template and tool parser
  --reasoning-format deepseek \    # thinking -> reasoning_content (harness must map it)
  --host 127.0.0.1 --port 9931     # default port is 9931 since ~b11521 (was 8080)
```

**Thinking.** For agent loops, either turn it off,
`--chat-template-kwargs '{"enable_thinking":false}'` (Qwen3.x), or cap it with
`--reasoning-budget N` (`0` = end immediately, `-1` = unlimited). Thinking
tokens consume the same window as the task.

**Download.** `-hf <user>/<repo>:<QUANT>` (e.g. `unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_XS`)
downloads into the HF cache. `hf download <repo> --include "*IQ4_XS*" --local-dir …`
gives a plain file path. Keep repo-native quant labels (UD-Q4_K_XL ≠ Q4_K_M).

## MoE offload (`--n-cpu-moe N`)

Keeps the expert weights of the first N layers in RAM. Attention, the KV cache
and the shared weights stay on the GPU.

- Start high (all experts: `--cpu-moe`, or N = number of layers), confirm it
  loads, then lower N until VRAM is ~0.5–1 GB from full at the target `-c`.
  A larger context takes VRAM that would otherwise hold experts.
- Generation speed is bounded by **RAM bandwidth**. Dual-channel DDR4-3000 is
  ~48 GB/s; DDR5-5600 is ~90 GB/s. Blog numbers measured on DDR5 do not carry over.
- `-t <physical cores>` for the CPU-side experts. Pin with `powerprofilesctl set performance`.
- Sweep with `llama-bench -m model.gguf -ngl 99 -fa 1 -ctk q8_0 -ctv q8_0 --n-cpu-moe 18,20,22,24 -p 2048 -n 128`
  (check that `--n-cpu-moe` is accepted by the installed llama-bench; otherwise sweep with llama-server).
- RAM budget: offloaded experts + OS + desktop + harness (Node/Python) must fit
  in RAM without swapping. The model is mmapped, so under memory pressure its
  pages get evicted silently and speed collapses. `--mlock` (raise `memlock`
  first) or `--no-mmap` makes this deterministic.
- Dense models do not offload well: a dense layer on CPU runs at CPU speed for
  every token.

## Prompt cache: why turn 2 should be cheap

- `cache_prompt` is on by default. A request whose prompt shares a prefix with
  the slot's cached tokens only processes the new suffix. The response's
  `timings.cache_n` and `timings.prompt_n` show it (the probe script reports both).
- Anything that changes early tokens forces re-prefill from that point:
  compaction, tool-result truncation, a timestamp or random id in the system
  prompt, a harness that rewrites history (Claude Code does), a different tool order.
- `--cache-reuse N` (default 0) reuses chunks by KV shifting when the prefix
  diverges in the middle. Try 256 when a harness edits history.
- `-cram N` (MiB, default 8192): RAM-side prompt cache for idle slots. On a
  low-RAM box it competes with offloaded experts; consider `-cram 2048` or `0`.
- **Hybrid models** (Qwen3.5/3.6 DeltaNet + attention, SWA models) cannot
  rewind the recurrent state token by token. They need **context checkpoints**
  (`--ctx-checkpoints N`, default 32; `--checkpoint-min-step`, default 8192
  tokens). With the default step, a prefix change can force up to ~8K tokens of
  re-prefill. A smaller step (2048) trades RAM for cheaper rewinds.
- `-np > 1` splits the context between slots (`-c` is shared), and requests
  land in a slot by prompt similarity (`-sps`, default 0.10). Keep `-np 1`
  unless the harness genuinely runs parallel calls (Claude Code background
  calls; see harnesses.md).

## Speculative decoding (MTP)

- `--spec-type draft-mtp` with an **MTP GGUF** (e.g. `unsloth/Qwen3.6-35B-A3B-MTP-GGUF`;
  plain GGUFs lack the heads). Start with `--spec-draft-n-max 2`. The old name
  `--spec-type mtp` is rejected by new builds.
- Reported +30% to ~3× on generation, depending on hardware. It does not help prefill.
- Turn it off first when tool calls truncate or loop.

## Router mode (several models, one endpoint)

Start without `-m`: `--models-dir DIR` (or `--models-preset file.ini`),
`--models-max 1` on a single small GPU (the default 4 counts models, not VRAM),
`--sleep-idle-seconds` to free VRAM. Requests choose the model by its name.
llama-swap is the alternative when mixing engines.

## Endpoints

- OpenAI: `/v1/chat/completions`, `/v1/models`. Anthropic: `/v1/messages`,
  `/v1/messages/count_tokens`. Native: `/health`, `/props` (n_ctx, chat
  template, modalities), `/slots`, `/metrics` (needs `--metrics`).
- Parallel tool calls are off unless the request sets `"parallel_tool_calls": true`.

## Build (CUDA)

```bash
cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=<sm, e.g. 86> \
      -DCMAKE_CUDA_COMPILER=$CUDA_HOME/bin/nvcc -DCMAKE_BUILD_RPATH=$CUDA_HOME/lib64
cmake --build build --config Release -j $(nproc)
```

A toolkit newer than the driver's CUDA version works for SASS built for the
exact architecture (minor-version compatibility). "CUDA driver version is
insufficient" means: rebuild with an older toolkit, or update the driver.
Vulkan (`-DGGML_VULKAN=ON`) needs no toolkit, but is slower at prefill on NVIDIA.
