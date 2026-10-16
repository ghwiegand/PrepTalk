"""Talk to the running coach (Aegra on port 2026) in the terminal. Standard library only.

    PYTHONPATH=src python3 -m preptalk.cli [--url http://localhost:2026] [--posting P-01 | --scenario S-04] [--lang fr]
                               [--trace trace.html]   (decision trace of the interview, written when it ends)
"""
import argparse
import json
import subprocess
import urllib.request

from preptalk.coach.greetings import ASK_JOB
from .menu import main_menu
from .terminal import TerminalUI


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:2026")
    presets = ap.add_mutually_exclusive_group()
    presets.add_argument("--posting")
    presets.add_argument("--scenario")
    ap.add_argument("--lang", choices=ASK_JOB)
    ap.add_argument("--name")
    ap.add_argument("--mode", choices=("chat", "voice"), default="chat", help="voice is experimental and runs on macOS")
    ap.add_argument("--no-menu", action="store_true", help="start the chat directly, using command-line options")
    ap.add_argument("--trace", help="write the decision trace as HTML to this file when the interview ends")
    args = ap.parse_args()
    lang = args.lang or "de"
    ui = TerminalUI(lang)
    with ui.screen(enabled=not args.no_menu):
        run_chat(args, ui)


def run_chat(args, ui):
    speech = None
    while True:
        if not args.no_menu:
            selection = main_menu(ui, args.scenario, args.posting, args.mode)
            if selection is None:
                ui.goodbye()
                return
            args.scenario, args.posting, args.lang, args.mode = selection
        if args.mode == "voice":
            from .voice import VoiceError, VoiceIO
            try:
                speech = VoiceIO(ui)
            except (VoiceError, OSError, subprocess.SubprocessError) as exc:
                ui.body(ui.text["voice_unavailable"].format(error=str(exc)))
                if args.no_menu:
                    return
                args.mode = "chat"
                if ui.prompt(ui.text["voice_return"]) is None:
                    return
                continue
        break
    if not speech:
        ui.close_screen()  # Text chat keeps its ordinary terminal scrollback.
    greeting = ui.text["preset_greeting"] if args.scenario or args.posting else ASK_JOB[ui.lang]
    ui.welcome(greeting, voice=bool(speech))
    if speech and not speech.speak(greeting):
        ui.goodbye()
        return
    text = speech.ask() if speech else ui.ask()
    if not text.strip():
        ui.goodbye()
        return

    # Connect only after the first answer. Include the local greeting in the conversation so the
    # backend knows setup has already been asked and does not repeat it.
    thread = None
    extra = {k: v for k, v in (("posting_id", args.posting), ("scenario_id", args.scenario),
                                ("lang", args.lang), ("name", args.name)) if v}
    if speech:
        extra.update(voice=True, lang=ui.lang)
    turn = {"messages": [{"role": "assistant", "content": greeting},
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
        if speech and messages and not speech.speak(messages[-1].get("content", "")):
            ui.goodbye()
            break
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
        text = speech.ask() if speech else ui.ask()
        if not text.strip():
            ui.goodbye()
            break
        turn = {"messages": [{"role": "user", "content": text}]}


if __name__ == "__main__":
    main()
