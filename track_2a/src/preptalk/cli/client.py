"""Talk to the running coach (Aegra on port 2026) in the terminal. Standard library only.

    PYTHONPATH=src python3 -m preptalk.cli [--url http://localhost:2026] [--posting P-01 | --scenario S-04] [--lang fr]
                               [--trace trace.html]   (decision trace of the interview, written when it ends)
"""
import argparse
import json
import urllib.request

from preptalk.coach.greetings import ASK_JOB
from .terminal import TerminalUI


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:2026")
    ap.add_argument("--posting")
    ap.add_argument("--scenario")
    ap.add_argument("--lang", choices=ASK_JOB)
    ap.add_argument("--name")
    ap.add_argument("--trace", help="write the decision trace as HTML to this file when the interview ends")
    args = ap.parse_args()
    lang = args.lang or "de"
    ui = TerminalUI(lang)
    ui.welcome(ASK_JOB[lang])
    text = ui.ask()
    if not text.strip():
        ui.goodbye()
        return

    # Connect only after the first answer. Include the local greeting in the conversation so the
    # backend knows setup has already been asked and does not repeat it.
    thread = None
    extra = {k: v for k, v in (("posting_id", args.posting), ("scenario_id", args.scenario),
                                ("lang", args.lang), ("name", args.name)) if v}
    turn = {"messages": [{"role": "assistant", "content": ASK_JOB[lang]},
                         {"role": "user", "content": text}], "setup_asked": True, **extra}
    while True:
        with ui.waiting():
            if thread is None:
                thread = post(f"{args.url}/threads", {})["thread_id"]
            state = post(f"{args.url}/threads/{thread}/runs/wait",
                         {"assistant_id": "agent", "input": turn})
        messages = state.get("messages", []) if isinstance(state, dict) else []
        ui.lang = (state.get("context") or {}).get("lang") or args.lang or "de"
        if messages:
            ui.message(messages[-1].get("content", ""))
        coach = (state or {}).get("coach") or {}
        ui.progress(coach.get("progress"))
        if coach.get("done"):
            if args.trace:
                import os
                from preptalk.coach import trace
                ctx = state.get("context") or {}
                run = {"scenario": args.scenario or args.posting or "", "context": ctx, "lang": ctx.get("lang", ""),
                       "state": coach}
                with open(args.trace, "w", encoding="utf-8") as f:
                    f.write(trace.render(run))
                ui.trace(os.path.abspath(args.trace))
            break
        text = ui.ask()
        if not text.strip():
            ui.goodbye()
            break
        turn = {"messages": [{"role": "user", "content": text}]}


if __name__ == "__main__":
    main()
