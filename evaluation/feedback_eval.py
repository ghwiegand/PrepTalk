"""Feedback accuracy against FHGR's expert reference feedback (13 full transcripts).

For each transcript the coach writes its feedback from the conversation alone; we compare its level per criterion
with the expert's (exact agreement, within one level, mean absolute error) and count how many of its evidence
quotes occur verbatim in the candidate's words. No simulator and no LLM judge are involved.

    python -m evaluation.feedback_eval            -> runs/feedback_eval.json and a summary
"""
import json
import os
import time
from pathlib import Path

from preptalk.coach import content, feedback, session
from framex import dialogue


def run(transcript):
    posting = content.postings().get(transcript.get("posting_id") or "")
    cand = content.candidates().get(transcript.get("candidate_id") or "")
    lang = transcript["lang"] if transcript["lang"] in content.LANGS else "de"
    sc = content.scenarios().get(transcript.get("scenario_id") or "") or {}
    ctx = content.context_from(posting=posting, candidate=cand, lang=lang, situation=sc.get("situation"))
    s = session.Session(ctx)
    s.channel = s.Channel(s)
    s.channel.transcript = [{"speaker": "bot" if t["speaker"] == "interviewer" else "user", "text": t["text"]}
                            for t in transcript["turns"]]
    dialogue.CHANNEL = s.channel
    started = time.time()
    s._structured_feedback()
    data = feedback.normalize(getattr(s, "last_feedback_data", {}) or {})
    ours = {c["key"]: c for c in data.get("criteria", [])}
    turns = [t["text"] for t in s.channel.transcript if t["speaker"] == "user"]
    pairs = []
    for ref in transcript["reference_feedback"]["criteria"]:
        mine = ours.get(ref["criterion"], {})
        pairs.append({"criterion": ref["criterion"], "expert": ref.get("level"), "ours": mine.get("level") or None,
                      "evidence_verbatim": bool(mine.get("evidence")) and feedback.said(mine.get("evidence"), turns)})
    return {"id": transcript["id"], "lang": transcript["lang"], "seconds": round(time.time() - started), "pairs": pairs,
            "third_person_before": len(getattr(s, "third_person_fields", [])),
            "third_person_after": len(feedback.third_person(data, ctx.get("name")))}


def summary(results):
    pairs = [p for r in results for p in r["pairs"] if p["expert"] and p["ours"]]
    n = len(pairs)
    exact = sum(p["expert"] == p["ours"] for p in pairs)
    near = sum(abs(p["expert"] - p["ours"]) <= 1 for p in pairs)
    mae = sum(abs(p["expert"] - p["ours"]) for p in pairs) / max(n, 1)
    bias = sum(p["ours"] - p["expert"] for p in pairs) / max(n, 1)
    evid = [p["evidence_verbatim"] for r in results for p in r["pairs"] if p["ours"]]
    missing = sum(1 for r in results for p in r["pairs"] if p["expert"] and not p["ours"])
    return {"pairs": n, "exact": round(exact / max(n, 1), 3), "within_one": round(near / max(n, 1), 3),
            "mae": round(mae, 2), "bias_ours_minus_expert": round(bias, 2), "no_level_given": missing,
            "evidence_verbatim": round(sum(evid) / max(len(evid), 1), 3),
            "third_person_fields_before_rewrite": sum(r.get("third_person_before", 0) for r in results),
            "third_person_fields_after": sum(r.get("third_person_after", 0) for r in results)}


if __name__ == "__main__":
    transcripts = [json.loads(line) for line in (content.DATA / "transcripts/transcripts.jsonl").open()
                   if json.loads(line).get("reference_feedback")]
    results = [run(t) for t in transcripts]
    out = {"summary": summary(results), "results": results}
    path = Path(os.environ.get("RUNS_DIR", "runs")) / "feedback_eval.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out["summary"]))
