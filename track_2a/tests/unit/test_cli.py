"""CLI startup and backend handoff, using only the standard library."""

import contextlib
import io
import unittest
from unittest.mock import patch

from preptalk.cli import client, menu, terminal, view, voice
from preptalk.cli.terminal import TEXT, TerminalUI
from preptalk.coach.greetings import ASK_JOB


class ChatClientTest(unittest.TestCase):
    def test_interactive_chat_keeps_menu_panes_and_shows_progress_and_final_feedback(self):
        ui = TerminalUI("de")
        ui.interactive = True
        ui.color = False
        states = [
            {"messages": [{"content": "Erzähl mir von dir."}], "context": {"lang": "de"},
             "coach": {"progress": {"current": 1, "total": 10, "completed": 0, "phase": "interview"}}},
            {"messages": [{"content": "Dein Feedback: Du hast klare Beispiele genannt."}],
             "coach": {"done": True, "progress": {"total": 10, "completed": 10, "phase": "completed"}}},
        ]
        with patch("sys.argv", ["preptalk"]), patch.object(client, "TerminalUI", return_value=ui), \
                patch.object(menu, "KeyReader") as navigation, patch.object(view, "KeyReader") as typing, \
                patch.object(terminal, "KeyReader") as closing, patch.object(voice, "VoiceIO") as audio, \
                patch.object(client, "post", side_effect=[{"thread_id": "test"}, *states]) as post, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            menu_view = []

            def choose(**kwargs):
                menu_view.append(ui.view)
                return "end" if len(menu_view) == 1 else "enter"

            def type_answer():
                self.assertIs(ui.view, menu_view[0])
                self.assertTrue(ui.screen_active)
                self.assertNotIn("\033[?1049l", output.getvalue())
                if ui.view.progress:
                    lines, _, _ = ui.view._layout()
                    self.assertIn("Hauptfrage 1 von 10", "\n".join(line.partition("│")[2] for line in lines))
                return next(keys)

            keys = iter([*"Ich bin Lea.", "enter", *"Ich arbeite gerne im Team.", "enter"])
            navigation.return_value.__enter__.return_value.read.side_effect = choose
            typing.return_value.__enter__.return_value.read.side_effect = lambda **kwargs: type_answer()

            def finish(**kwargs):
                self.assertTrue(ui.screen_active)
                self.assertTrue(any("Dein Feedback:" in text for text, _ in ui.view.entries))
                self.assertEqual(ui.view.progress["phase"], "completed")
                return "enter"

            closing.return_value.__enter__.return_value.read.side_effect = finish
            client.main()
        audio.assert_not_called()
        self.assertNotIn("voice", post.call_args_list[1].args[1]["input"])
        self.assertEqual(output.getvalue().count("\033[?1049h"), 1)
        self.assertEqual(output.getvalue().count("\033[?1049l"), 1)
        self.assertFalse(ui.screen_active)

    def test_empty_input_exits_locally_in_each_language(self):
        for lang in ASK_JOB:
            with self.subTest(lang=lang), patch("sys.argv", ["preptalk", "--no-menu", "--lang", lang]), \
                    patch("builtins.input", return_value="") as ask, patch.object(client, "post") as post, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                client.main()
                post.assert_not_called()
                self.assertIn(TEXT[lang]["you"], ask.call_args.args[0])
                self.assertIn(TEXT[lang]["exit"], output.getvalue())
                self.assertIn(TEXT[lang]["goodbye"], output.getvalue())

    def test_first_answer_hands_off_greeting_and_displays_progress(self):
        state = {
            "messages": [{"role": "assistant", "content": "Erzähl mir von dir."}],
            "context": {"lang": "de"},
            "coach": {"progress": {"current": 1, "total": 10, "completed": 0,
                                    "phase": "interview", "follow_up": False}},
        }
        with patch("sys.argv", ["preptalk", "--no-menu"]), patch("builtins.input", side_effect=["Ich bin Lea.", ""]), \
                patch.object(client, "post", side_effect=[{"thread_id": "test"}, state]) as post, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            client.main()
        self.assertEqual(post.call_count, 2)
        turn = post.call_args_list[1].args[1]["input"]
        self.assertTrue(turn["setup_asked"])
        self.assertEqual(turn["messages"][0]["content"], ASK_JOB["de"])
        self.assertEqual(turn["messages"][1]["content"], "Ich bin Lea.")
        self.assertIn("Hauptfrage 1 von 10", output.getvalue())


if __name__ == "__main__":
    unittest.main()
