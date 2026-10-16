"""Experimental local macOS voice transport. The coach still receives ordinary text messages."""

from array import array
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave

from .keys import KeyReader
from .microphone import PCMRecorder

VOICE_HOME = Path(__file__).resolve().parents[3] / ".voice"


class VoiceError(Exception):
    """A recoverable audio/setup failure, safe to show in the terminal."""


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def speech_text(text):
    """Avoid reading Markdown syntax and speech-control markup aloud."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", str(text))
    text = re.sub(r"\[\[.*?\]\]", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*[#>*|]+\s*", "", text)
    return re.sub(r"[*`|]", "", text).strip()


def has_audio(path):
    with wave.open(str(path), "rb") as recording:
        if recording.getnframes() < recording.getframerate() // 4:
            return False
        samples = array("h", recording.readframes(recording.getnframes()))
        if sys.byteorder != "little":
            samples.byteswap()
    return bool(samples) and max(abs(sample) for sample in samples) > 50


class VoiceIO:
    def __init__(self, ui):
        self.ui = ui
        if sys.platform != "darwin":
            raise VoiceError(ui.text["voice_mac_only"])
        self.ffmpeg = shutil.which("ffmpeg")
        self.whisper = (os.environ.get("PREPTALK_WHISPER_BIN") or shutil.which("whisper-cli")
                        or str(VOICE_HOME / "whisper.cpp/build/bin/whisper-cli"))
        self.model = Path(os.environ.get("PREPTALK_WHISPER_MODEL", str(VOICE_HOME / "ggml-base.bin"))).expanduser()
        if not self.ffmpeg or not Path(self.whisper).is_file() or not self.model.is_file():
            raise VoiceError(ui.text["voice_setup"])
        if not sys.stdin.isatty():
            raise VoiceError(ui.text["voice_terminal"])
        result = subprocess.run(["/usr/bin/say", "-v", "?"], capture_output=True, text=True, timeout=15)
        self.voices = {}
        for line in result.stdout.splitlines():
            match = re.match(r"(.+?)\s+((?:de|fr|it)_\w+)\s+#", line)
            if match:
                self.voices.setdefault(match[2][:2], match[1].strip())
        preferred = {"de": "Anna", "fr": "Thomas", "it": "Alice"}
        for lang, name in preferred.items():
            if any(re.match(rf"{name}\s+{lang}_", line) for line in result.stdout.splitlines()):
                self.voices[lang] = name
        if not os.environ.get("PREPTALK_TTS_VOICE") and ui.lang not in self.voices:
            raise VoiceError(ui.text["voice_missing_language"])

    def transcribe(self, path):
        output = path.with_suffix("")
        result = subprocess.run([self.whisper, "-m", str(self.model), "-l", self.ui.lang, "-f", str(path),
                                 "-otxt", "-of", str(output), "-nt", "-np"],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
        transcript = output.with_suffix(".txt")
        if result.returncode or not transcript.is_file():
            raise VoiceError(self.ui.text["voice_transcription_error"])
        return transcript.read_text(encoding="utf-8").strip()

    def record(self, path):
        device = os.environ.get("PREPTALK_MIC_DEVICE", "default")
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "avfoundation", "-i", f":{device}",
                   "-t", "120", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                   "-f", "s16le", "-flush_packets", "1", "pipe:1"]
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=errors, start_new_session=True)
            recorder = PCMRecorder()
            worker = threading.Thread(target=recorder.capture, args=(process.stdout, path), daemon=True)
            cancelled = False
            try:
                self.ui.body(self.ui.text["voice_recording"])
                worker.start()
                with self.ui.microphone_meter() as draw, KeyReader() as keyboard:
                    while True:
                        code = process.poll()
                        if recorder.error or code not in (None, 0):
                            raise VoiceError(self.ui.text["voice_recording_error"])
                        draw(*recorder.snapshot(), finished=code == 0)
                        key = keyboard.read(timeout=0.1)
                        if key in ("quit", "back"):
                            cancelled = True
                            break
                        # A held spacebar repeats key events. Only Enter submits this recording.
                        if key == "enter":
                            break
                if process.poll() is None:
                    try:
                        process.stdin.write(b"q\n")
                        process.stdin.flush()
                        process.wait(timeout=5)
                    except (BrokenPipeError, subprocess.TimeoutExpired):
                        stop_process(process)
            finally:
                stop_process(process)
                if worker.ident is not None:
                    worker.join(timeout=3)
                process.stdout.close()
                process.stdin.close()
            if cancelled:
                return False
            if worker.is_alive() or recorder.error or process.returncode != 0 or not path.is_file():
                raise VoiceError(self.ui.text["voice_recording_error"])
        return True

    def ask(self):
        while True:
            self.ui.body(self.ui.text["voice_controls"], muted=True)
            with KeyReader() as keyboard:
                while (key := keyboard.read()) not in ("space", "enter", "back", "quit"):
                    pass
            if key in ("back", "quit"):
                return ""
            if key == "enter":
                return self.ui.ask()
            try:
                with tempfile.TemporaryDirectory(prefix="preptalk-voice-") as directory:
                    path = Path(directory) / "answer.wav"
                    if not self.record(path):
                        return ""
                    if not has_audio(path):
                        self.ui.body(self.ui.text["voice_no_speech"])
                        continue
                    with self.ui.waiting(self.ui.text["voice_transcribing"]):
                        text = self.transcribe(path)
                if not text:
                    self.ui.body(self.ui.text["voice_no_speech"])
                    continue
                self.ui.body(f"{self.ui.text['you']}: {text}")
                return text
            except (VoiceError, OSError, subprocess.SubprocessError, wave.Error) as exc:
                self.ui.body(self.ui.text["voice_error"].format(error=str(exc)))
            except KeyboardInterrupt:
                return ""

    def speak(self, text):
        voice = os.environ.get("PREPTALK_TTS_VOICE") or self.voices.get(self.ui.lang)
        try:
            with self.ui.waiting(self.ui.text["voice_speaking"]):
                result = subprocess.run(["/usr/bin/say", "-v", voice, "-f", "-"], input=speech_text(text),
                                        capture_output=True, text=True, timeout=300)
            if result.returncode:
                raise VoiceError(self.ui.text["voice_playback_error"])
        except (VoiceError, OSError, subprocess.SubprocessError) as exc:
            self.ui.body(self.ui.text["voice_error"].format(error=str(exc)))
        except KeyboardInterrupt:
            return False
        return True
