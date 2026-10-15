"""Schema-driven OpenAI-compatible fixture; never contacts an external model."""

import json
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def fill(schema):
    t = schema.get("type")
    if "enum" in schema:
        return schema["enum"][0]
    if t == "object":
        return {k: fill(v) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return [fill(schema.get("items", {}))] * 2
    if t == "integer":
        return 3
    if t == "boolean":
        return False
    return "Du hast das gut erklärt."


class FakeModelHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"data":[{"id":"swiss-ai/Apertus-v1.5-8B"}]}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        rf = body.get("response_format") or {}
        sys_prompt = body["messages"][0]["content"]
        rej = os.environ.get("FAKE_REJECT")
        if rf.get("type") == "json_schema" and rej and rej in json.dumps(rf):
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"schema not supported"}')
            return
        if rf.get("type") == "json_schema":
            text = json.dumps(fill(rf["json_schema"]["schema"]), ensure_ascii=False)
        elif rf.get("type") == "json_object":
            text = '{"utterance": "Gut.", "verdict": "yes", "reason": "ok", "check": "yes", "checkReason": "ok", "label": "none"}'
        elif "Extract from the message" in sys_prompt:
            text = '{"lang": "de", "occupation": "Informatiker", "name": "Lea"}'
        else:
            text = "Danke, gute Frage."
        out = {
            "id": "x",
            "object": "chat.completion",
            "model": body["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_DELETE(self):
        pass


@contextmanager
def fake_model():
    server = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("FAKE_PORT", "0"))), FakeModelHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
