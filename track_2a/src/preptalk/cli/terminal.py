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
        "main_menu": "Hauptmenü",
        "menu_language": "Sprache",
        "scenario": "Szenario",
        "posting": "Lehrstelle",
        "none": "Keine Auswahl",
        "start_chat": "Chat starten",
        "menu_help": "↑/↓ Navigieren · Leertaste/Enter Öffnen oder starten · Esc Beenden",
        "dropdown_help": "↑/↓ Auswählen · Leertaste/Enter Bestätigen · Esc Zurück",
        "loading_choices": "Auswahl wird geladen",
        "catalog_error": "Die Auswahl konnte nicht geladen werden. Prüfe deine Internetverbindung und versuche es erneut.",
        "preset_greeting": "Deine Auswahl ist bereit. Schreib eine kurze Nachricht, um das Übungsgespräch zu starten.",
        "scenario_hint": "Ein Szenario enthält bereits eine Lehrstelle und ein fiktives Bewerberprofil.",
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
        "main_menu": "Menu principal",
        "menu_language": "Langue",
        "scenario": "Scénario",
        "posting": "Offre d'apprentissage",
        "none": "Aucune sélection",
        "start_chat": "Démarrer le chat",
        "menu_help": "↑/↓ Naviguer · Espace/Entrée Ouvrir ou démarrer · Échap Quitter",
        "dropdown_help": "↑/↓ Choisir · Espace/Entrée Confirmer · Échap Retour",
        "loading_choices": "Chargement des choix",
        "catalog_error": "Impossible de charger les choix. Vérifie ta connexion Internet et réessaie.",
        "preset_greeting": "Ton choix est prêt. Écris un court message pour commencer l'entretien d'entraînement.",
        "scenario_hint": "Un scénario comprend déjà une offre d'apprentissage et un profil de candidature fictif.",
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
        "main_menu": "Menu principale",
        "menu_language": "Lingua",
        "scenario": "Scenario",
        "posting": "Offerta di tirocinio",
        "none": "Nessuna selezione",
        "start_chat": "Avvia la chat",
        "menu_help": "↑/↓ Naviga · Spazio/Invio Apri o avvia · Esc Esci",
        "dropdown_help": "↑/↓ Scegli · Spazio/Invio Conferma · Esc Indietro",
        "loading_choices": "Caricamento delle opzioni",
        "catalog_error": "Impossibile caricare le opzioni. Controlla la connessione Internet e riprova.",
        "preset_greeting": "La tua scelta è pronta. Scrivi un breve messaggio per iniziare il colloquio di prova.",
        "scenario_hint": "Uno scenario include già un'offerta di tirocinio e un profilo di candidatura fittizio.",
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

    def header(self):
        gap = max(2, self.width - 2 - len("PrepTalk") - len(self.text["language"]))
        print()
        print("  " + self.style("PrepTalk", "1;36") + " " * gap + self.style(self.text["language"], "2"))
        self.body(self.text["tagline"], muted=True)
        print("  " + self.style("─" * (self.width - 2), "2"))

    def welcome(self, greeting, header=True):
        if header:
            self.header()
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
        return self.prompt(self.text["you"]) or ""

    def prompt(self, label):
        try:
            return input("  " + self.style(label, "1") + "  " + self.style("›", "36") + " ")
        except (EOFError, KeyboardInterrupt):
            print()
            return None

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
    def waiting(self, label=None):
        if not self.interactive:
            yield
            return

        stopped = threading.Event()
        frames = ("●··", "·●·", "··●", "·●·")

        def draw(index):
            message = textwrap.shorten(label or self.text["waiting"], width=max(1, self.width - 6), placeholder="…")
            print("\r\033[2K  " + self.style(message, "2") + " " + self.style(frames[index], "36"),
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
