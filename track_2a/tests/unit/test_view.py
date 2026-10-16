"""Fixed terminal panes, scrolling, resizing, and playback without audio devices."""

import contextlib
import io
import os
import re
import threading
import unittest
from unittest.mock import Mock, patch

from preptalk.cli import voice, view
from preptalk.cli.terminal import TerminalUI
from preptalk.coach.greetings import ASK_JOB


def frame(ui):
    return [re.sub(r"\033\[[\d;]*m", "", line) for line in ui.view._previous]


def orb_position(ui):
    lines = frame(ui)
    return next((row + 2, len(line.partition("│")[0]) + 1) for row, line in enumerate(lines)
                if line.partition("│")[2].strip() == "Coach")


class LayoutTest(unittest.TestCase):
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
                position = orb_position(ui)
                for turn in range(20):
                    ui.body(f"{ui.text['you']}: Antwort {turn}")
                    ui.message(f"Frage {turn}: " + "Langer Text im Gespräch. " * 12)
                    ui.progress({"phase": "interview", "current": 2, "total": 10, "completed": 1})
                    ui.voice_controls()
                    self.assertEqual(orb_position(ui), position)
                    self.assertEqual(sum(line.partition("│")[2].strip() == "Coach" for line in frame(ui)), 1)
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
                position = orb_position(ui)
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
                    self.assertEqual(orb_position(ui), position)
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

    def test_progress_is_centered_at_the_bottom_in_each_language_and_size(self):
        for lang in ASK_JOB:
            for columns, rows in ((80, 18), (80, 24), (144, 30), (180, 42)):
                ui = self.make_ui(lang)
                with self.subTest(lang=lang, columns=columns, rows=rows), \
                        patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, rows))), \
                        contextlib.redirect_stdout(io.StringIO()):
                    ui.welcome(ASK_JOB[lang])
                    ui.progress({"phase": "interview", "current": 3, "total": 10,
                                 "completed": 2, "follow_up": True})
                    right = [line.partition("│")[2] for line in frame(ui)]
                    bar_row = next(index for index, line in enumerate(right) if "[━━━" in line)
                    block = [(index, line) for index, line in enumerate(right)
                             if index >= bar_row - 1 and line.strip()]
                    self.assertEqual(block[-1][0], rows - 3)
                    for _, line in block:
                        leading = len(line) - len(line.lstrip())
                        trailing = len(line) - len(line.rstrip())
                        self.assertLessEqual(abs(leading - trailing), 1)
                    ui.message("Noch eine lange Antwort. " * 30)
                    ui.view.editing = (ui.text["you"], "Meine Antwort", 13)
                    ui.refresh()
                    updated = [line.partition("│")[2] for line in frame(ui)]
                    self.assertEqual(updated[bar_row:], right[bar_row:])
                    self.assertTrue(all(len(line) < columns for line in frame(ui)))

    def test_history_scrolls_without_moving_the_coach(self):
        ui = self.make_ui()
        with patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 30))), \
                contextlib.redirect_stdout(io.StringIO()):
            ui.welcome(ASK_JOB['de'], voice=True)
            ui.body("\n".join(f"Zeile {number:03}" for number in range(100)))
            position = orb_position(ui)
            ui.voice_controls()
            self.assertIn("Zeile 099", "\n".join(frame(ui)))
            self.assertTrue(ui.navigate("home"))
            self.assertIn("Zeile 000", "\n".join(frame(ui)))
            self.assertNotIn("Zeile 099", "\n".join(frame(ui)))
            self.assertEqual(orb_position(ui), position)
            ui.navigate("page_down")
            self.assertNotIn("Zeile 000", "\n".join(frame(ui)))
            ui.navigate("end")
            self.assertIn("Zeile 099", "\n".join(frame(ui)))
            self.assertEqual(orb_position(ui), position)

    def test_meter_updates_in_left_footer_and_keeps_a_single_instruction(self):
        ui = self.make_ui()
        ui.color = True
        with patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 30))), \
                contextlib.redirect_stdout(io.StringIO()):
            ui.welcome(ASK_JOB['de'], voice=True)
            position = orb_position(ui)
            entries = list(ui.view.entries)
            ui.voice_controls()
            with ui.microphone_meter() as draw:
                for second in range(1, 5):
                    draw([0.5, 1], second, -12)
                    self.assertEqual(orb_position(ui), position)
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
                self.assertEqual(any(line.partition("│")[2].strip() == "Coach" for line in frame(ui)), visible)
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
                self.assertNotIn("│", output.getvalue())
                self.assertIn("Für welche Lehre", output.getvalue())

    def test_finish_and_escape_reset_audio_animation(self):
        from tests.unit.test_voice import write_wav

        for skipped in (False, True):
            ui = self.make_ui()
            audio = voice.VoiceIO.__new__(voice.VoiceIO)
            audio.ui = ui
            audio.voices = {"de": "Anna"}
            synthesis = Mock(returncode=0)
            synthesis.poll.return_value = 0
            process = Mock(returncode=-15 if skipped else 0)
            process.poll.return_value = None
            moved = threading.Event()

            def launch(command, **kwargs):
                if command[0] == "/usr/bin/say":
                    write_wav(command[command.index("-o") + 1], 2000)
                    return synthesis
                return process

            def observe(lines, audio_level=None):
                update(lines, audio_level=audio_level)
                if audio_level:
                    moved.set()

            def next_key(**kwargs):
                self.assertTrue(moved.wait(timeout=2), "Orb never received audio levels during playback")
                if skipped:
                    return "back"
                process.poll.return_value = 0
                return ""

            with self.subTest(skipped=skipped), \
                    patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 30))), \
                    patch.object(voice.subprocess, "Popen", side_effect=launch), \
                    patch.object(voice, "KeyReader") as reader, contextlib.redirect_stdout(io.StringIO()):
                reader.return_value.__enter__.return_value.read.side_effect = next_key
                ui.welcome(ASK_JOB['de'], voice=True)
                update = ui.view.set_footer
                with patch.object(ui.view, "set_footer", side_effect=observe):
                    self.assertTrue(audio.speak(ASK_JOB['de']))
                self.assertEqual(ui.view.audio_level, 0)
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
            position = orb_position(ui)
            keys = iter([*answer, "backspace", "left", "X", "home", "q", "end", "!", "enter"])

            def read(**kwargs):
                self.assertEqual(orb_position(ui), position)
                self.assertTrue(all(len(line) < 100 for line in frame(ui)))
                return next(keys)

            reader.return_value.__enter__.return_value.read.side_effect = read
            result = ui.ask()
            self.assertEqual(result, "q" + answer[:-2] + "X" + answer[-2] + "!")
            self.assertIn((f"Du: {result}", None), ui.view.entries)
            self.assertEqual(orb_position(ui), position)

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

    def test_wrapped_input_navigation_keeps_cursor_visible_after_resize(self):
        ui = self.make_ui()
        with patch("shutil.get_terminal_size") as size, patch.object(view, "KeyReader") as reader, \
                contextlib.redirect_stdout(io.StringIO()):
            size.return_value = os.terminal_size((100, 30))
            ui.welcome(ASK_JOB['de'])
            width = ui.view._input_width(ui.text["you"])
            answer = "a" * (width * 9 + 7)
            keys = iter([*answer, "home", "right", "right", "down", "X", "up", "Y", "page_up",
                         "end", "left", "delete", "!", "enter"])
            visited = []

            def read(**kwargs):
                key = next(keys)
                label, value, position = ui.view.editing
                row, col = ui.view._cursor
                self.assertLessEqual(col, ui.view.width)
                self.assertLess(row, size.return_value.lines)
                # The actual cursor cell is visible in the rendered input, even in a long draft.
                visible = frame(ui)[row - 1]
                if position < len(value):
                    self.assertEqual(visible[col - 1], value[position])
                if key == "X":
                    self.assertEqual(position, width + 2)
                elif key == "Y":
                    self.assertEqual(position, 3)
                    size.return_value = os.terminal_size((80, 24))
                visited.append(position)
                return key

            reader.return_value.__enter__.return_value.read.side_effect = read
            self.assertEqual(ui.ask(), "aaaY" + "a" * (width - 1) + "X" + answer[width + 2:-1] + "!")
            self.assertIn(width + 2, visited)
            self.assertIsNone(ui.view.editing)

    def test_word_jumps_insert_delete_and_boundary_navigation(self):
        ui = self.make_ui()
        with patch.object(view, "KeyReader") as reader, contextlib.redirect_stdout(io.StringIO()):
            ui.welcome(ASK_JOB['de'])
            keys = [*"Bonjour tout le monde", "word_left", "word_left", "X", "word_right", "delete",
                    "home", "left", "backspace", "^", "end", "right", "delete", "!", "enter"]
            reader.return_value.__enter__.return_value.read.side_effect = keys
            self.assertEqual(ui.ask(), "^Bonjour tout Xle onde!")

    def test_escape_confirmation_is_localized_and_cancel_preserves_draft_and_cursor(self):
        for lang in ASK_JOB:
            for cancel in ("enter", " ", "back"):
                ui = self.make_ui(lang)
                with self.subTest(lang=lang, cancel=cancel), patch.object(view, "KeyReader") as reader, \
                        contextlib.redirect_stdout(io.StringIO()):
                    ui.welcome(ASK_JOB[lang])
                    progress = ui.view.progress
                    keys = iter([*"Café", "left", "back", cancel, "X", "enter"])

                    def read(**kwargs):
                        key = next(keys)
                        if key == cancel and ui.view.confirmation is not None:
                            self.assertFalse(ui.view.confirmation)  # No is the default.
                            self.assertFalse(ui.view._cursor)
                            rendered = " ".join(" ".join(frame(ui)).split())
                            self.assertIn(ui.text["leave_question"], rendered)
                            self.assertIn("› " + ui.text["no"], rendered)
                            self.assertIn(ui.text["yes"], rendered)
                        return key

                    reader.return_value.__enter__.return_value.read.side_effect = read
                    self.assertEqual(ui.ask(), "CafXé")
                    self.assertIs(ui.view.progress, progress)
                    self.assertIsNone(ui.view.confirmation)

    def test_confirming_return_cleans_up_prompt_and_ctrl_c_quits_directly(self):
        for keys, expected in ((["back", "up", "enter"], "menu"),
                               (["back", "left", " "], "menu"),
                               (["back", "tab", "enter"], "menu"),
                               (["quit"], "quit"), (["back", "quit"], "quit")):
            ui = self.make_ui()
            with self.subTest(keys=keys), patch.object(view, "KeyReader") as reader, \
                    contextlib.redirect_stdout(io.StringIO()):
                ui.welcome(ASK_JOB['de'])
                reader.return_value.__enter__.return_value.read.side_effect = keys
                if expected == "menu":
                    with self.assertRaises(view.ReturnToMenu):
                        ui.ask()
                else:
                    self.assertEqual(ui.ask(), "")
                self.assertIsNone(ui.view.editing)
                self.assertIsNone(ui.view.confirmation)
                self.assertEqual(ui.view.footer, [])
