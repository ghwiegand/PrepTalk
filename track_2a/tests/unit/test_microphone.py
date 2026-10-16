"""Live levels reflect captured PCM, while partial pipe reads preserve the complete recording."""

from array import array
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
import wave

from preptalk.cli.microphone import PCMRecorder
from preptalk.cli.terminal import TEXT, TerminalUI


def pcm(samples):
    values = array("h", samples)
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


class FragmentedPipe(io.BytesIO):
    def read(self, size):
        return super().read(min(size, 137))  # A pipe can split a PCM16 sample across two reads.


class MicrophoneTest(unittest.TestCase):
    def test_levels_and_duration_come_from_actual_audio(self):
        recorder = PCMRecorder()
        data = pcm([3276] * 8000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answer.wav"
            recorder.capture(io.BytesIO(data), path)
            self.assertIsNone(recorder.error)
            levels, seconds, db = recorder.snapshot()
            self.assertAlmostEqual(seconds, 0.5)
            self.assertAlmostEqual(db, -20, places=1)
            self.assertTrue(all(0 < level < 1 for level in levels))
            with wave.open(str(path), "rb") as recording:
                self.assertEqual(recording.readframes(8000), data)

    def test_fragmented_reads_preserve_every_frame(self):
        data = pcm(list(range(-8000, 8000)))
        recorder = PCMRecorder()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answer.wav"
            recorder.capture(FragmentedPipe(data), path)
            self.assertIsNone(recorder.error)
            self.assertEqual(recorder.snapshot()[1], 1)
            with wave.open(str(path), "rb") as recording:
                self.assertEqual(recording.readframes(16000), data)

    def test_silence_has_no_visual_activity(self):
        recorder = PCMRecorder()
        with tempfile.TemporaryDirectory() as directory:
            recorder.capture(io.BytesIO(pcm([0] * 8000)), Path(directory) / "silent.wav")
        levels, seconds, db = recorder.snapshot()
        self.assertEqual(seconds, 0.5)
        self.assertEqual(db, float("-inf"))
        self.assertFalse(any(levels))

    def test_meter_shows_levels_and_send_instruction_in_each_language(self):
        for lang in TEXT:
            ui = TerminalUI(lang)
            ui.interactive = True
            ui.color = False
            with self.subTest(lang=lang), contextlib.redirect_stdout(io.StringIO()) as output:
                with ui.microphone_meter() as draw:
                    draw([0.5, 1], 12, -12)
                    draw([0] * 24, 120, float("-inf"), finished=True)
                rendered = output.getvalue()
                self.assertIn("█", rendered)
                self.assertIn("00:12", rendered)
                self.assertIn("-12 dBFS", rendered)
                self.assertIn(TEXT[lang]["voice_recorded"].split(" · ")[0], rendered)
                self.assertTrue(rendered.endswith("\033[?25h"))
