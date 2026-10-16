"""Brand highlight consistency and terminal color fallbacks."""

import contextlib
import io
import os
import unittest
from unittest.mock import patch

from preptalk.cli.terminal import TerminalUI
from preptalk.cli.theme import ACCENT_RGB
from preptalk.coach.greetings import ASK_JOB


class ThemeTest(unittest.TestCase):
    def test_highlight_adapts_to_truecolor_256_and_basic_terminals(self):
        for environment, expected in (
            ({"TERM": "xterm-256color", "COLORTERM": "truecolor"}, ACCENT_RGB),
            ({"TERM": "xterm-ghostty"}, ACCENT_RGB),
            ({"TERM": "xterm-256color"}, "38;5;116"),
            ({"TERM": "xterm"}, "36"),
        ):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                ui = TerminalUI("de")
                ui.color = True
                self.assertEqual(ui.style("Highlight", "1;36"), f"\033[1;{expected}mHighlight\033[0m")
                self.assertEqual(ui.style("Audio clipping", "31"), "\033[31mAudio clipping\033[0m")

    def test_brand_color_reaches_header_progress_and_orb_accents(self):
        with patch.dict(os.environ, {"COLORTERM": "truecolor"}, clear=True), \
                patch("shutil.get_terminal_size", return_value=os.terminal_size((144, 30))), \
                patch("preptalk.cli.view.time.monotonic", return_value=100), \
                contextlib.redirect_stdout(io.StringIO()):
            ui = TerminalUI("de")
            ui.interactive = ui.color = True
            ui.welcome(ASK_JOB["de"])
            ui.progress({"phase": "interview", "current": 1, "total": 10, "completed": 0})
            frame = ui.view._previous
            self.assertIn(ACCENT_RGB, frame[1])
            bar = next(line for line in frame if "[··················]" in line)
            self.assertIn(ACCENT_RGB, bar)
            orb = "".join(line.partition("│")[2] for line in frame[6:22])
            self.assertIn(ACCENT_RGB, orb)
            self.assertIn("\033[0;37m", orb)
            self.assertNotIn("\033[36m", "".join(frame))

    def test_no_color_keeps_output_plain(self):
        with patch.dict(os.environ, {"NO_COLOR": "1", "COLORTERM": "truecolor"}, clear=True), \
                patch("sys.stdout.isatty", return_value=True):
            ui = TerminalUI("de")
            self.assertEqual(ui.style("Highlight", "1;36"), "Highlight")
