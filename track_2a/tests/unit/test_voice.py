"""Voice control flow and cleanup, without opening microphones or playing audio."""

from array import array
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

from preptalk.cli import client, menu, voice, voice_setup
from preptalk.cli.terminal import TEXT, TerminalUI


def write_wav(path, value=0):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(array("h", [value] * 8000).tobytes())


class VoiceClientTest(unittest.TestCase):
    def test_chat_default_does_not_initialize_voice(self):
        with patch("sys.argv", ["preptalk", "--no-menu"]), patch("builtins.input", return_value=""), \
                patch.object(voice, "VoiceIO") as audio, contextlib.redirect_stdout(io.StringIO()):
            client.main()
        audio.assert_not_called()

    def test_voice_transcript_uses_existing_coach_and_speaks_response(self):
        state = {"messages": [{"content": "Parle-moi de toi."}], "context": {"lang": "fr"}, "coach": {"done": True}}
        with patch("sys.argv", ["preptalk", "--no-menu", "--mode", "voice", "--lang", "fr"]), \
                patch.object(voice, "VoiceIO") as audio, \
                patch.object(client, "post", side_effect=[{"thread_id": "voice"}, state]) as post, \
                contextlib.redirect_stdout(io.StringIO()):
            audio.return_value.ask.return_value = "Je suis Alex et je veux faire un apprentissage."
            audio.return_value.speak.return_value = True
            client.main()
        turn = post.call_args_list[1].args[1]["input"]
        self.assertTrue(turn["voice"])
        self.assertEqual(turn["lang"], "fr")
        self.assertEqual(turn["messages"][-1]["content"], audio.return_value.ask.return_value)
        self.assertEqual(audio.return_value.speak.call_count, 2)
        audio.return_value.speak.assert_called_with("Parle-moi de toi.")

    def test_empty_voice_input_never_connects(self):
        with patch("sys.argv", ["preptalk", "--no-menu", "--mode", "voice"]), \
                patch.object(voice, "VoiceIO") as audio, patch.object(client, "post") as post, \
                contextlib.redirect_stdout(io.StringIO()):
            audio.return_value.ask.return_value = ""
            client.main()
        post.assert_not_called()

    def test_voice_controls_appear_once_after_greeting_in_each_language(self):
        for lang in TEXT:
            audio = voice.VoiceIO.__new__(voice.VoiceIO)
            audio.ui = TerminalUI(lang)
            audio.speak = Mock(return_value=True)
            with self.subTest(lang=lang), \
                    patch("sys.argv", ["preptalk", "--no-menu", "--mode", "voice", "--lang", lang]), \
                    patch.object(voice, "VoiceIO", return_value=audio), patch.object(voice, "KeyReader") as reader, \
                    patch("builtins.input", return_value=""), patch.object(client, "post") as post, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                reader.return_value.__enter__.return_value.read.return_value = "enter"
                client.main()
                self.assertEqual(output.getvalue().count(TEXT[lang]["voice_controls"]), 1)
                post.assert_not_called()

    def test_missing_voice_setup_returns_to_menu_without_connecting(self):
        with patch("sys.argv", ["preptalk"]), \
                patch.object(client, "main_menu", side_effect=[(None, None, "de", "voice"), None]) as menu, \
                patch.object(voice, "VoiceIO", side_effect=voice.VoiceError("make voice-setup")), \
                patch("builtins.input", return_value=""), patch.object(client, "post") as post, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            client.main()
        post.assert_not_called()
        self.assertEqual(menu.call_count, 2)
        self.assertEqual(menu.call_args.args[-1], "chat")
        self.assertIn("make voice-setup", output.getvalue())

    def test_voice_transition_keeps_one_screen_open_until_exit(self):
        ui = TerminalUI("de")
        ui.interactive = True
        ui.color = False
        with patch("sys.argv", ["preptalk", "--mode", "voice"]), \
                patch.object(client, "TerminalUI", return_value=ui), patch.object(menu, "KeyReader") as reader, \
                patch.object(voice, "VoiceIO") as audio, contextlib.redirect_stdout(io.StringIO()) as output:
            reader.return_value.__enter__.return_value.read.side_effect = ["end", "enter"]

            def answer():
                self.assertTrue(ui.screen_active)
                self.assertNotIn("\033[?1049l", output.getvalue())
                return ""

            audio.return_value.ask.side_effect = answer
            client.main()
        self.assertEqual(output.getvalue().count("\033[?1049h"), 1)
        self.assertEqual(output.getvalue().count("\033[?1049l"), 1)
        self.assertFalse(ui.screen_active)

    def test_screen_is_restored_if_voice_fails(self):
        ui = TerminalUI("de")
        ui.interactive = True
        with patch("sys.argv", ["preptalk", "--mode", "voice"]), \
                patch.object(client, "TerminalUI", return_value=ui), patch.object(menu, "KeyReader") as reader, \
                patch.object(voice, "VoiceIO") as audio, contextlib.redirect_stdout(io.StringIO()) as output:
            reader.return_value.__enter__.return_value.read.side_effect = ["end", "enter"]
            audio.return_value.ask.side_effect = RuntimeError("audio failed")
            with self.assertRaises(RuntimeError):
                client.main()
        self.assertEqual(output.getvalue().count("\033[?1049l"), 1)
        self.assertFalse(ui.screen_active)


class VoiceTransportTest(unittest.TestCase):
    def make_audio(self, lang="de"):
        audio = voice.VoiceIO.__new__(voice.VoiceIO)
        audio.ui = TerminalUI(lang)
        audio.whisper = "/test/whisper-cli"
        audio.model = Path("/test/model.bin")
        audio.ffmpeg = "/test/ffmpeg"
        audio.voices = {"de": "Anna", "fr": "Thomas", "it": "Alice"}
        return audio

    def test_silence_is_not_transcribed_and_typed_fallback_works(self):
        audio = self.make_audio()
        paths = []

        def record(path):
            paths.append(path)
            write_wav(path)
            return True

        with patch.object(voice, "KeyReader") as reader, patch.object(audio, "record", side_effect=record), \
                patch.object(audio, "transcribe") as transcribe, patch("builtins.input", return_value="Typed answer"), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            reader.return_value.__enter__.return_value.read.side_effect = ["space", "enter"]
            self.assertEqual(audio.ask(), "Typed answer")
        transcribe.assert_not_called()
        self.assertIn(TEXT["de"]["voice_no_speech"], output.getvalue())
        self.assertTrue(paths)
        self.assertFalse(paths[0].exists())

    def test_transcription_file_and_audio_are_removed_after_turn(self):
        audio = self.make_audio("it")
        paths = []

        def record(path):
            paths.append(path)
            write_wav(path, 1000)
            return True

        with patch.object(voice, "KeyReader") as reader, patch.object(audio, "record", side_effect=record), \
                patch.object(audio, "transcribe", return_value="Mi chiamo Alex."), \
                contextlib.redirect_stdout(io.StringIO()):
            reader.return_value.__enter__.return_value.read.return_value = "space"
            self.assertEqual(audio.ask(), "Mi chiamo Alex.")
        self.assertFalse(paths[0].parent.exists())

    def test_recording_cancel_stops_and_closes_child(self):
        audio = self.make_audio()
        process = Mock()
        process.stdout = io.BytesIO(b"")
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory, patch.object(voice.subprocess, "Popen", return_value=process), \
                patch.object(voice, "KeyReader") as reader, contextlib.redirect_stdout(io.StringIO()):
            reader.return_value.__enter__.return_value.read.return_value = "back"
            self.assertFalse(audio.record(Path(directory) / "cancelled.wav"))
        process.stdin.close.assert_called_once()
        process.wait.assert_called()
        process.terminate.assert_called_once()

    def test_repeated_spaces_do_not_submit_and_enter_preserves_full_recording(self):
        audio = self.make_audio()
        pcm = array("h", [1000] * 16000).tobytes()
        process = Mock(returncode=0)
        process.stdout = io.BytesIO(pcm)
        process.poll.return_value = 0  # Capture ended, but submission still requires Enter.
        with tempfile.TemporaryDirectory() as directory, patch.object(voice.subprocess, "Popen", return_value=process), \
                patch.object(voice, "KeyReader") as reader, contextlib.redirect_stdout(io.StringIO()):
            keys = reader.return_value.__enter__.return_value.read
            keys.side_effect = ["space", "space", "space", "enter"]
            path = Path(directory) / "answer.wav"
            self.assertTrue(audio.record(path))
            self.assertEqual(keys.call_count, 4)
            with wave.open(str(path), "rb") as recording:
                self.assertEqual(recording.getnframes(), 16000)
                self.assertEqual(recording.readframes(16000), pcm)
        process.stdin.write.assert_not_called()

    def test_transcription_uses_selected_language(self):
        audio = self.make_audio("fr")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answer.wav"
            path.with_suffix(".txt").write_text("Bonjour Alex.\n", encoding="utf-8")
            with patch.object(voice.subprocess, "run", return_value=Mock(returncode=0)) as run:
                self.assertEqual(audio.transcribe(path), "Bonjour Alex.")
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("-l") + 1], "fr")
            self.assertEqual(command[command.index("-m") + 1], str(audio.model))

    def test_speech_uses_language_voice_and_text_is_not_a_command(self):
        audio = self.make_audio("fr")
        process = Mock(returncode=0)
        process.poll.return_value = 0
        captured = {}

        def start(command, **kwargs):
            captured["text"] = kwargs["stdin"].read()
            return process

        with patch.dict("os.environ", {}, clear=True), \
                patch.object(voice.subprocess, "Popen", side_effect=start) as launch, patch.object(voice, "KeyReader"):
            self.assertTrue(audio.speak("**Bonjour** [[volm 0]] [Alex](https://example.com)."))
        self.assertEqual(launch.call_args.args[0], ["/usr/bin/say", "-v", "Thomas", "-f", "-"])
        self.assertEqual(captured["text"], "Bonjour  Alex.")

    def test_escape_stops_reading_but_quit_ends_the_conversation(self):
        for key, keep_chatting in (("back", True), ("quit", False)):
            audio = self.make_audio()
            process = Mock(returncode=-15)
            process.poll.return_value = None
            with self.subTest(key=key), patch.object(voice.subprocess, "Popen", return_value=process), \
                    patch.object(voice, "KeyReader") as reader:
                reader.return_value.__enter__.return_value.read.return_value = key
                self.assertEqual(audio.speak("Hallo Alex."), keep_chatting)
            process.terminate.assert_called_once()
            process.wait.assert_called_once()

    def test_capture_error_allows_retry_or_typing(self):
        audio = self.make_audio()
        with patch.object(voice, "KeyReader") as reader, \
                patch.object(audio, "record", side_effect=voice.VoiceError("microphone denied")), \
                patch("builtins.input", return_value="Typed answer"), contextlib.redirect_stdout(io.StringIO()) as output:
            reader.return_value.__enter__.return_value.read.side_effect = ["space", "enter"]
            self.assertEqual(audio.ask(), "Typed answer")
        self.assertIn("microphone denied", output.getvalue())

    def test_other_platforms_fail_before_opening_any_devices(self):
        with patch.object(voice.sys, "platform", "linux"), patch.object(voice.subprocess, "run") as run:
            with self.assertRaises(voice.VoiceError):
                voice.VoiceIO(TerminalUI("de"))
        run.assert_not_called()


class VoiceSetupTest(unittest.TestCase):
    def test_corrupt_download_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(voice_setup, "VOICE_HOME", Path(directory)), \
                patch.object(voice_setup.sys, "platform", "darwin"), \
                patch.object(voice_setup.shutil, "which", return_value="/test/tool"), \
                patch.object(voice_setup.subprocess, "run"), \
                patch.object(voice_setup.subprocess, "check_output", return_value=voice_setup.WHISPER_COMMIT), \
                patch.object(voice_setup.urllib.request, "urlopen") as download, \
                contextlib.redirect_stdout(io.StringIO()):
            download.return_value.__enter__.return_value = io.BytesIO(b"invalid model")
            with self.assertRaises(SystemExit):
                voice_setup.setup()
            self.assertFalse((Path(directory) / "ggml-base.bin").exists())
            self.assertFalse((Path(directory) / "ggml-base.part").exists())
