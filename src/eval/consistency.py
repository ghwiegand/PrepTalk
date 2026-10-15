"""Consistency of the judged runs: scenario criteria met by language, situation, difficulty and candidate profile,
for each judge, plus the spread over scenarios and the calls per answer by language.

    python -m eval.consistency runs/g17 runs/g17h   -> table on stdout, runs/consistency.json, docs/consistency.png

Each run directory holds S-*.json (the interviews) and opus/judged.json, gemini/judged.json (eval.judge).
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coach import content  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
# candidates whose coach_focus names a sensitive case from the FHGR material (dyslexia, German as a second language,
# nervousness or shyness, emotional moments, an interrupted school or apprenticeship, gender-atypical choice,
# dialect to be understood, strong self-doubt)
SENSITIVE = ("legasthenie", "deutschniveau", "nervosität", "zurückhaltend", "emotional", "abbruch", "lücke",
             "gender", "dialekt verstehen", "selbstzweifel")
JUDGES = {"opus": "Claude Opus 5.5", "gemini": "Gemini Pro"}
SITUATION = {"apprenticeship_interview": "interview", "online_interview": "online", "phone_call_trial": "phone call",
             "trial_interview": "trial day", "follow_up_interview": "follow-up", "assessment": "assessment"}


def profile(scenario):
    focus = " ".join(content.candidates()[scenario["candidate_id"]].get("coach_focus") or []).lower()
    return "sensitive" if any(w in focus for w in SENSITIVE) else "standard"


def groups(sid):
    sc = content.scenarios()[sid]
    cand = content.candidates()[sc["candidate_id"]]
    return {"language": sc["lang"], "situation": SITUATION.get(sc["situation"], sc["situation"]),
            "difficulty": sc.get("difficulty", "?"), "profile": profile(sc),
            "dialect": "dialect speaker" if cand.get("dialect") else "standard language"}


def main(dirs):
    rows = []  # one per scenario run and judge
    calls = defaultdict(list)
    for d in map(Path, dirs):
        for f in sorted(d.glob("S-*.json")):
            r = json.loads(f.read_text())
            calls[content.scenarios()[f.stem]["lang"]].append(r["summary"]["llm_calls"] / max(r["summary"]["candidate_answers"], 1))
        for judge in JUDGES:
            p = d / judge / "judged.json"
            for x in json.loads(p.read_text()) if p.exists() else []:
                rows.append(dict(groups(x["scenario"]), judge=judge, run=d.name, scenario=x["scenario"],
                                 met=x["checks_met"], total=x["checks_total"]))
    out = {}
    for axis in ("language", "situation", "difficulty", "profile", "dialect"):
        out[axis] = {}
        for value in sorted({r[axis] for r in rows}):
            out[axis][value] = {}
            for judge in JUDGES:
                sel = [r for r in rows if r[axis] == value and r["judge"] == judge]
                met, tot = sum(r["met"] for r in sel), sum(r["total"] for r in sel)
                out[axis][value][judge] = {"pct": round(100 * met / tot) if tot else None, "met": met, "total": tot,
                                           "n": len(sel)}
    for judge in JUDGES:
        per = [100 * r["met"] / r["total"] for r in rows if r["judge"] == judge and r["total"]]
        out.setdefault("spread", {})[judge] = {"mean": round(statistics.mean(per)), "sd": round(statistics.pstdev(per)),
                                               "min": round(min(per)), "max": round(max(per)), "n": len(per)}
    out["calls_per_answer"] = {k: round(statistics.mean(v), 2) for k, v in sorted(calls.items())}
    (ROOT / "runs" / "consistency.json").write_text(json.dumps(out, indent=1))
    for axis in ("language", "situation", "difficulty", "profile", "dialect"):
        print(f"\n{axis}: " + "; ".join(f"{v} " + " / ".join(f"{out[axis][v][j]['pct']} %" for j in JUDGES)
                                        + f" (n={out[axis][v]['opus']['n']})" for v in out[axis]))
    print("\nspread over scenario runs:", out["spread"], "\ncalls per answer by language:", out["calls_per_answer"])
    figure(out)
    latex(out)


def latex(out):
    """docs/report/consistency.tex (table rows) and consistency_numbers.tex (macros) for the LaTeX report."""
    names = {"language": {"de": "German", "fr": "French", "it": "Italian"}}
    blocks = []
    for axis in ("language", "profile", "dialect", "difficulty", "situation"):
        rows = [f"{axis.capitalize() if i == 0 else ''} & {names.get(axis, {}).get(v, v)} ({d['opus']['n']}) & "
                f"{d['opus']['pct']}\\,\\% & {d['gemini']['pct']}\\,\\% \\\\" for i, (v, d) in enumerate(out[axis].items())]
        blocks.append("\n".join(rows))
    (ROOT / "docs" / "report" / "consistency.tex").write_text("\n\\addlinespace[2pt]\n".join(blocks) + "\n")
    sp = out["spread"]
    (ROOT / "docs" / "report" / "consistency_numbers.tex").write_text(
        f"\\newcommand{{\\spread}}{{Per scenario run, Opus ranges from {sp['opus']['min']} to {sp['opus']['max']}\\,\\% "
        f"(mean {sp['opus']['mean']}, SD {sp['opus']['sd']}), Gemini Pro from {sp['gemini']['min']} to "
        f"{sp['gemini']['max']}\\,\\% (mean {sp['gemini']['mean']}, SD {sp['gemini']['sd']}).}}\n"
        "\\newcommand{\\callslang}{" + ", ".join(f"{k} {v}" for k, v in out["calls_per_answer"].items()) + "}\n")


def figure(out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    axes = [("language", ["de", "fr", "it"], ["German", "French", "Italian"]),
            ("profile", ["standard", "sensitive"], ["standard", "sensitive"]),
            ("situation", [k for k in ("interview", "online", "trial day", "follow-up", "assessment", "phone call")
                           if k in out["situation"]], None)]
    fig, axs = plt.subplots(1, 3, figsize=(11, 2.9), gridspec_kw={"width_ratios": [3, 2, 6]}, sharey=True)
    colors = {"opus": "#1f3b63", "gemini": "#c0602a"}
    for ax, (axis, keys, labels) in zip(axs, axes):
        for i, judge in enumerate(JUDGES):
            vals = [out[axis][k][judge]["pct"] or 0 for k in keys]
            xs = [x + (i - 0.5) * 0.38 for x in range(len(keys))]
            bars = ax.bar(xs, vals, 0.38, color=colors[judge], label=JUDGES[judge])
            for b, v in zip(bars, vals):
                ax.text(b.get_x() + b.get_width() / 2, v + 1.5, str(v), ha="center", fontsize=7)
        ax.set_xticks(range(len(keys)))
        ax.set_xticklabels([f"{label}\n(n={out[axis][k]['opus']['n']})" for k, label in zip(keys, labels or keys)], fontsize=7.5)
        ax.set_title(f"by {axis}", fontsize=9)
        ax.set_ylim(0, 100)
        ax.spines[["top", "right"]].set_visible(False)
    axs[0].set_ylabel("scenario criteria met (%)", fontsize=8)
    handles, labels = axs[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=7.5, frameon=False, loc="upper center", ncol=2)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(ROOT / "docs" / "consistency.png", dpi=200)


if __name__ == "__main__":
    main(sys.argv[1:])
