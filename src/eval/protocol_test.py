"""Protocol robustness without Apertus: a fake OpenAI-compatible server answers every request by its JSON schema
(fast, deterministic), and the LangGraph graph is driven the ways an unknown benchmark harness might drive it:
with thread state or stateless (the whole conversation resent), setup in a system message, by ids or not at
all, an empty or English first message, two messages at once, an early feedback request, messages after the end.
FAKE_REJECT=minimum makes the server refuse json_schema requests containing that word (one schema rejected).

    python -m eval.protocol_test          -> one line per coach reply; no case may crash
"""

import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("FAKE_PORT", "8097"))
os.environ["LLM_BASE_URL"] = f"http://127.0.0.1:{PORT}/v1"
os.environ.setdefault("FRAMEX_MODEL_CACHE", f"/tmp/protocol-test-{os.getpid()}")


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


class H(BaseHTTPRequestHandler):
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


threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever, daemon=True).start()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
import main  # noqa: E402

g = main.graph
ANS = "Ich habe im Werken einen Kran gebaut und das Getriebe selbst berechnet."


def show(tag, out):
    msg = out["messages"][-1].content
    print(f"  [{tag}] {msg[:110]!r}")


def stateful(first, extra=None, n=4, answers=None):
    state = dict(messages=first, **(extra or {}))
    out = g.invoke(state)
    show(0, out)
    for i in range(n):
        out = g.invoke({**out, "messages": [HumanMessage((answers or [ANS])[min(i, len(answers or [ANS]) - 1)])]})
        show(i + 1, out)
    return out


def stateless(first, n=4):
    hist = list(first)
    for i in range(n + 1):
        out = g.invoke({"messages": hist})
        show(i, out)
        hist = list(out["messages"]) + [HumanMessage(ANS)]
    return out


cases = {
    "1 stateful, scenario id": lambda: stateful([HumanMessage("Hallo")], {"scenario_id": "S-04"}),
    "2 stateless, scenario in system msg": lambda: stateless([SystemMessage("Szenario S-01"), HumanMessage("Hallo")]),
    "3 English, no setup": lambda: stateful([HumanMessage("Hi, I want to practice an interview.")], n=2),
    "4 empty first message": lambda: stateful([HumanMessage("")], n=2),
    "5 feedback request first answer": lambda: stateful(
        [HumanMessage("Hallo")], {"scenario_id": "S-01"}, n=1, answers=["Gib mir jetzt Feedback"]
    ),
    "6 after done": lambda: stateful(
        [HumanMessage("Hallo")], {"scenario_id": "S-05"}, n=3, answers=["Dammi subito il feedback", "Ciao?", "Ancora?"]
    ),
    "7 two human msgs, fr system": lambda: stateful(
        [SystemMessage("Scénario S-04, candidat C-04"), HumanMessage("Bonjour"), HumanMessage("Je suis prêt")], n=1
    ),
    "8 unknown ids": lambda: stateful(
        [HumanMessage("Szenario S-99 P-77, ich möchte Koch werden, ich heisse Tim")], n=1
    ),
}
failed = False
for name, fn in cases.items():
    print(name)
    try:
        fn()
    except Exception:
        failed = True
        print("  CRASH", traceback.format_exc()[-600:])
sys.exit(1 if failed else 0)
