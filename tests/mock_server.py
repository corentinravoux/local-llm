"""Mock llama-server for testing llm_probe.py. MODE=good|leak|nocache."""
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

MODE = sys.argv[2] if len(sys.argv) > 2 else "good"
state = {"last_prefix": None}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/health":
            return self.send(200, {"status": "ok"})
        if self.path == "/props":
            return self.send(200, {"default_generation_settings": {"n_ctx": 32768},
                                   "chat_template": "{{ x }}", "model_path": "/m/test.gguf"})
        if self.path == "/v1/models":
            return self.send(200, {"data": [{"id": "local"}]})
        self.send(404, {"error": "nf"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/v1/messages":
            if MODE == "nocache":
                return self.send(404, {"error": "not found"})
            return self.send(200, {"content": [{"type": "text", "text": "OK"}]})
        msgs = body["messages"]
        if body.get("tools"):
            if MODE == "leak":
                msg = {"role": "assistant", "content": '<tool_call>{"name": "get_weather", "arguments": {"city": "Paris"}}</tool_call>'}
            else:
                msg = {"role": "assistant", "content": None, "tool_calls": [
                    {"type": "function", "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'}}]}
            return self.send(200, {"choices": [{"message": msg}]})
        prefix = msgs[0]["content"] if msgs[0]["role"] == "system" else None
        n = 2000 if prefix else 20
        if prefix and prefix == state["last_prefix"] and MODE != "nocache":
            t = {"cache_n": 1990, "prompt_n": 10, "prompt_per_second": 900.0}
        else:
            t = {"cache_n": 0, "prompt_n": n, "prompt_per_second": 850.0}
        state["last_prefix"] = prefix
        t.update({"predicted_n": 128, "predicted_per_second": 31.5})
        self.send(200, {"choices": [{"message": {"role": "assistant", "content": "one"}}], "timings": t})


HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
