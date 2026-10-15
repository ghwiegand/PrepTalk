"""Talk to the running coach (Aegra on port 2026) in the terminal. Standard library only.

    python3 src/chat_client.py [--url http://localhost:2026] [--posting P-01 | --scenario S-04] [--lang fr]
                               [--trace trace.html]   (decision trace of the interview, written when it ends)
"""
import argparse
import json
import urllib.request


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:2026")
    ap.add_argument("--posting")
    ap.add_argument("--scenario")
    ap.add_argument("--lang")
    ap.add_argument("--name")
    ap.add_argument("--trace", help="write the decision trace as HTML to this file when the interview ends")
    args = ap.parse_args()
    thread = post(f"{args.url}/threads", {})["thread_id"]
    extra = {k: v for k, v in (("posting_id", args.posting), ("scenario_id", args.scenario),
                                ("lang", args.lang), ("name", args.name)) if v}
    print("Schreib deine Antworten (leer lassen und Enter zum Beenden).\n")
    text = input("Du: ") if not extra else "Hallo"
    while text.strip():
        state = post(f"{args.url}/threads/{thread}/runs/wait",
                     {"assistant_id": "agent", "input": {"messages": [{"role": "user", "content": text}], **extra}})
        extra = {}
        messages = state.get("messages", []) if isinstance(state, dict) else []
        if messages:
            print("\nCoach:", messages[-1].get("content", ""), "\n")
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
        text = input("Du: ")


if __name__ == "__main__":
    main()
