# Choosing a model and quant

State of 2026-11-07. Check Hugging Face for newer releases before recommending;
open-weight models turn over every few months.

## Memory arithmetic

- GGUF file size ≈ the memory the weights need. KV cache: q8_0 roughly halves
  the f16 size. Plan **≥ 1 GB VRAM headroom** for the CUDA context and compute
  buffers. The desktop (compositor, browser, editor) also holds 0.3–0.8 GB of
  VRAM on a GPU that drives the display.
- **Dense:** file + KV must fit in VRAM. A spill to CPU makes generation crawl.
- **MoE:** the GPU holds attention, KV and shared weights plus as many experts
  as fit; the rest go to RAM (`--n-cpu-moe`). Speed ∝ RAM bandwidth ÷ bytes of
  active experts read per token. Few active parameters (A3B, A4B) is what makes
  a 30B-class model usable on 12 GB.
- RAM must hold the offloaded experts + OS + desktop + harness with margin.
  16 GB total leaves ~10–11 GB for experts with a desktop open.

## Quant rules for agents

- **UD-Q4_K_XL / Q4_K_M are the default.** A 1,360-run local sweep found Q4 ≈ Q8
  on agentic coding (Q4 406 vs Q8 400 of 560 cells) [neuralnoise 2026].
- **Use IQ4_XS** (≈ 15–20% smaller) when RAM is the limit. Do not go below 4 bits:
  an IQ3_XXS 35B-A3B failed an OpenCode task that UD-IQ4_XS passed. Q3 and
  below give malformed tool calls.
- If tool arguments come out garbled at Q4, try Q5_K/Q6_K before blaming the harness.
- Unsloth "UD" (dynamic) quants are the usual choice. ggml-org also publishes
  official GGUFs for major models.

## Candidates (agentic use, evidence where it exists)

| Model | Type | ~Q4 size | Agentic evidence |
|---|---|---|---|
| Qwen3.6-35B-A3B | MoE 3B active, hybrid | UD-IQ4_XS ~18 GB, UD-Q4_K_XL ~22 GB | 80% across 5 harnesses (Q4), fastest strong model; MTP GGUF exists; the model in arXiv 2608.26218 |
| Qwen3.6-27B | dense, hybrid | ~17 GB | 82.5%, only 16/16 cell (with Pi); needs ≥ 20 GB VRAM to be fast |
| Qwen3.8-27B | dense | ~17 GB | released Aug 2026 (Apache 2.0), 262K context; harness-sensitive (20%→35% with context mgmt) |
| Gemma 4 26B-A4B | MoE 4B active | ~16 GB | 70%; best paired with OpenCode (15/16); **tool calling unreliable in llama.cpp** (see below) |
| Gemma 4 31B | dense | ~19 GB | 81% |
| gpt-oss-20b | MoE | ~12–13 GB (MXFP4) | 56% Q4, 65% Q8; native Harmony parser; fits ~12 GB |
| gpt-oss-120b | MoE | ~63 GB | 77.5%, very fast with Pi; needs 64 GB+ RAM |
| Qwen3.5-9B, Gemma 4 12B, Gemma 4 E4B | dense | 3–9 GB | no harness data; good for plumbing tests and long context |
| LFM2.5-2.6B / Qwen3.5-2B multi-harness RL (FineEnvs) | dense | < 3 GB | trained *through* harnesses; data-analysis tasks; research toys |
| Qwen3-Omni-30B-A3B | MoE | | 34%: omni-tuned models are poor agents |

Percentages: neuralnoise harness-bench (16 tasks, 5 harnesses, M3 Max 128 GB,
WIP). They indicate rank, not absolute quality.

## Official sampling settings (model cards, 2026-11-07)

| Model | Mode | temp | top_p | top_k | min_p | presence_penalty | Thinking switch |
|---|---|---|---|---|---|---|---|
| Qwen3.6 (35B-A3B, 27B) | non-thinking (agents at ≤ 64K) | 0.7 | 0.8 | 20 | 0 | 1.5 | `--chat-template-kwargs '{"enable_thinking":false}'`; `/no_think` soft switch is NOT supported |
| Qwen3.6 | thinking, precise coding | 0.6 | 0.95 | 20 | 0 | 0 | |
| Qwen3.6 | thinking, general | 1.0 | 0.95 | 20 | 0 | 1.5 (Unsloth says 0) | |
| Gemma 4 | all | 1.0 | 0.95 | 64 | — | — | `{"enable_thinking":true/false}` via llama-server (not llama-cli); system prompt `<\|think\|>` natively |
| gpt-oss-20b | — | not stated | | | | | system prompt `Reasoning: low/medium/high`; Harmony format only |

- Qwen3.6 card: allow 32,768 output tokens and ≥ 128K context *to preserve
  thinking*. On a 32K window, use **non-thinking mode** for agents.
- Set sampling on the server (`--temp 0.7 --top-p 0.8 --top-k 20 --min-p 0
  --presence-penalty 1.5`) or per request through the harness, not both.

## Tool-calling status in llama.cpp (2026-11-07)

- **Qwen3.6:** works with `--jinja` (default). Unsloth improved nested-object
  parsing in its GGUF templates, so prefer Unsloth or ggml-org GGUFs.
- **Gemma 4:** **unreliable.** Issue #25072 ("does not match the expected
  peg-gemma4 format") was closed as stale with no fix confirmed; #29655
  (unstable multi-line streamed tool calls) is open. The model needs
  `reasoning_content` sent back on tool turns (Pi compat
  `requiresReasoningContentOnAssistantMessages`). Run the probe several times
  before trusting it.
- **gpt-oss:** mostly works through the native Harmony parser, but #30377
  (tools + json_schema loop in reasoning, open) and malformed channel headers in
  ~4% of turns at temp 1.0 (#27720) are reported. Lower the temperature for agents.

## Example profile: 12 GB VRAM + 16 GB RAM

1. Plumbing: Qwen3.5-9B Q4_K_M or gpt-oss-20b, fully on GPU, 32K+ context.
2. Main agent: **Qwen3.6-35B-A3B UD-IQ4_XS**, `-c 32768`, KV q8_0,
   `--n-cpu-moe` ≈ 20–24 (sweep), non-thinking sampling (0.7/0.8/20/1.5), `-np 1`. Close the browser
   during long runs. Q4_K_XL (22 GB) leaves no RAM for the system.
3. Alternative: gpt-oss-20b (lower temperature). Gemma 4 26B-A4B only after the probe passes repeatedly.
4. Dense 27B–31B: too slow here; save them for ≥ 24 GB VRAM.
5. A 32K window is tight for heavy harnesses. Prefer Pi or mini-swe-agent.
