"""Baseline vs pilot on the same scenarios: judge scores plus direct checks of the relevant dialogue places.

    python -m evaluation.ab_compare runs/ab/base_var runs/ab/pilot_var [more pairs ...]  -> table and runs/ab/compare.json

Per version: Opus scenario criteria and aspects; hard limits of the regression suite; calls per answer, latency;
follow-ups per interview and, judged one by one by Claude Opus 5.5, whether each follow-up was necessary and
picked up what was said; per feedback whether the strength is an account of what the applicant did (not a claim
or an attributed ability), whether the point to work on is concrete and evidenced, and whether anything in the
feedback is not supported by the conversation.
"""
import json
import os
import re
import statistics
import sys
import urllib.request
from pathlib import Path

from preptalk.coach import content, evidence

FOLLOW = {t for lang in ("de", "fr", "it") for k in ("example", "own", "company", "step") for t in [content.TEXT[lang][k]]}
FOLLOW |= {t for lang in evidence.ACTION_TEXT for t in evidence.ACTION_TEXT[lang].values()}
ASPECTS = ["realism", "adaptivity", "feedback_quality", "age_appropriateness", "language_consistency"]


def opus(prompt):
    body = {"model": "claude-opus-5-5", "max_tokens": 8000, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", json.dumps(body).encode(),
                                 {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "content-type": "application/json",
                                  "anthropic-version": "2023-06-01"})
    out = json.load(urllib.request.urlopen(req, timeout=900))
    text = "".join(b.get("text", "") for b in out["content"] if b.get("type") == "text")
    return json.loads(re.search(r"\{.*\}", text, re.S).group(0))


def followups(run):
    """(previous answer, follow-up as said, answer to it) for every follow-up of the interview."""
    out, rec = [], run["state"]["record"]
    turns = [e["output"] for e in rec if e["tool"] in ("_turn", "_repairTurn") and "answer" in e.get("output", {})]
    for i, o in enumerate(turns):
        if o["question"] in FOLLOW and i > 0:
            out.append({"before": turns[i - 1]["answer"], "asked": o.get("utterance", o["question"]), "after": o["answer"]})
    return out


def judge_followups(items):
    if not items:
        return []
    prompt = ("An AI coach interviews 14-16 year olds for an apprenticeship. For each follow-up question below, given "
              "the applicant's previous answer, decide: necessary (true if the answer lacked something important, e.g. "
              "a concrete example, the applicant's own part or the result, and the follow-up asks for it), and "
              "picks_up (true if the follow-up refers to what the applicant actually said). Return JSON "
              '{"labels": [{"i": 0, "necessary": true|false, "picks_up": true|false}, ...]}.\n\n'
              + "\n".join(f"[{i}] Previous answer: {x['before']}\nFollow-up: {x['asked']}" for i, x in enumerate(items)))
    return opus(prompt)["labels"]


def judge_feedback(runs):
    items = []
    for r in runs:
        transcript = "\n".join(("COACH: " if t["speaker"] == "coach" else "APPLICANT: ") + t["text"] for t in r["log"][:-1])
        items.append(f"[{len(items)}] TRANSCRIPT:\n{transcript[-6000:]}\nFEEDBACK:\n{r['log'][-1]['text'][-4000:]}")
    prompt = ("Below are practice interviews of an AI coach with 14-16 year olds and the feedback it gave at the end. "
              "For each feedback decide: strength = 'account' if the named strength rests on something the applicant "
              "described doing, 'claim' if it repeats a self-description or attributes an ability (e.g. 'you are a team "
              "player'), 'none' if no strength is named; point_concrete (true if the main point to work on is concrete "
              "and tied to something said); unsupported (number of statements in the feedback about the applicant that "
              "the conversation does not support). Return JSON {\"labels\": [{\"i\": 0, \"strength\": \"account|claim|none\", "
              "\"point_concrete\": true|false, \"unsupported\": 0}, ...]}.\n\n" + "\n\n".join(items))
    return opus(prompt)["labels"]


def summarize(d):
    d = Path(d)
    runs = [json.loads(f.read_text()) for f in sorted(d.glob("S-*.json"))]
    judged = json.loads((d / "opus" / "judged.json").read_text()) if (d / "opus" / "judged.json").exists() else []
    met, tot = sum(x["checks_met"] for x in judged), sum(x["checks_total"] for x in judged)
    reg = (d / "regression.md").read_text() if (d / "regression.md").exists() else ""
    calls = sum(r["summary"]["llm_calls"] for r in runs) / max(sum(r["summary"]["candidate_answers"] for r in runs), 1)
    turns = [t["seconds"] for r in runs for t in r["log"][1:-1] if t["speaker"] == "coach" and "seconds" in t]
    fu = [x for r in runs for x in followups(r)]
    fl = judge_followups(fu)
    fb = judge_feedback([r for r in runs if r.get("situation") != "phone_call_trial"])
    return {
        "run": d.name, "interviews": len(runs), "completed": sum(r["summary"]["status"] == "completed" for r in runs),
        "opus_criteria": f"{met}/{tot} = {round(100 * met / max(tot, 1))} %",
        **{a: round(statistics.mean([x.get(a) or 0 for x in judged]), 2) if judged else None for a in ASPECTS},
        "hard_limits": "all met" if "all met" in reg else "BROKEN: " + "; ".join(line.strip() for line in reg.splitlines() if line.startswith("  ")),
        "calls_per_answer": round(calls, 2), "turn_s_median": statistics.median(turns) if turns else None,
        "turn_s_max": max(turns) if turns else None,
        "followups_per_interview": round(len(fu) / max(len(runs), 1), 1),
        "followups_necessary": f"{sum(x['necessary'] for x in fl)}/{len(fl)}",
        "followups_pick_up": f"{sum(x['picks_up'] for x in fl)}/{len(fl)}",
        "strength_account/claim/none": "/".join(str(sum(x["strength"] == k for x in fb)) for k in ("account", "claim", "none")),
        "point_concrete": f"{sum(x['point_concrete'] for x in fb)}/{len(fb)}",
        "unsupported_statements": sum(int(x.get("unsupported") or 0) for x in fb),
        "followup_examples": [dict(x, **{k: fl[i][k] for k in ("necessary", "picks_up")}) for i, x in enumerate(fu[:len(fl)])],
    }


if __name__ == "__main__":
    rows = [summarize(d) for d in sys.argv[1:]]
    out = Path(sys.argv[1]).parent / "compare.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    keys = [k for k in rows[0] if k != "followup_examples"]
    print("| " + " | ".join(keys) + " |\n|" + "---|" * len(keys))
    for r in rows:
        print("| " + " | ".join(str(r[k]) for k in keys) + " |")
