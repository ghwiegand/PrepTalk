"""Orb motion and measured speech envelopes, without playing sound."""

from array import array
import contextlib
import io
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import wave

from preptalk.cli import menu
from preptalk.cli.orb import PALETTE, render_orb
from preptalk.cli.speech import SpeechEnvelope
from preptalk.cli.terminal import TerminalUI


def plain(lines):
    return [re.sub(r"\033\[[\d;]*m", "", line) for line in lines]


class OrbTest(unittest.TestCase):
    def test_frames_fit_their_grid_and_use_the_requested_palette(self):
        for width, height in ((23, 5), (23, 9), (35, 12)):
            with self.subTest(width=width, height=height):
                frame = render_orb(width, height, 2, 0.8, color=True)
                self.assertEqual(len(frame), height)
                self.assertTrue(all(len(line) == width and line.isascii() for line in plain(frame)))
                colors = set(re.findall(r"\033\[38;2;(\d+);(\d+);(\d+)m", "".join(frame)))
                self.assertTrue(colors)
                self.assertTrue(colors <= {tuple(map(str, rgb)) for rgb in PALETTE})
                self.assertNotIn("\033", "".join(render_orb(width, height, 2)))

    def test_idle_motion_is_slow_and_audio_changes_the_frame(self):
        initial = render_orb(35, 12, 0)
        next_frame = render_orb(35, 12, 1 / 30)
        later = render_orb(35, 12, 25)
        changed = sum(a != b for row, other in zip(initial, next_frame) for a, b in zip(row, other))
        self.assertLess(changed, 35 * 12 * 0.05)
        self.assertNotEqual(initial, later)
        self.assertNotEqual(initial, render_orb(35, 12, 0, 0.9))
        self.assertEqual(initial, render_orb(35, 12, 0, -1))
        self.assertEqual(render_orb(35, 12, 0, 1), render_orb(35, 12, 0, 2))

    def test_menu_animates_without_input_and_keeps_left_pane_unchanged(self):
        ui = TerminalUI("de")
        ui.interactive = True
        ui.color = False
        frames = []
        with patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 30))), \
                patch("preptalk.cli.view.time.monotonic", return_value=100) as clock, \
                patch.object(menu, "KeyReader") as keyboard, contextlib.redirect_stdout(io.StringIO()):

            def read(**kwargs):
                frames.append(plain(ui.view._previous))
                clock.return_value = 125
                return "" if len(frames) == 1 else "quit"

            keyboard.return_value.__enter__.return_value.read.side_effect = read
            self.assertIsNone(menu.main_menu(ui))
        self.assertEqual([line.partition("│")[0] for line in frames[0]],
                         [line.partition("│")[0] for line in frames[1]])
        self.assertNotEqual([line.partition("│")[2] for line in frames[0]],
                            [line.partition("│")[2] for line in frames[1]])

    def test_reduced_motion_keeps_orb_static_with_time_and_audio(self):
        ui = TerminalUI("de")
        ui.interactive = True
        ui.color = False
        with patch.dict(os.environ, {"PREPTALK_REDUCED_MOTION": "1"}), \
                patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 30))), \
                patch("preptalk.cli.view.time.monotonic", return_value=100) as clock, \
                contextlib.redirect_stdout(io.StringIO()):
            ui.ensure_view().render()
            first = ui.view._previous.copy()
            clock.return_value = 140
            ui.view.set_footer([], audio_level=0.9)
            self.assertEqual(first, ui.view._previous)


class SpeechEnvelopeTest(unittest.TestCase):
    def write(self, path, amplitudes):
        with wave.open(str(path), "wb") as output:
            output.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
            for amplitude in amplitudes:
                output.writeframes(array("h", [amplitude] * 735).tobytes())

    def test_levels_follow_quiet_loud_and_silent_pcm_at_playback_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "speech.wav"
            self.write(path, [0] * 10 + [1000] * 10 + [12000] * 10)
            envelope = SpeechEnvelope(path)
        self.assertEqual(envelope.at(0.1), 0)
        self.assertGreater(envelope.at(0.45), 0)
        self.assertGreater(envelope.at(0.85), envelope.at(0.45))
        self.assertEqual(envelope.at(-0.1), 0)
        self.assertEqual(envelope.at(1.1), 0)

    def test_silent_file_has_no_fabricated_speech_motion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "silence.wav"
            self.write(path, [0] * 30)
            self.assertEqual(SpeechEnvelope(path).levels, [0] * 30)

    def test_empty_audio_is_rejected_before_playback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.wav"
            self.write(path, [])
            with self.assertRaises(ValueError):
                SpeechEnvelope(path)
