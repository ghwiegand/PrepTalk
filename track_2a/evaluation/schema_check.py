"""Send every reply schema the coach uses once to the server at LLM_BASE_URL (json_schema, as vLLM receives it)
and report which are accepted and whether the reply fits. Run this first against a new endpoint.

    LLM_BASE_URL=https://.../v1 LLM_API_KEY=... python -m evaluation.schema_check
"""
import json
import os
import time
import urllib.error
import urllib.request

from preptalk.coach import content, feedback, rules
from framex import dialogue

def main():
    keys = [k["key"] for k in content.rubric()["criteria"]]
    SCHEMAS = {
        "utterance": dialogue.UTTERANCE_SCHEMA,
        "judge (answered + check)": dialogue.judge_schema({"collect": True, "checkCriterion": "x"}),
        "judge (yes/no, more)": dialogue.judge_schema({"more": True}),
        "guard": rules.GUARD_SCHEMA,
        "feedback": feedback.schema(keys),
        "rewrite": feedback.rewrite_schema(["overall", "strengths[0]", "improvements[1]"]),
    }
    base = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1").rstrip("/")
    for name, schema in SCHEMAS.items():
        body = {"model": os.environ.get("LLM_NAME", "swiss-ai/Apertus-v1.5-8B"), "max_tokens": 1500, "temperature": 0,
                "messages": [{"role": "system", "content": "Answer as JSON for a short practice interview in German."},
                             {"role": "user", "content": "Ich habe im Werken einen Kran gebaut."}],
                "response_format": {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}}}
        req = urllib.request.Request(base + "/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json",
                                      "Authorization": "Bearer " + os.environ.get("LLM_API_KEY", "none")})
        t = time.time()
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                reply = json.loads(r.read())["choices"][0]["message"]["content"]
            try:
                data = json.loads(reply)
                missing = [k for k in schema.get("required", []) if k not in data]
                print(f"OK   {name:28} {time.time() - t:5.1f}s  missing={missing}  {reply[:90]!r}")
            except ValueError:
                print(f"BAD  {name:28} reply is not JSON: {reply[:120]!r}")
        except urllib.error.HTTPError as e:
            print(f"FAIL {name:28} HTTP {e.code}: {e.read()[:200]!r}")


if __name__ == "__main__":
    main()
