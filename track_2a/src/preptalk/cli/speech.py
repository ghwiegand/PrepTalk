"""Measure the speech WAV used for playback so the orb follows actual sound, including pauses."""

from array import array
import math
import sys
import wave

from .orb import FPS


class SpeechEnvelope:
    def __init__(self, path):
        self.levels = []
        with wave.open(str(path), "rb") as source:
            if source.getsampwidth() != 2 or source.getcomptype() != "NONE" or not source.getnframes():
                raise ValueError("Speech playback requires PCM16 WAV")
            self.window = max(1, source.getframerate() // FPS)
            self.rate = source.getframerate()
            while data := source.readframes(self.window):
                samples = array("h", data)
                if sys.byteorder != "little":
                    samples.byteswap()
                rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
                # A fixed dB scale keeps digital silence at zero and louder words visibly stronger.
                db = 20 * math.log10(rms) if rms else -60
                self.levels.append(max(0, min(1, (db + 54) / 42)))

    def at(self, seconds):
        index = int(seconds * self.rate / self.window)
        return self.levels[index] if seconds >= 0 and index < len(self.levels) else 0
