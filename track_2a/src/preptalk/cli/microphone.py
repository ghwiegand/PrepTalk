"""Save the live PCM stream and measure input levels without another audio dependency."""

from array import array
from collections import deque
import math
import sys
import threading
import wave


class PCMRecorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.levels = deque(maxlen=24)
        self.frames = 0
        self.db = float("-inf")
        self.error = None

    def capture(self, stream, path):
        try:
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                pending = b""
                while chunk := stream.read(3200):  # about 100 ms of 16 kHz mono PCM16
                    chunk = pending + chunk
                    end = len(chunk) - len(chunk) % 2
                    pending = chunk[end:]
                    chunk = chunk[:end]
                    if not chunk:
                        continue
                    output.writeframesraw(chunk)
                    samples = array("h", chunk)
                    if sys.byteorder != "little":
                        samples.byteswap()
                    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
                    db = 20 * math.log10(rms) if rms else float("-inf")
                    with self.lock:
                        self.frames += len(samples)
                        self.db = db
                        self.levels.append(max(0, min(1, (db + 60) / 60)))
                if pending:
                    raise ValueError("Incomplete microphone PCM sample")
        except Exception as exc:
            self.error = exc

    def snapshot(self):
        with self.lock:
            return list(self.levels), self.frames / 16000, self.db
