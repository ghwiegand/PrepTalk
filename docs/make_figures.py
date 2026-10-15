"""Figure for the report: scenario criteria per round and what the guard rules add. Numbers from runs/*/judge.md
and runs/*/rules_eval.md (see docs/report/report.tex).

    python docs/make_figures.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# scenario criteria met (%), by judge: Gemini Pro and Claude Opus 5.5 (strict); final bars with Gemini Flash as applicant
STAGES = [
    ("before rules\n(round 3, 12)", 55, 48),
    ("all rules\n(round 9, 14)", 69, 65),
    ("final on vLLM\ndevelopment (14)", 80, 72),
    ("final on vLLM\nheld-out (14)", 67, 56),
]
GUARD = {"distress": (0, 10, 10), "manipulation": (2, 8, 8), "harmless": (22, 22, 22)}  # patterns, +model, n

plt.rcParams.update({"font.family": "Arial", "font.size": 9})
fig, (a, b) = plt.subplots(1, 2, figsize=(7.2, 2.5), gridspec_kw={"width_ratios": [1.7, 1]})

xs = range(len(STAGES))
a.bar([i - 0.2 for i in xs], [q for _, q, _ in STAGES], 0.4, color="#9db4d3", label="Gemini Pro")
a.bar([i + 0.2 for i in xs], [o for _, _, o in STAGES], 0.4, color="#2b5d9b", label="Claude Opus 5.5 (strict)")
for i, (_, q, o) in enumerate(STAGES):
    a.text(i - 0.2, q + 1.5, f"{q}", ha="center", fontsize=7.5)
    a.text(i + 0.2, o + 1.5, f"{o}", ha="center", fontsize=7.5)
a.set_xticks(list(xs), [lab for lab, _, _ in STAGES], fontsize=6.8)
a.set_ylim(0, 118)
a.set_yticks(range(0, 101, 20))
a.set_ylabel("scenario criteria met (%)")
a.set_title("Scenario criteria by judge", fontsize=9)
a.legend(fontsize=7, loc="upper left", frameon=False, ncol=2)

x = range(len(GUARD))
p = [100 * v[0] / v[2] for v in GUARD.values()]
q = [100 * v[1] / v[2] for v in GUARD.values()]
b.bar([i - 0.2 for i in x], p, 0.4, color="#d9a066", label="patterns only")
b.bar([i + 0.2 for i in x], q, 0.4, color="#2b5d9b", label="patterns + Apertus")
b.set_xticks(list(x), [f"{k}\n(n={v[2]})" for k, v in GUARD.items()], fontsize=7.5)
b.set_ylim(0, 128)
b.set_yticks(range(0, 101, 20))
b.set_ylabel("handled correctly (%)")
b.set_title("Guard rule R5 on unseen sentences", fontsize=9)
b.legend(fontsize=7, loc="upper left", frameon=False, ncol=2)
for ax in (a, b):
    ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(Path(__file__).with_name("results.png"), dpi=200)
