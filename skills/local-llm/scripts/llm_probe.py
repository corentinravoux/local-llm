#!/usr/bin/env python3
"""Probe a local LLM server (llama-server, or any OpenAI-compatible endpoint)
before pointing an agent harness at it.

Checks, in order:
  health      GET /health
  props       GET /props            context size, template present (llama-server only)
  models      GET /v1/models        model id to use
  tool_call   POST /v1/chat/completions with one tool: structured call, valid JSON args,
              no tool markup leaking into the text
  cache       two requests sharing a long prefix: is the prefix reused (timings.cache_n)?
              also reports prefill tok/s
  generation  decode tok/s on a ~128-token answer
  anthropic   POST /v1/messages (needed for Claude Code)

Standard library only. Run with: python3 -I llm_probe.py --url http://127.0.0.1:9931
Exit code 1 if any check FAILs.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

LEAK_MARKERS = ("<tool_call>", "<function=", "</tool_call>", "<|tool_call", "<|channel|>", '"name": "get_weather"')

TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["city"],
        },
    },
}


def filler(n_words):
    """Deterministic, non-repetitive-looking text so the prefix is long but stable."""
    words = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike "
             "november oscar papa quebec romeo sierra tango uniform victor whiskey xray").split()
    return " ".join(f"{words[i % len(words)]}{i % 97}" for i in range(n_words))


class Probe:
    def __init__(self, url, api_key, timeout):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.results = []

    def req(self, method, path, body=None, headers=None):
        h = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.url + path, data=data, headers=h, method=method)
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(r, timeout=self.timeout) as resp:
                raw = resp.read()
                code = resp.status
        except urllib.error.HTTPError as e:
            raw, code = e.read(), e.code
        dt = time.monotonic() - t0
        try:
            js = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            js = None
        return code, js, raw, dt

    def record(self, name, status, detail):
        self.results.append((name, status, detail))
        print(f"[{status:4}] {name:10} {detail}", flush=True)

    def chat(self, model, messages, **kw):
        body = {"model": model, "messages": messages, "temperature": 0, "cache_prompt": True}
        body.update(kw)
        return self.req("POST", "/v1/chat/completions", body)


def run(args):
    p = Probe(args.url, args.api_key, args.timeout)
    try:
        code, js, raw, _ = p.req("GET", "/health")
    except (urllib.error.URLError, OSError) as e:
        p.record("health", "FAIL", f"cannot connect to {args.url}: {e}")
        return p
    ok = code == 200 and (js or {}).get("status", "ok") == "ok"
    p.record("health", "PASS" if ok else "FAIL", f"HTTP {code} {raw[:80]!r}" if not ok else "server up")

    # props (llama-server specific)
    n_ctx = None
    code, js, _, _ = p.req("GET", "/props")
    if code == 200 and isinstance(js, dict):
        n_ctx = js.get("n_ctx") or (js.get("default_generation_settings") or {}).get("n_ctx")
        tmpl = js.get("chat_template") or ""
        detail = f"n_ctx={n_ctx} template={'yes' if tmpl else 'NO'} ({len(tmpl)} chars)"
        if js.get("model_path"):
            detail += f" model={js['model_path'].rsplit('/', 1)[-1]}"
        p.record("props", "PASS" if tmpl else "WARN", detail)
        if n_ctx and n_ctx < 16384:
            p.record("props", "WARN", f"n_ctx {n_ctx} < 16384: most harnesses need 16-32K just for scaffolding")
    else:
        p.record("props", "SKIP", f"/props HTTP {code} (not llama-server?)")

    model = args.model
    code, js, _, _ = p.req("GET", "/v1/models")
    ids = [m.get("id") for m in (js or {}).get("data", [])] if code == 200 and isinstance(js, dict) else []
    if not model:
        model = ids[0] if ids else "local"
    p.record("models", "PASS" if ids else "WARN", f"ids={ids} using '{model}'")

    # tool call
    if "tool_call" not in args.skip:
        code, js, raw, dt = p.chat(model, [
            {"role": "system", "content": "You are a helpful assistant. Use tools when they are relevant."},
            {"role": "user", "content": "What is the weather in Paris right now? Use the tool."},
        ], tools=[TOOL], max_tokens=args.max_tokens)
        if code != 200 or not js:
            p.record("tool_call", "FAIL", f"HTTP {code} {raw[:200]!r}")
        else:
            msg = (js.get("choices") or [{}])[0].get("message", {})
            calls = msg.get("tool_calls") or []
            content = msg.get("content") or ""
            leaked = [m for m in LEAK_MARKERS if m in content]
            if calls:
                fn = calls[0].get("function", {})
                try:
                    a = json.loads(fn.get("arguments") or "{}")
                    good = fn.get("name") == "get_weather" and isinstance(a, dict) and "city" in a
                    p.record("tool_call", "PASS" if good else "FAIL",
                             f"{fn.get('name')}({fn.get('arguments')}) in {dt:.1f}s"
                             + ("" if good else " -> wrong name or missing 'city'"))
                except json.JSONDecodeError:
                    p.record("tool_call", "FAIL", f"arguments not JSON: {fn.get('arguments')!r}")
            elif leaked:
                p.record("tool_call", "FAIL", f"tool markup in text {leaked}: template/parser problem "
                         "(--jinja, --chat-template-file, update llama.cpp)")
            else:
                p.record("tool_call", "FAIL", f"no tool call; reply: {content[:150]!r}")
            if msg.get("reasoning_content"):
                p.record("tool_call", "INFO", f"reasoning_content present ({len(msg['reasoning_content'])} chars): "
                         "harness must map it, or turn thinking off")

    # prefix cache + prefill speed
    if "cache" not in args.skip:
        system = "Reference notes (ignore unless asked):\n" + filler(args.prefix_words)
        t = []
        for q in ("Reply with the single word: one.", "Reply with the single word: two."):
            code, js, raw, dt = p.chat(model, [{"role": "system", "content": system},
                                               {"role": "user", "content": q}], max_tokens=8)
            if code != 200 or not js:
                p.record("cache", "FAIL", f"HTTP {code} {raw[:200]!r}")
                break
            t.append((js.get("timings") or {}, dt))
        if len(t) == 2:
            (t1, d1), (t2, d2) = t
            if not t1:
                p.record("cache", "SKIP", f"no 'timings' in response (not llama-server); wall {d1:.1f}s then {d2:.1f}s")
            else:
                n1 = t1.get("prompt_n", 0) + t1.get("cache_n", 0)
                pps = t1.get("prompt_per_second")
                p.record("prefill", "INFO", f"{t1.get('prompt_n')} tokens at {pps:.0f} tok/s" if pps else str(t1))
                c2, n2 = t2.get("cache_n"), t2.get("prompt_n")
                if c2 is None:
                    ok = n2 is not None and n1 and n2 < 0.2 * n1
                    p.record("cache", "PASS" if ok else "FAIL", f"turn 2 processed {n2} of ~{n1} tokens (no cache_n field)")
                else:
                    ok = n1 and c2 >= 0.8 * n1
                    p.record("cache", "PASS" if ok else "FAIL",
                             f"turn 2 reused {c2} cached tokens, processed {n2} new (prompt ~{n1}); "
                             f"wall {d1:.1f}s -> {d2:.1f}s"
                             + ("" if ok else " -> prefix not reused: -np>1? hybrid model checkpoints? cache-prompt off?"))

    # generation speed
    if "generation" not in args.skip:
        code, js, raw, dt = p.chat(model, [{"role": "user", "content":
                                            "Write the numbers from 1 to 200 separated by spaces."}],
                                   max_tokens=128)
        if code == 200 and js:
            tm = js.get("timings") or {}
            n = tm.get("predicted_n") or (js.get("usage") or {}).get("completion_tokens")
            tps = tm.get("predicted_per_second") or (n / dt if n and dt else None)
            p.record("generation", "INFO", f"{n} tokens at {tps:.1f} tok/s" if tps else f"no timing ({dt:.1f}s)")
        else:
            p.record("generation", "FAIL", f"HTTP {code} {raw[:200]!r}")

    # Anthropic Messages (Claude Code)
    if "anthropic" not in args.skip:
        code, js, raw, dt = p.req("POST", "/v1/messages", {
            "model": model, "max_tokens": 16,
            "messages": [{"role": "user", "content": "Say OK."}]},
            headers={"x-api-key": args.api_key, "anthropic-version": "2023-06-01"})
        ok = code == 200 and isinstance(js, dict) and isinstance(js.get("content"), list)
        p.record("anthropic", "PASS" if ok else "WARN",
                 f"/v1/messages HTTP {code}" + ("" if ok else f" {raw[:150]!r} (only needed for Claude Code)"))
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:9931", help="server origin, no /v1 (default %(default)s)")
    ap.add_argument("--model", help="model id (default: first id from /v1/models)")
    ap.add_argument("--api-key", default="local")
    ap.add_argument("--timeout", type=float, default=600, help="seconds per request (cold prefill can be slow)")
    ap.add_argument("--prefix-words", type=int, default=1500, help="length of the shared prefix for the cache test")
    ap.add_argument("--max-tokens", type=int, default=512, help="cap for the tool-call reply (thinking models need more)")
    ap.add_argument("--skip", nargs="*", default=[], choices=["tool_call", "cache", "generation", "anthropic"])
    args = ap.parse_args()
    p = run(args)
    fails = [r for r in p.results if r[1] == "FAIL"]
    print(f"\n{len(fails)} FAIL, {sum(r[1] == 'WARN' for r in p.results)} WARN")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
