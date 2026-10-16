"""Fixed voice panes, scrolling, resizing, and playback without audio devices."""

import contextlib
import io
import os
import re
import threading
import unittest
from unittest.mock import Mock, patch

from preptalk.cli import voice, view
from preptalk.cli.terminal import TerminalUI
from preptalk.cli.view import MOUTHS
from preptalk.coach.greetings import ASK_JOB


def frame(ui):
    return [re.sub(r"\033\[[\d;]*m", "", line) for line in ui.view._previous]


def face_position(ui):
    lines = frame(ui)
    return next((row, line.index("| o   o |")) for row, line in enumerate(lines) if "| o   o |" in line)


class PortraitTest(unittest.TestCase):
    def make_ui(self, lang="de"):
        ui = TerminalUI(lang)
        ui.interactive = True
        ui.color = False
        return ui

    def test_one_fixed_coach_for_each_language(self):
        for lang, greeting in ASK_JOB.items():
            ui = self.make_ui(lang)
            with self.subTest(lang=lang), patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 30))), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                ui.welcome(greeting, voice=True)
                position = face_position(ui)
                for turn in range(20):
                    ui.body(f"{ui.text['you']}: Antwort {turn}")
                    ui.message(f"Frage {turn}: " + "Langer Text im Gespräch. " * 12)
                    ui.progress({"phase": "interview", "current": 2, "total": 10, "completed": 1})
                    ui.voice_controls()
                    self.assertEqual(face_position(ui), position)
                    self.assertEqual(sum("| o   o |" in line for line in frame(ui)), 1)
                self.assertIn("Frage 19", "\n".join(frame(ui)))
                self.assertTrue(all(len(line) <= 99 for line in frame(ui)))
                # Absolute-position paints must never advance the terminal's scrollback.
                self.assertNotIn("\n", output.getvalue())
                self.assertNotIn("\r", output.getvalue())

    def test_progress_stays_in_sidebar_in_each_language(self):
        for lang in ASK_JOB:
            ui = self.make_ui(lang)
            with self.subTest(lang=lang), patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))), \
                    contextlib.redirect_stdout(io.StringIO()):
                ui.welcome(ASK_JOB[lang])
                progress = {"phase": "interview", "current": 3, "total": 10, "completed": 2, "follow_up": True}
                ui.progress(progress)
                position = face_position(ui)
                for _ in range(3):
                    ui.message("Une longue réponse. " * 20)
                    ui.view.editing = (ui.text["you"], "", 0)
                    ui.refresh()
                    left = " ".join(line.partition("│")[0] for line in frame(ui)[4:])
                    right = " ".join(line.partition("│")[2].strip() for line in frame(ui)[4:])
                    self.assertIn(ui.text["question"].format(**progress), " ".join(right.split()))
                    self.assertIn(ui.text["pane_completed"].format(**progress), " ".join(right.split()))
                    self.assertIn("[━━━", right)
                    self.assertNotIn("[━━━", left)
                    self.assertEqual(face_position(ui), position)
                    self.assertTrue(all(len(line) < 80 for line in frame(ui)))
                ui.progress(None)
                self.assertNotIn("[━━━", "\n".join(frame(ui)))

    def test_narrow_layout_keeps_progress_available_without_sidebar(self):
        ui = self.make_ui()
        with patch("shutil.get_terminal_size", return_value=os.terminal_size((60, 24))), \
                contextlib.redirect_stdout(io.StringIO()):
            ui.welcome(ASK_JOB['de'])
            ui.progress({"phase": "interview", "current": 3, "total": 10, "completed": 2})
            rendered = "\n".join(frame(ui))
            self.assertIn("Hauptfrage 3 von 10", rendered)
            self.assertIn("2/10 abgeschlossen", rendered)
            self.assertNotIn("│", rendered)
            self.assertTrue(all(len(line) < 60 for line in frame(ui)))

    def test_history_scrolls_without_moving_the_coach(self):
        ui = self.make_ui()
        with patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 30))), \
                contextlib.redirect_stdout(io.StringIO()):
            ui.welcome(ASK_JOB['de'], voice=True)
            ui.body("\n".join(f"Zeile {number:03}" for number in range(100)))
            position = face_position(ui)
            ui.voice_controls()
            self.assertIn("Zeile 099", "\n".join(frame(ui)))
            self.assertTrue(ui.navigate("home"))
            self.assertIn("Zeile 000", "\n".join(frame(ui)))
            self.assertNotIn("Zeile 099", "\n".join(frame(ui)))
            self.assertEqual(face_position(ui), position)
            ui.navigate("page_down")
            self.assertNotIn("Zeile 000", "\n".join(frame(ui)))
            ui.navigate("end")
            self.assertIn("Zeile 099", "\n".join(frame(ui)))
            self.assertEqual(face_position(ui), position)

    def test_meter_updates_in_left_footer_and_keeps_a_single_instruction(self):
        ui = self.make_ui()
        ui.color = True
        with patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 30))), \
                contextlib.redirect_stdout(io.StringIO()):
            ui.welcome(ASK_JOB['de'], voice=True)
            position = face_position(ui)
            entries = list(ui.view.entries)
            ui.voice_controls()
            with ui.microphone_meter() as draw:
                for second in range(1, 5):
                    draw([0.5, 1], second, -12)
                    self.assertEqual(face_position(ui), position)
                    rendered = "\n".join(frame(ui))
                    self.assertIn(f"00:0{second}", rendered)
                    self.assertIn("█", rendered)
                    self.assertEqual(rendered.count("Aufnahme läuft"), 1)
                    self.assertNotIn("Aufnahme starten", rendered)
                    self.assertNotIn("\033", rendered)
                    self.assertTrue(all(len(line) < 100 for line in frame(ui)))
            self.assertEqual(list(ui.view.entries), entries)
            self.assertNotIn("Aufnahme läuft", "\n".join(frame(ui)))

    def test_resize_reflows_history_and_restores_the_pane(self):
        ui = self.make_ui()
        with patch("shutil.get_terminal_size") as size, contextlib.redirect_stdout(io.StringIO()):
            size.return_value = os.terminal_size((100, 30))
            ui.welcome(ASK_JOB['de'], voice=True)
            entries = list(ui.view.entries)
            for columns, rows, visible in ((60, 24, False), (120, 40, True), (80, 12, False), (80, 24, True)):
                size.return_value = os.terminal_size((columns, rows))
                ui.refresh()
                self.assertEqual(any("| o   o |" in line for line in frame(ui)), visible)
                self.assertEqual(len(frame(ui)), rows)
                self.assertTrue(all(len(line) < columns for line in frame(ui)))
                self.assertEqual(list(ui.view.entries), entries)

    def test_noninteractive_chat_and_voice_keep_plain_output(self):
        for interactive, voice_mode in ((False, True), (False, False)):
            ui = self.make_ui()
            ui.interactive = interactive
            with self.subTest(interactive=interactive, voice_mode=voice_mode), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                ui.welcome(ASK_JOB['de'], voice=voice_mode)
                self.assertIsNone(ui.view)
                self.assertNotIn("| o   o |", output.getvalue())
                self.assertIn("Für welche Lehre", output.getvalue())

    def test_finish_and_escape_close_the_animated_mouth(self):
        for skipped in (False, True):
            ui = self.make_ui()
            audio = voice.VoiceIO.__new__(voice.VoiceIO)
            audio.ui = ui
            audio.voices = {"de": "Anna"}
            process = Mock(returncode=-15 if skipped else 0)
            process.poll.return_value = None
            moved = threading.Event()

            def observe(lines, mouth=None):
                update(lines, mouth=mouth)
                if mouth:
                    moved.set()

            def next_key(**kwargs):
                self.assertTrue(moved.wait(timeout=2), "Mouth never animated during playback")
                if skipped:
                    return "back"
                process.poll.return_value = 0
                return ""

            with self.subTest(skipped=skipped), \
                    patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 30))), \
                    patch.object(voice.subprocess, "Popen", return_value=process), \
                    patch.object(voice, "KeyReader") as reader, contextlib.redirect_stdout(io.StringIO()) as output:
                reader.return_value.__enter__.return_value.read.side_effect = next_key
                ui.welcome(ASK_JOB['de'], voice=True)
                update = ui.view.set_footer
                with patch.object(ui.view, "set_footer", side_effect=observe):
                    self.assertTrue(audio.speak(ASK_JOB['de']))
                self.assertIn(MOUTHS[1], output.getvalue())
                self.assertTrue(any(MOUTHS[0] in line for line in frame(ui)))
                self.assertFalse(ui.view.footer)
            if skipped:
                process.terminate.assert_called_once()
                process.wait.assert_called_once()
            else:
                process.terminate.assert_not_called()

    def test_long_unicode_answer_can_be_edited_without_overwriting_the_coach(self):
        ui = self.make_ui()
        answer = "Café für Québec " * 10
        with patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 30))), \
                patch.object(view, "KeyReader") as reader, contextlib.redirect_stdout(io.StringIO()):
            ui.welcome(ASK_JOB['de'], voice=True)
            position = face_position(ui)
            keys = iter([*answer, "backspace", "left", "X", "home", "q", "end", "!", "enter"])

            def read(**kwargs):
                self.assertEqual(face_position(ui), position)
                self.assertTrue(all(len(line) < 100 for line in frame(ui)))
                return next(keys)

            reader.return_value.__enter__.return_value.read.side_effect = read
            result = ui.ask()
            self.assertEqual(result, "q" + answer[:-2] + "X" + answer[-2] + "!")
            self.assertIn((f"Du: {result}", None), ui.view.entries)
            self.assertEqual(face_position(ui), position)

    def test_wide_characters_stay_inside_the_left_pane(self):
        ui = self.make_ui()
        with patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))), \
                contextlib.redirect_stdout(io.StringIO()):
            ui.welcome(ASK_JOB['de'], voice=True)
            ui.message("Antwort: " + "你好 👋 " * 30)
            for line in frame(ui)[4:-1]:
                left, separator, right = line.partition("│")
                self.assertTrue(separator)
                # Each Chinese character and this emoji occupy two cells.
                occupied = len(left) + sum(left.count(char) for char in "你好👋")
                self.assertEqual(occupied, ui.view.width)
                self.assertLess(occupied + 1 + len(right), 80)
