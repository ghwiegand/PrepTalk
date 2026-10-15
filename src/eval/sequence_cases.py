"""Fixed answer sequences: the same scripted candidate for baseline and pilot (COACH_SEQUENCES=0/1), to isolate
how each version coaches one topic (the strengths question). The candidate answers the coach by the kind of
question it receives: main question, concrete situation, own part, result. Earlier questions get one complete
answer; after the strengths topic the candidate asks for feedback.

    COACH_SEQUENCES=1 python -m eval.sequence_cases out.json
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coach import content, session  # noqa: E402

COMPLETE = {"de": "In der Schnupperlehre habe ich letzten Herbst ein Bauteil im CAD gezeichnet. Ich habe die Masse "
                  "selbst kontrolliert, und am Ende wurde es gefräst; dabei habe ich gelernt, genau zu arbeiten.",
            "fr": "Pendant mon stage l'automne dernier, j'ai dessiné une pièce sur ordinateur. J'ai vérifié moi-même "
                  "les mesures, et à la fin elle a été fabriquée; j'ai appris à travailler avec précision.",
            "it": "Durante lo stage dell'autunno scorso ho disegnato un pezzo al computer. Ho controllato io le misure "
                  "e alla fine è stato prodotto; ho imparato a lavorare con precisione."}
FEEDBACK = {"de": "Gib mir jetzt Feedback", "fr": "Donne-moi maintenant un retour", "it": "Dammi subito il feedback"}
CASES = {
    "floskel": ("de", "Ich bin teamfähig, motiviert und zuverlässig.",
                "Im Handball habe ich letzte Saison das Aufwärmen der Junioren organisiert.",
                "Ich habe die Übungen ausgesucht und den Jüngeren gezeigt, wie es geht.",
                "Es gab weniger Verletzungen, und ich habe gelernt, klar zu erklären."),
    "wortkarg": ("de", "Teamfähig.", "Handball.", "Aufwärmen gemacht.", "Gut."),
    "ohne_beitrag": ("de", "Ich bin teamfähig. Letzten Sommer hat unser Team im Pfadilager ein Floss gebaut.",
                     "Das war im Pfadilager am Thunersee, letzten Sommer.",
                     "Ich habe den Plan gezeichnet und die Seile geknotet.",
                     "Das Floss hat gehalten, und ich habe gelernt, Aufgaben zu verteilen."),
    "vollstaendig": ("de", "Ich bin teamfähig: Letzten Sommer habe ich im Pfadilager mit drei anderen ein Floss gebaut. "
                     "Ich habe den Plan gezeichnet und die Seile geknotet. Am Ende hat es gehalten, und ich habe "
                     "gelernt, Aufgaben zu verteilen.",
                     "Wie gesagt, im Pfadilager mit dem Floss.", "Ich habe den Plan gezeichnet.", "Es hat gehalten."),
    "uebertreibung": ("de", "Ich kann eigentlich alles schon, ich bin die Beste in jedem Team und mache nie Fehler.",
                      "Also, in der Schule beim Projekt habe ich halt alles gemacht.",
                      "Ich habe die Präsentation gemacht und die anderen haben zugeschaut.",
                      "Wir hatten eine 5,5, und ich habe gemerkt, dass ich die anderen mehr einbeziehen sollte."),
    "verstaendnis": ("de", "Was meinen Sie mit Stärken? Also, ich bin pünktlich.",
                     "Ich bin jeden Morgen um sieben beim Training, seit zwei Jahren, auch im Winter.",
                     "Ich stelle mir zwei Wecker und packe am Abend die Tasche.",
                     "Der Trainer hat mich deshalb zum Captain gemacht."),
    "belastung": ("de", "Ich bin halt nicht so gut, mich nimmt eh niemand. Aber ich bin pünktlich.",
                  "Ich habe meiner Grossmutter jeden Samstag beim Einkaufen geholfen.",
                  "Ich habe die Liste geschrieben und die Taschen getragen.",
                  "Sie hat sich gefreut, und ich habe gemerkt, dass ich gerne helfe."),
    "floskel_fr": ("fr", "Je suis motivée, dynamique et polyvalente.",
                   "L'été dernier, dans le camp de jeunesse, j'ai organisé les jeux du soir.",
                   "J'ai préparé le matériel et expliqué les règles aux petits.",
                   "Tout le monde a participé, et j'ai appris à parler devant un groupe."),
    "floskel_it": ("it", "Sono motivato, dinamico e affidabile.",
                   "L'estate scorsa al grotto degli zii ho servito ai tavoli durante una festa.",
                   "Ho preso le ordinazioni e ho aiutato in cucina quando c'era troppo lavoro.",
                   "Gli zii erano contenti e ho imparato a restare calmo sotto pressione."),
}
KIND = [("result", r"herausgekommen|gelernt|daraus|ça a donné|appris|ne è venuto|imparato|risultato|résultat|ergebnis"),
        ("own", r"selbst|toi-même|tu même|eigene[nr]? (anteil|beitrag)|hai fatto tu|fatto tu|ta part|tua parte|was hast du (da|dabei|dort|in)"),
        ("situation", r"situation|beispiel|erlebt|exemple|vécu|esempio|vissuto|raconte|erzähl|racconta")]


def run(case):
    lang, main, situation, own, result = CASES[case]
    posting = next(p for p in content.postings().values() if p.get("lang", lang) == lang) if lang != "de" else content.postings()["P-01"]
    ctx = content.context_from(posting=posting, lang=lang, name="Alex")
    strengths_q = content.questions()["Q-05-01"]["text"][lang]
    state, msg, log, phase, started, calls0 = None, None, [], "before", time.time(), session.CALLS["n"]
    for _ in range(40):
        s = session.Session(ctx, state)
        t = time.time()
        out = " ".join(s.step(msg))
        state = json.loads(json.dumps(s.state))
        log.append({"speaker": "coach", "text": out, "seconds": round(time.time() - t, 1)})
        if state["done"]:
            break
        if phase == "before" and strengths_q in out:
            phase, msg = "topic", main
        elif phase == "topic":
            kind = next((k for k, pat in KIND if re.search(pat, out.split("?")[0][-200:], re.I)), None)
            if kind:
                msg = {"situation": situation, "own": own, "result": result}[kind]
                log[-1]["action"] = kind
            else:
                msg = FEEDBACK[lang]
                phase = "done"
        else:
            msg = COMPLETE[lang]
        log.append({"speaker": "candidate", "text": msg})
    followups = [x["action"] for x in log if x.get("action")]
    return {"case": case, "lang": lang, "followups": followups, "seconds": round(time.time() - started),
            "calls": session.CALLS["n"] - calls0, "answers": state.get("answers"), "feedback": log[-1]["text"],
            "log": log, "topics": state.get("topics")}


if __name__ == "__main__":
    out = [run(c) for c in (sys.argv[2:] or CASES)]
    Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for r in out:
        print(r["case"], "| follow-ups:", r["followups"], "| calls", r["calls"], "/", r["answers"], "answers |", r["seconds"], "s", flush=True)
