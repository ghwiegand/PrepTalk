"""Talk to the running coach (Aegra on port 2026) in the terminal. Standard library only.

    python3 src/chat_client.py [--url http://localhost:2026] [--posting P-01 | --scenario S-04] [--lang fr]
                               [--trace trace.html]   (decision trace of the interview, written when it ends)
"""
import argparse
import json
import urllib.request

from coach.greetings import ASK_JOB

INPUT_PROMPTS = {"de": "Du: ", "fr": "Toi: ", "it": "Tu: "}


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:2026")
    ap.add_argument("--posting")
    ap.add_argument("--scenario")
    ap.add_argument("--lang", choices=INPUT_PROMPTS)
    ap.add_argument("--name")
    ap.add_argument("--trace", help="write the decision trace as HTML to this file when the interview ends")
    args = ap.parse_args()
    lang = args.lang or "de"
    print(f"\n{ASK_JOB[lang]}\n")
    text = input(INPUT_PROMPTS[lang])
    if not text.strip():
        return

    # Connect only after the first answer. Include the local greeting in the conversation so the
    # backend knows setup has already been asked and does not repeat it.
    thread = post(f"{args.url}/threads", {})["thread_id"]
    extra = {k: v for k, v in (("posting_id", args.posting), ("scenario_id", args.scenario),
                                ("lang", args.lang), ("name", args.name)) if v}
    turn = {"messages": [{"role": "assistant", "content": ASK_JOB[lang]},
                         {"role": "user", "content": text}], "setup_asked": True, **extra}
    while True:
        state = post(f"{args.url}/threads/{thread}/runs/wait",
                     {"assistant_id": "agent", "input": turn})
        messages = state.get("messages", []) if isinstance(state, dict) else []
        if messages:
            print("\nCoach:", messages[-1].get("content", ""), "\n")
        lang = (state.get("context") or {}).get("lang") or args.lang or "de"
        coach = (state or {}).get("coach") or {}
        if coach.get("done"):
            if args.trace:
                import os
                import sys
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from coach import trace
                ctx = state.get("context") or {}
                run = {"scenario": args.scenario or args.posting or "", "context": ctx, "lang": ctx.get("lang", ""),
                       "state": coach}
                with open(args.trace, "w", encoding="utf-8") as f:
                    f.write(trace.render(run))
                print(f"Decision trace: {os.path.abspath(args.trace)}")
            break
        text = input(INPUT_PROMPTS.get(lang, INPUT_PROMPTS["de"]))
        if not text.strip():
            break
        turn = {"messages": [{"role": "user", "content": text}]}


if __name__ == "__main__":
    main()
