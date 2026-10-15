"""Rule-based regression suite: the hard requirements counted directly on interview logs, next to the LLM judge
(which overlooks exactly these errors, see the error analysis). Every check comes from a failure we found.

    python -m eval.regression runs/vllm [runs/eval9 ...]   -> table per run; exit code 1 if a hard limit is broken

Hard limits (must be 0 / met): aborted or hung interviews, reactions copying the prompt's examples, feedback about
the applicant in the third person, coach turns in another language, guard-handled messages quoted as evidence,
feedback criticising fillers / dialect / language level, mean calls per answer < 5. Reported, not enforced:
latency, share of the middle level «good», repeated support texts.
"""
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coach import content, feedback, rules, session  # noqa: E402
from coach import feedback as fbmod  # noqa: E402  (check() has a local variable «feedback»)

SORRY = ("hier ist etwas schiefgelaufen", "quelque chose n'a pas fonctionné", "qualcosa è andato storto")  # the coach's error message, not a question about what went wrong
SUPPORT = ("Danke, dass du das so offen", "Merci de le dire", "Grazie per averlo")
GOOD = {"Gut", "Bien", "Buono"}
LEVELS = {"Ungenügend", "Ausbaufähig", "Gut", "Sehr gut", "Insuffisant", "À développer", "Bien", "Très bien",
          "Insufficiente", "Da sviluppare", "Buono", "Molto buono"}
FORM_CRITIQUE = feedback.FORM_CRITIQUE  # feedback must never judge slips, fillers, dialect or language level


def improvements(feedback):
    """The lines of the improvement section (and the next step), where a critique would be."""
    m = re.search(r"\*\*(Daran kannst du arbeiten|Ce que tu peux encore travailler|Su che cosa puoi ancora lavorare)"
                  r"\*\*(.*)", feedback, re.S)
    return m.group(2) if m else ""


IMPROVE = r"\*\*(Daran kannst du arbeiten|Ce que tu peux encore travailler|Su che cosa puoi ancora lavorare)\*\*(.*?)(\*\*(Dein nächster|Ta prochaine|Il tuo prossimo)|$)"
SAFETY = ("Zum Schluss", "Unterstützung", "Pour finir", "Soutien", "Per finire", "Sostegno")


def company_unsupported(run):
    """Sentences of the company answer with offers or numbers that are not in the company data."""
    facts = json.dumps(content.company_facts(run["context"]), ensure_ascii=False)
    n = 0
    for e in run["state"]["record"]:
        if e["tool"] != "_company_answer":
            continue
        said = " ".join(t["text"] for t in e.get("transcript", []) if t["speaker"] == "bot")
        said = re.split(r"Vielen Dank für das Gespräch|Danke für das Gespräch|Merci (beaucoup )?pour cet|Grazie (mille )?per", said)[0]
        said = re.sub("|".join(re.escape(v) for g in rules.GLOSSARY.values() for v in g.values()), "", said)
        kept = rules.grounded_company_answer(said, facts, run["lang"])
        n += len(re.split(r"(?<=[.!?])\s+", said.strip())) - len(re.split(r"(?<=[.!?])\s+", kept)) if said.strip() else 0
    return max(n, 0)


def check(run):
    log, st, ctx = run["log"], run["state"], run["context"]
    lang, name = run["lang"], ctx.get("name") or ""
    coach = [t for t in log if t["speaker"] == "coach"]
    feedback = coach[-1]["text"] if coach else ""
    reactions = [re.split(r"(?<=[.!])\s", t["text"])[0] for t in coach[1:-1]]
    body = "\n".join(line for line in re.sub(r"«[^»]*»", "", feedback.split("**", 1)[-1]).splitlines()
                     if not line.startswith("|"))  # table evidence is the applicant's own words (quoted or paraphrased)
    third = len(re.findall(rf"\b{re.escape(name)}\b(?!\s*[,!])", body)) if name else 0
    guarded = [g.get("message", "") for g in st.get("guard", [])]
    quotes = re.findall(r"«([^»]{12,})", feedback)
    levels = [c.strip() for c in re.findall(r"^\|[^|]+\|([^|]+)\|", feedback, re.M) if c.strip() in LEVELS]
    secs = [t["seconds"] for t in coach[1:-1] if "seconds" in t]
    s = run["summary"]
    return {
        "aborted": int(s["status"] not in ("completed", "feedback on request") or any(x in t["text"] for t in coach for x in SORRY)),
        "copied_example": sum(session.copies_example(r, lang) for r in reactions),
        "third_person": int(third > 0),
        "other_language": sum(bool(re.search(session.OTHER_LANG[lang], r, re.I)) for r in reactions),
        "guard_quoted": sum(any(q.rstrip(" …")[:40] in g for g in guarded) for q in quotes),
        "form_critique": int(bool(re.search(FORM_CRITIQUE, re.sub(r"«[^»]*»", "", improvements(feedback)), re.I))),
        "support_repeated": int(sum(any(x in t["text"] for x in SUPPORT) for t in coach) > 1),
        # restfehler R1-R9
        "phone_incomplete": int(run.get("situation") == "phone_call_trial" and not (
            "✓" in feedback and re.search(r"Stichwortzettel|aide-mémoire|foglietto", feedback)
            and re.search(r"Gut gemacht|Gut, dass|Bien joué|C'est bien|Ben fatto|È bello", feedback))),
        "inadmissible_level": sum(1 for evidence, level in [(r[2], r[1]) for r in re.findall(r"^\|([^|]+)\|([^|]+)\|([^|]+)\|", feedback, re.M)]
                                  if level.strip() in LEVELS and (re.search(fbmod.INADMISSIBLE, evidence, re.I))),
        "more_than_two_points": int(len([line for line in re.findall(r"^- (.*)$", (re.search(IMPROVE, feedback, re.S) or [None, "", ""])[2], re.M)
                                         if not any(line.startswith(f"**{x}") for x in SAFETY)]) > 2),
        "company_unsupported": company_unsupported(run),
        "comprehension_ignored": sum(1 for i, t in enumerate(log[:-1]) if t["speaker"] == "candidate"
                                     and re.search(session.COMPREHENSION, t["text"], re.I)
                                     and (re.search(r"nicht langsamer|pas plus lentement|non più piano", log[i + 1]["text"], re.I)
                                          or re.search(session.PRAISE, re.split(r"(?<=[.!?])\s", log[i + 1]["text"])[0], re.I))),
        "calls": s["llm_calls"], "answers": s["candidate_answers"],
        "good_share": (sum(lv in GOOD for lv in levels), len(levels)),
        "turn_s": secs, "feedback_s": coach[-1].get("seconds"),
    }


HARD = ["aborted", "copied_example", "third_person", "other_language", "guard_quoted", "form_critique",
        "phone_incomplete", "inadmissible_level", "more_than_two_points", "company_unsupported", "comprehension_ignored"]


def summarize(name, results):
    tot = {k: sum(r[k] for r in results) for k in HARD + ["support_repeated"]}
    calls, answers = sum(r["calls"] for r in results), sum(r["answers"] for r in results)
    good = sum(r["good_share"][0] for r in results), sum(r["good_share"][1] for r in results)
    turns = [x for r in results for x in r["turn_s"]]
    fb = [r["feedback_s"] for r in results if r["feedback_s"]]
    return {"run": name, "interviews": len(results), **tot,
            "calls_per_answer": round(calls / max(answers, 1), 2),
            "max_calls_per_answer": max((round(r["calls"] / max(r["answers"], 1), 2) for r in results), default=0),
            "good_share": round(good[0] / max(good[1], 1), 2),
            "turn_s_median": round(statistics.median(turns), 1) if turns else None,
            "turn_s_max": max(turns) if turns else None,
            "feedback_s_max": max(fb) if fb else None}


if __name__ == "__main__":
    rows, failed = [], False
    for d in sys.argv[1:]:
        files = sorted(Path(d).glob("S-*.json"))
        results = [check(json.loads(f.read_text())) for f in files]
        row = summarize(d, results)
        rows.append(row)
        failed |= any(row[k] for k in HARD) or row["calls_per_answer"] >= 5
        for f, r in zip(files, results):
            bad = [k for k in HARD if r[k]]
            if bad:
                print(f"  {f}: {', '.join(bad)}")
    keys = list(rows[0]) if rows else []
    print("| " + " | ".join(keys) + " |\n|" + "---|" * len(keys))
    for r in rows:
        print("| " + " | ".join(str(r[k]) for k in keys) + " |")
    print("hard limits:", "BROKEN" if failed else "all met")
    sys.exit(1 if failed else 0)
