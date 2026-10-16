"""Exercise real terminal key sequences and restoration of normal text input."""

import os
import unittest
from unittest.mock import patch

from preptalk.cli.keys import KeyReader


@unittest.skipIf(os.name == "nt", "POSIX pseudo-terminal checks")
class KeyReaderTest(unittest.TestCase):
    def assert_restored(self, terminal, original):
        import termios

        restored = termios.tcgetattr(terminal)
        # macOS sets this transient retype-pending-input flag when canonical input resumes.
        restored[3] &= ~getattr(termios, "PENDIN", 0)
        original[3] &= ~getattr(termios, "PENDIN", 0)
        self.assertEqual(restored, original)

    def test_arrow_sequences_space_enter_and_escape(self):
        import termios

        master, slave = os.openpty()
        try:
            with os.fdopen(slave, "r") as terminal, patch("sys.stdin", terminal):
                original = termios.tcgetattr(terminal)
                with KeyReader() as keyboard:
                    os.write(master, b"\x1b[B \x1bOA\r\x1b[F\x1b[6~")
                    self.assertEqual([keyboard.read() for _ in range(6)],
                                     ["down", "space", "up", "enter", "end", "page_down"])
                    os.write(master, b"\x1b")
                    self.assertEqual(keyboard.read(), "back")
                self.assert_restored(terminal, original)
        finally:
            os.close(master)

    def test_terminal_settings_restored_after_failure(self):
        import termios

        master, slave = os.openpty()
        try:
            with os.fdopen(slave, "r") as terminal, patch("sys.stdin", terminal):
                original = termios.tcgetattr(terminal)
                with self.assertRaises(RuntimeError):
                    with KeyReader():
                        raise RuntimeError("failed to render")
                self.assert_restored(terminal, original)
        finally:
            os.close(master)

    def test_text_editing_preserves_utf8_spaces_and_q(self):
        master, slave = os.openpty()
        try:
            with os.fdopen(slave, "r") as terminal, patch("sys.stdin", terminal), KeyReader() as keyboard:
                os.write(master, "q éü".encode("utf-8") + b"\x7f\x1b[D\x1b[3~\r")
                keys = []
                for _ in range(12):
                    key = keyboard.read(timeout=0.1, text=True)
                    if key:
                        keys.append(key)
                    if key == "enter":
                        break
                self.assertEqual(keys, ["q", " ", "é", "ü", "backspace", "left", "delete", "enter"])
        finally:
            os.close(master)

    def test_switching_from_voice_controls_to_typing_keeps_buffered_input(self):
        master, slave = os.openpty()
        try:
            with os.fdopen(slave, "r") as terminal, patch("sys.stdin", terminal):
                with KeyReader() as keyboard:
                    os.write(master, b"\rQuick answer\r")
                    self.assertEqual(keyboard.read(), "enter")
                with KeyReader() as keyboard:
                    keys = [keyboard.read(timeout=0.1, text=True) for _ in range(13)]
                self.assertEqual(keys, [*"Quick answer", "enter"])
        finally:
            os.close(master)

    def test_word_navigation_and_home_end_shortcuts(self):
        master, slave = os.openpty()
        try:
            with os.fdopen(slave, "r") as terminal, patch("sys.stdin", terminal), KeyReader() as keyboard:
                os.write(master, b"\x1b[1;5D\x1b[1;5C\x1bb\x1bf\x01\x05\t")
                self.assertEqual([keyboard.read(text=True) for _ in range(7)],
                                 ["word_left", "word_right", "word_left", "word_right", "home", "end", "tab"])
        finally:
            os.close(master)
