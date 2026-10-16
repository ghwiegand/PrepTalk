"""Small, dependency-free terminal presentation for the chat client."""

import os
import shutil
import sys
import textwrap
import threading
from contextlib import contextmanager

from .keys import KeyReader
from .view import TerminalView

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
        "pane_completed": "{completed}/{total} abgeschlossen",
        "finish": "Enter: beenden · ↑/↓ oder PgUp/PgDn: Verlauf",
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
        "start_voice": "Voice starten",
        "menu_mode": "Modus",
        "mode_chat": "Chat",
        "mode_voice": "Voice (experimentell)",
        "voice_controls": "Leertaste: Aufnahme starten · Enter: tippen · Esc: beenden",
        "history": "↑/↓: Verlauf · PgUp/PgDn: blättern",
        "voice_recording": "● Aufnahme läuft · Enter: zur Transkription senden · Esc: beenden · maximal 2 Minuten",
        "voice_input": "Mikrofon",
        "voice_mic_waiting": "Warte auf Mikrofonsignal …",
        "voice_recorded": "Aufnahme beendet · Enter: zur Transkription senden · Esc: beenden",
        "voice_transcribing": "Deine Aufnahme wird transkribiert",
        "voice_speaking": "Der Coach spricht · Esc: Vorlesen stoppen · Ctrl-C: beenden",
        "voice_no_speech": "Keine Sprache erkannt. Versuche es nochmals oder drücke Enter zum Tippen.",
        "voice_error": "Voice-Fehler: {error}",
        "voice_unavailable": "Voice ist noch nicht bereit: {error}",
        "voice_return": "Enter: zurück zum Menü",
        "voice_mac_only": "Die experimentelle Voice-Version läuft derzeit lokal auf macOS.",
        "voice_setup": "Führe einmal make voice-setup aus. FFmpeg, whisper-cli und das Whisper-Modell müssen vorhanden sein.",
        "voice_terminal": "Voice benötigt ein interaktives Terminal.",
        "voice_missing_language": "Installiere eine macOS-Systemstimme für die ausgewählte Sprache.",
        "voice_transcription_error": "Die Transkription ist fehlgeschlagen. Prüfe das Whisper-Modell.",
        "voice_recording_error": "Die Aufnahme ist fehlgeschlagen. Prüfe Mikrofonfreigabe und PREPTALK_MIC_DEVICE.",
        "voice_playback_error": "Die Sprachausgabe ist fehlgeschlagen. Die Antwort steht weiterhin im Chat.",
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
        "pane_completed": "{completed}/{total} terminées",
        "finish": "Entrée : quitter · ↑/↓ ou PgUp/PgDn : historique",
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
        "start_voice": "Démarrer la voix",
        "menu_mode": "Mode",
        "mode_chat": "Chat",
        "mode_voice": "Voix (expérimental)",
        "voice_controls": "Espace : enregistrer · Entrée : écrire · Échap : quitter",
        "history": "↑/↓ : historique · PgUp/PgDn : défiler",
        "voice_recording": "● Enregistrement · Entrée : envoyer pour transcription · Échap : quitter · maximum 2 minutes",
        "voice_input": "Microphone",
        "voice_mic_waiting": "En attente du signal du microphone …",
        "voice_recorded": "Enregistrement terminé · Entrée : transcrire · Échap : quitter",
        "voice_transcribing": "Transcription de ton enregistrement",
        "voice_speaking": "Le coach parle · Échap : arrêter la lecture · Ctrl-C : quitter",
        "voice_no_speech": "Aucune parole reconnue. Réessaie ou appuie sur Entrée pour écrire.",
        "voice_error": "Erreur vocale : {error}",
        "voice_unavailable": "Le mode vocal n'est pas encore prêt : {error}",
        "voice_return": "Entrée : retour au menu",
        "voice_mac_only": "Cette version vocale expérimentale fonctionne actuellement en local sur macOS.",
        "voice_setup": "Lance une fois make voice-setup. FFmpeg, whisper-cli et le modèle Whisper sont nécessaires.",
        "voice_terminal": "Le mode vocal nécessite un terminal interactif.",
        "voice_missing_language": "Installe une voix système macOS pour la langue sélectionnée.",
        "voice_transcription_error": "La transcription a échoué. Vérifie le modèle Whisper.",
        "voice_recording_error": "L'enregistrement a échoué. Vérifie l'accès au microphone et PREPTALK_MIC_DEVICE.",
        "voice_playback_error": "La lecture vocale a échoué. La réponse reste visible dans le chat.",
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
        "pane_completed": "{completed}/{total} completate",
        "finish": "Invio: esci · ↑/↓ o PgUp/PgDn: cronologia",
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
        "start_voice": "Avvia la voce",
        "menu_mode": "Modalità",
        "mode_chat": "Chat",
        "mode_voice": "Voce (sperimentale)",
        "voice_controls": "Spazio: registra · Invio: scrivi · Esc: esci",
        "history": "↑/↓: cronologia · PgUp/PgDn: scorri",
        "voice_recording": "● Registrazione · Invio: invia alla trascrizione · Esc: esci · massimo 2 minuti",
        "voice_input": "Microfono",
        "voice_mic_waiting": "In attesa del segnale del microfono …",
        "voice_recorded": "Registrazione terminata · Invio: trascrivi · Esc: esci",
        "voice_transcribing": "Trascrizione della registrazione",
        "voice_speaking": "Il coach parla · Esc: interrompi la lettura · Ctrl-C: esci",
        "voice_no_speech": "Nessuna voce riconosciuta. Riprova o premi Invio per scrivere.",
        "voice_error": "Errore vocale: {error}",
        "voice_unavailable": "La modalità vocale non è ancora pronta: {error}",
        "voice_return": "Invio: torna al menu",
        "voice_mac_only": "Questa versione vocale sperimentale funziona attualmente in locale su macOS.",
        "voice_setup": "Esegui una volta make voice-setup. Servono FFmpeg, whisper-cli e il modello Whisper.",
        "voice_terminal": "La modalità vocale richiede un terminale interattivo.",
        "voice_missing_language": "Installa una voce di sistema macOS per la lingua selezionata.",
        "voice_transcription_error": "Trascrizione non riuscita. Controlla il modello Whisper.",
        "voice_recording_error": "Registrazione non riuscita. Controlla l'accesso al microfono e PREPTALK_MIC_DEVICE.",
        "voice_playback_error": "Riproduzione vocale non riuscita. La risposta resta visibile nella chat.",
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
        self.screen_active = False
        self.view = None

    def _write(self, text="", *, end="\n", flush=False):
        if self.view:
            self.view.append(text)
        else:
            print(text, end=end, flush=flush)

    @contextmanager
    def screen(self, enabled=True):
        """Own one terminal screen across setup and either conversation mode."""
        active = enabled and self.interactive
        if active:
            self.screen_active = True
            print("\033[?1049h\033[?25l", end="", flush=True)
        try:
            yield
        finally:
            if active:
                self.close_screen()

    def close_screen(self):
        if self.screen_active:
            self.screen_active = False
            print("\033[?25h\033[?1049l", end="", flush=True)

    @property
    def text(self):
        return TEXT.get(self.lang, TEXT["de"])

    @property
    def width(self):
        if self.view:
            return self.view.width
        return max(12, min(80, shutil.get_terminal_size().columns - 2))

    def style(self, text, code):
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def body_lines(self, text, width=None):
        # Preserve fixed-format feedback tables and code blocks; wrap prose to a comfortable reading width.
        lines = []
        code_block = False
        for line in str(text).splitlines():
            if line.lstrip().startswith("```"):
                code_block = not code_block
            if width is None and (code_block or line.lstrip().startswith(("|", "```"))):
                rendered = "  " + line
            elif line.strip():
                rendered = textwrap.fill(line, width=width or self.width,
                                         initial_indent="  ", subsequent_indent="  ")
            else:
                rendered = ""
            lines.extend(rendered.split("\n"))
        return lines

    def body(self, text, muted=False):
        if self.view:
            self.view.append(text, "2" if muted else None)
            return
        for line in self.body_lines(text):
            self._write(self.style(line, "2") if muted else line)

    def header(self):
        if self.view:
            self.view.render()
            return
        gap = max(2, self.width - 2 - len("PrepTalk") - len(self.text["language"]))
        print()
        print("  " + self.style("PrepTalk", "1;36") + " " * gap + self.style(self.text["language"], "2"))
        self.body(self.text["tagline"], muted=True)
        print("  " + self.style("─" * (self.width - 2), "2"))

    def welcome(self, greeting, header=True, voice=False):
        if self.interactive:
            self.ensure_view().start_chat()
        if header:
            self.header()
        # Keep the setup question visually separate from the introduction in all three static greetings.
        intro, separator, question = greeting.rpartition(". ")
        self.message(f"{intro}.\n\n{question}" if separator else greeting)
        if not voice and not self.view:
            self.body(self.text["exit"], muted=True)
        self._write()

    def ensure_view(self):
        if self.view is None:
            self.view = TerminalView(self)
        return self.view

    def menu(self, rows, footer, focus):
        if self.interactive:
            self.ensure_view().show_menu(rows, footer, focus)
        else:
            self.header()
            for text, style in rows:
                print(self.style("  " + text, style) if style else "  " + text)
            for text, _ in footer:
                self.body(text, muted=True)

    def message(self, text):
        if self.view:
            self.view.append("\nCoach", "1;36")
            self.view.append(text)
            self.view.append()
            return
        self._write("\n  " + self.style("Coach", "1;36"))
        self.body(text)
        self._write()

    def refresh(self):
        if self.view:
            self.view.render()

    def navigate(self, key):
        return self.view.navigate(key) if self.view else False

    def voice_controls(self, visible=True):
        if self.view:
            lines = [(self.text["voice_controls"], "2"), (self.text["history"], "2")] if visible else []
            self.view.set_footer(lines)
        elif visible:
            self.body(self.text["voice_controls"], muted=True)

    def ask(self):
        return self.prompt(self.text["you"]) or ""

    def prompt(self, label):
        try:
            if self.view:
                self.view.set_footer([(self.text["exit"], "2"), (self.text["history"], "2")])
                answer = self.view.prompt(label)
                if answer:
                    self.view.append(f"{label}: {answer}")
                return answer
            if self.screen_active:
                print("\033[?25h", end="", flush=True)
            return input("  " + self.style(label, "1") + "  " + self.style("›", "36") + " ")
        except (EOFError, KeyboardInterrupt):
            print()
            return None

    def progress(self, progress):
        if self.view:
            self.view.set_progress(progress)
            return
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
        self._write()

    def wait_for_exit(self):
        if self.view:
            self.view.set_footer([(self.text["finish"], "2")])
            with KeyReader() as keyboard:
                while (key := keyboard.read(timeout=0.1)) not in ("enter", "back", "quit"):
                    self.navigate(key)
                    self.refresh()

    @contextmanager
    def microphone_meter(self):
        """Show recent measured input levels as moving bars, with no fabricated animation."""
        previous_lines = 0

        def draw(levels, seconds, db, finished=False):
            nonlocal previous_lines
            if not self.interactive:
                return
            columns = min(24, max(1, (self.width - 6) // 2))
            levels = ([0] * columns + levels)[-columns:]
            glyphs = " ▁▂▃▄▅▆▇█"
            clock = f"{int(seconds) // 60:02}:{int(seconds) % 60:02}"
            decibels = f"{db:.0f}" if db != float("-inf") else "−∞"
            lines = [f"  {self.text['voice_input']}  {clock}  {decibels} dBFS"]
            color = "31" if db > -3 else "36"
            for row in range(3, -1, -1):
                bars = " ".join(glyphs[max(0, min(8, round(level * 32) - row * 8))] for level in levels)
                lines.append("  " + bars)
            if finished:
                status = self.text["voice_recorded"]
            elif seconds == 0:
                status = self.text["voice_mic_waiting"]
            else:
                status = self.text["voice_recording"]
            lines.extend(textwrap.wrap(status, width=self.width, initial_indent="  ", subsequent_indent="  "))
            if self.view:
                # The footer belongs to the left pane; it never scrolls the coach or transcript.
                plain = [(line[2:], "31" if db > -3 else "36") for line in lines[:5]]
                self.view.set_footer(plain + [(status, "2")])
                return
            prefix = f"\033[{previous_lines}F" if previous_lines else ""
            lines[1:5] = [self.style(line, color) for line in lines[1:5]]
            print(prefix + "\033[0J" + "\n".join(lines), flush=True)
            previous_lines = len(lines)

        if self.interactive and not self.view:
            print("\033[?25l", end="", flush=True)
        try:
            yield draw
        finally:
            if self.view:
                self.view.set_footer([])
            elif self.interactive:
                print("\033[?25h", end="", flush=True)

    @contextmanager
    def waiting(self, label=None, *, speaking=False):
        if not self.interactive:
            yield
            return

        stopped = threading.Event()
        frames = ("●··", "·●·", "··●", "·●·")

        def draw(index):
            if self.view:
                self.view.set_footer([(f"{label or self.text['waiting']} {frames[index]}", "2")],
                                     mouth=index if speaking else None)
                return
            message = textwrap.shorten(label or self.text["waiting"], width=max(1, self.width - 6), placeholder="…")
            print("\r\033[2K  " + self.style(message, "2") + " " + self.style(frames[index], "36"),
                  end="", flush=True)

        def animate():
            index = 0
            while not stopped.wait(0.18):
                index = (index + 1) % len(frames)
                draw(index)

        worker = threading.Thread(target=animate, daemon=True)
        if not self.view:
            self._write("\n\033[?25l", end="", flush=True)
        try:
            draw(0)
            worker.start()
            yield
        finally:
            stopped.set()
            if worker.ident is not None:
                worker.join()
            if self.view:
                self.view.set_footer([], mouth=0 if speaking else None)
            else:
                print("\r\033[2K\033[?25h", end="", flush=True)

    def goodbye(self):
        self._write()
        self.body(self.text["goodbye"], muted=True)
        self._write()

    def trace(self, path):
        self.body(f"{self.text['trace']}: {path}", muted=True)
