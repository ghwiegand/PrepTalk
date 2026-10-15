"""Measure the deterministic rules on data they were not tuned on.

R1 (concrete example) against the FHGR expert annotations (criteria_scores.concrete_examples <= 2 = vague), and
R5 (guard) on data/guard_cases.json, new phrasings written for this test (not taken from the datasets):
stage 1 = patterns only, stage 1+2 = patterns, then the model (LLM_BASE_URL) for everything else.

    python -m evaluation.rules_eval            # R1 and R5 stage 1 (no model)
    python -m evaluation.rules_eval --model    # also R5 stage 1+2 (one model call per case)
"""
import collections
import json
import sys
from pathlib import Path

from preptalk.coach import content, rules


def r1():
    answers = {a["id"]: a for a in map(json.loads, (content.DATA / "answers/answers.jsonl").open())}
    notes = [json.loads(line) for line in (content.DATA / "annotations/annotations.jsonl").open()]
    print("R1 concrete-example rule vs FHGR experts (vague = concrete_examples <= 2)")
    for lang in ("de", "fr", "it", "gsw"):
        tp = fp = fn = tn = 0
        for n in notes:
            a, score = answers[n["answer_id"]], (n.get("criteria_scores") or {}).get("concrete_examples")
            if a["lang"] != lang or score is None:
                continue
            gold, pred = score <= 2, not rules.concrete(a["text"], "de" if lang == "gsw" else lang)[0]
            tp += gold and pred
            fp += (not gold) and pred
            fn += gold and not pred
            tn += (not gold) and not pred
        print(f"  {lang}: n={tp + fp + fn + tn}  precision={tp / max(tp + fp, 1):.2f}  recall={tp / max(tp + fn, 1):.2f}")


def r5(with_model):
    cases = json.loads((Path(__file__).parent / "data" / "guard_cases.json").read_text(encoding="utf-8"))
    stage1, both = collections.Counter(), collections.Counter()
    session = None
    if with_model:
        from preptalk.coach import session  # noqa: F811 - configures the model endpoint
    for gold, _lang, text in cases:
        p1 = rules.guard(text) or "none"
        stage1[(gold, p1)] += 1
        if session:
            s = session.Session(content.context_from(lang="de"))
            both[(gold, s._guard(text) or "none")] += 1
    for name, counts in (("stage 1 (patterns)", stage1), ("stage 1+2 (patterns + model)", both)):
        if counts:
            line = ", ".join(f"{g}: {counts[(g, g)]}/{sum(v for (gg, _), v in counts.items() if gg == g)}"
                             for g in ("distress", "manipulation", "none"))
            line += (f"; mild self-doubt (should not interrupt): {counts[('self_doubt', 'none')]}/"
                     f"{sum(v for (gg, _), v in counts.items() if gg == 'self_doubt')} not interrupted")
            print(f"R5 guard, {name}: {line}")


if __name__ == "__main__":
    r1()
    r5("--model" in sys.argv)
