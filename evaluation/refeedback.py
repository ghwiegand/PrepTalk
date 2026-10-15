"""Same interviews, new feedback: regenerate only the feedback of recorded interviews with the current code, so
that two feedback versions can be judged on identical conversations (no simulator noise).

    python -m evaluation.refeedback runs/vllm12 runs/refb_new      -> one file per interview, feedback replaced
"""
import json
import sys
from pathlib import Path

from preptalk.coach import session
from framex import dialogue


def regenerate(path, out_dir):
    run = json.loads(Path(path).read_text())
    if run.get("situation") == "phone_call_trial":
        return path.name, "skipped (phone)"
    st = run["state"]
    s = session.Session(run["context"], dict(st))
    s.channel = s.Channel(s)
    s.channel.transcript = [t for t in st["transcript"]][:-1]  # without the feedback turn
    dialogue.CHANNEL = s.channel
    text = s._structured_feedback()
    if not text:
        return path.name, "no structured feedback"
    old = run["log"][-1]["text"]
    head = old.split("\n\n**", 1)[0]  # the closing words before the feedback
    run["log"][-1]["text"] = f"{head}\n\n{text}"
    (out_dir / path.name).write_text(json.dumps(run, ensure_ascii=False, indent=1))
    return path.name, "ok"


if __name__ == "__main__":
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("S-*.json")):  # sequential: the dialogue module keeps per-run globals
        print(*regenerate(f, out), flush=True)
