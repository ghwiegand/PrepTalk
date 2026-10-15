"""CLI startup and backend handoff, using only the standard library."""

import contextlib
import io
import unittest
from unittest.mock import patch

from preptalk.cli import client
from preptalk.cli.terminal import TEXT
from preptalk.coach.greetings import ASK_JOB


class ChatClientTest(unittest.TestCase):
    def test_empty_input_exits_locally_in_each_language(self):
        for lang in ASK_JOB:
            with self.subTest(lang=lang), patch("sys.argv", ["preptalk", "--lang", lang]), \
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
        with patch("sys.argv", ["preptalk"]), patch("builtins.input", side_effect=["Ich bin Lea.", ""]), \
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
