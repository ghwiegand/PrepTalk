"""Small, dependency-free terminal presentation for the chat client."""

import os
import shutil
import sys
import textwrap
import threading
from contextlib import contextmanager

TEXT = {
    "de": {
        "language": "Deutsch",
        "tagline": "Bereite dich auf dein nächstes Bewerbungsgespräch vor!",
        "you": "Du",
        "exit": "Leere Eingabe + Enter beendet den Chat.",
        "waiting": "Der Coach bereitet die Antwort vor",
        "goodbye": "Bis zum nächsten Mal. Viel Erfolg!",
        "trace": "Entscheidungsspur",
        "question": "Hauptfrage {current} von {total}",
        "completed_count": "{completed}/{total} Hauptfragen abgeschlossen",
        "follow_up": "Nachfrage zur aktuellen Hauptfrage",
        "questions": "Deine Fragen an den Betrieb",
        "completed": "Gespräch abgeschlossen",
        "early_feedback": "Vorzeitiges Feedback",
        "ended": "Gespräch beendet",
    },
    "fr": {
        "language": "Français",
        "tagline": "Prépare ton prochain entretien d'embauche !",
        "you": "Toi",
        "exit": "Une réponse vide + Entrée ferme le chat.",
        "waiting": "Le coach prépare sa réponse",
        "goodbye": "À bientôt et bonne chance !",
        "trace": "Trace des décisions",
        "question": "Question principale {current} sur {total}",
        "completed_count": "{completed}/{total} questions principales terminées",
        "follow_up": "Question complémentaire à la question actuelle",
        "questions": "Tes questions à l'entreprise",
        "completed": "Entretien terminé",
        "early_feedback": "Retour anticipé",
        "ended": "Entretien arrêté",
    },
    "it": {
        "language": "Italiano",
        "tagline": "Preparati per il tuo prossimo colloquio di lavoro!",
        "you": "Tu",
        "exit": "Lascia vuoto e premi Invio per uscire dalla chat.",
        "waiting": "Il coach sta preparando la risposta",
        "goodbye": "A presto e in bocca al lupo!",
        "trace": "Traccia delle decisioni",
        "question": "Domanda principale {current} di {total}",
        "completed_count": "{completed}/{total} domande principali completate",
        "follow_up": "Approfondimento della domanda attuale",
        "questions": "Le tue domande all'azienda",
        "completed": "Colloquio completato",
        "early_feedback": "Feedback anticipato",
        "ended": "Colloquio interrotto",
    },
}


class TerminalUI:
    def __init__(self, lang):
        self.lang = lang
        self.interactive = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
        self.color = self.interactive and "NO_COLOR" not in os.environ

    @property
    def text(self):
        return TEXT.get(self.lang, TEXT["de"])

    @property
    def width(self):
        return max(12, min(80, shutil.get_terminal_size().columns - 2))

    def style(self, text, code):
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def body(self, text, muted=False):
        # Preserve fixed-format feedback tables and code blocks; wrap prose to a comfortable reading width.
        code_block = False
        for line in str(text).splitlines():
            if line.lstrip().startswith("```"):
                code_block = not code_block
            if code_block or line.lstrip().startswith(("|", "```")):
                rendered = "  " + line
            elif line.strip():
                rendered = textwrap.fill(line, width=self.width, initial_indent="  ", subsequent_indent="  ")
            else:
                rendered = ""
            print(self.style(rendered, "2") if muted else rendered)

    def welcome(self, greeting):
        gap = max(2, self.width - 2 - len("PrepTalk") - len(self.text["language"]))
        print()
        print("  " + self.style("PrepTalk", "1;36") + " " * gap + self.style(self.text["language"], "2"))
        self.body(self.text["tagline"], muted=True)
        print("  " + self.style("─" * (self.width - 2), "2"))
        # Keep the setup question visually separate from the introduction in all three static greetings.
        intro, separator, question = greeting.rpartition(". ")
        self.message(f"{intro}.\n\n{question}" if separator else greeting)
        self.body(self.text["exit"], muted=True)
        print()

    def message(self, text):
        print("\n  " + self.style("Coach", "1;36"))
        self.body(text)
        print()

    def ask(self):
        try:
            return input("  " + self.style(self.text["you"], "1") + "  " + self.style("›", "36") + " ")
        except (EOFError, KeyboardInterrupt):
            print()
            return ""

    def progress(self, progress):
        if not progress:
            return
        phase = progress["phase"]
        if phase == "interview":
            label = self.text["question"].format(**progress)
        else:
            label = self.text[phase]
        self.body(label, muted=True)
        size = min(20, self.width - 6)
        filled = size * progress["completed"] // progress["total"]
        self.body("[" + "━" * filled + "·" * (size - filled) + "]", muted=True)
        self.body(self.text["completed_count"].format(**progress), muted=True)
        if phase == "interview" and progress.get("follow_up"):
            self.body(self.text["follow_up"], muted=True)
        print()

    @contextmanager
    def waiting(self):
        if not self.interactive:
            yield
            return

        stopped = threading.Event()
        frames = ("●··", "·●·", "··●", "·●·")

        def draw(index):
            label = textwrap.shorten(self.text["waiting"], width=max(1, self.width - 6), placeholder="…")
            print("\r\033[2K  " + self.style(label, "2") + " " + self.style(frames[index], "36"),
                  end="", flush=True)

        def animate():
            index = 0
            while not stopped.wait(0.18):
                index = (index + 1) % len(frames)
                draw(index)

        worker = threading.Thread(target=animate, daemon=True)
        print("\n\033[?25l", end="", flush=True)
        try:
            draw(0)
            worker.start()
            yield
        finally:
            stopped.set()
            if worker.ident is not None:
                worker.join()
            print("\r\033[2K\033[?25h", end="", flush=True)

    def goodbye(self):
        print()
        self.body(self.text["goodbye"], muted=True)
        print()

    def trace(self, path):
        self.body(f"{self.text['trace']}: {path}", muted=True)
