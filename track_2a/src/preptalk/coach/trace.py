"""Decision trace of one interview, from FrameX's receipts: per answer, what the model judged, which rule
overrode it, and what the coach did next. For teachers and for checking the coach.

    python -m preptalk.coach.trace runs/S-04.json > trace.html
"""
import html
import json
import sys


def rows(state):
    """One row per candidate answer: question, answer, verdict (+reason), example check (+reason), next action."""
    out, current = [], None
    for e in state.get("record", []):
        o, tool = e.get("output", {}), e.get("tool")
        if tool in ("_turn", "_repairTurn") and "answer" in o:
            if current:
                out.append(current)
            current = {"question": o.get("question", ""), "answer": o.get("answer", ""), "verdict": "", "check": "",
                       "rule": False, "action": ""}
        elif tool in ("_judge", "_repairJudge") and current and "verdict" in o:
            current["verdict"] = f'{o.get("label") or o.get("verdict")}: {o.get("reason", "")}'
            if "check" in o:
                reason = o.get("checkReason", "")
                current["check"] = f'{o["check"]}: {reason}'
                current["rule"] = reason.startswith("rule:")
        elif tool == "_company_answer" and current:
            current["action"] = "answered as the company"
        elif tool == "_feedback" and current:
            current["action"] = "feedback"
    if current:
        out.append(current)
    for i, r in enumerate(out[:-1]):
        nxt = out[i + 1]["question"]
        r["action"] = r["action"] or ("asked again" if nxt == r["question"] else f"next: {nxt[:70]}")
    for g in state.get("guard", []):
        out.append({"question": "(guard rule)", "answer": g.get("message", ""), "verdict": g.get("kind", ""),
                    "check": "", "rule": True, "action": {"distress": "support and refer", "manipulation": "stay in role, repeat the question",
                                                        "feedback": "feedback now", "stop": "stop"}.get(
                        g.get("kind"), "interview goes on (support given once)")})
    return out


def render(run):
    head = (f'<h1>Decision trace · {html.escape(run.get("scenario", ""))} · {html.escape(run.get("context", {}).get("occupation", ""))}'
            f' ({html.escape(run.get("lang", ""))})</h1>')
    body = "".join(
        f'<tr class="{"rule" if r["rule"] else ""}"><td>{html.escape(r["question"])}</td><td>{html.escape(r["answer"])}</td>'
        f'<td>{html.escape(r["verdict"])}</td><td>{html.escape(r["check"])}</td><td>{html.escape(r["action"])}</td></tr>'
        for r in rows(run["state"]))
    return f"""<!doctype html><meta charset="utf-8"><title>Decision trace</title>
<style>body{{font:14px/1.4 -apple-system,Helvetica,sans-serif;margin:24px;color:#111}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:6px;vertical-align:top}}th{{background:#f4f4f4;text-align:left}}
tr.rule td{{background:#fff4e5}}</style>{head}
<p>Model verdicts and the rules that checked them. Orange rows: a deterministic rule decided (concrete-example rule or guard).</p>
<table><tr><th>Question</th><th>Answer</th><th>Judge: answered?</th><th>Concrete example?</th><th>What the coach did</th></tr>{body}</table>"""


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as source:
        print(render(json.load(source)))
