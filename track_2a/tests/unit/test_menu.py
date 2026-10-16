"""Menu navigation, localization and the resulting API request, without services or a model."""

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from preptalk.cli import catalog, client, menu
from preptalk.cli.terminal import TEXT, TerminalUI
from preptalk.coach.greetings import ASK_JOB


POSTINGS = {
    f"P-{n:02}": {"id": f"P-{n:02}", "lang": "de", "occupation": {
        "name_de": "Testberuf", "name_fr": "Métier de test", "name_it": "Professione di prova"},
        "company": {"name": f"Testbetrieb {n}", "place": "Chur"}}
    for n in range(1, 11)
}
CHOICES = {"posting": POSTINGS, "scenario": {
    "S-04": {"id": "S-04", "lang": "fr", "posting_id": "P-01", "situation": "online_interview"}}}


class MenuTest(unittest.TestCase):
    def test_interactive_menu_keeps_coach_fixed_and_translates_before_chat(self):
        ui = TerminalUI("de")
        ui.interactive = True
        ui.color = False
        snapshots = []
        keys = iter(["down", "down", "space", "down", "enter", "down", "space", "down", "enter",
                     "end", "enter"])
        with patch.object(menu, "KeyReader") as reader, patch.object(catalog, "load") as load, \
                patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))), \
                contextlib.redirect_stdout(io.StringIO()) as output:

            def read(**kwargs):
                snapshots.append(ui.view._previous.copy())
                return next(keys)

            reader.return_value.__enter__.return_value.read.side_effect = read
            self.assertEqual(menu.main_menu(ui), (None, None, "fr", "voice"))
            old_view = ui.view
            ui.welcome(ASK_JOB["fr"], voice=True)
            self.assertIs(ui.view, old_view)
            snapshots.append(ui.view._previous.copy())
            positions = [next((row, len(line.partition("│")[0])) for row, line in enumerate(frame)
                              if line.partition("│")[2].strip() == "Coach") for frame in snapshots]
            self.assertTrue(all(position == positions[0] for position in positions))
            translated = "\n".join(snapshots[-2])
            self.assertIn(TEXT["fr"]["main_menu"], translated)
            self.assertIn(TEXT["fr"]["mode_voice"], translated)
            self.assertNotIn(TEXT["de"]["main_menu"], translated)
            self.assertTrue(all(len(line) < 80 for frame in snapshots for line in frame))
            self.assertNotIn("\n", output.getvalue())
        load.assert_not_called()

    def test_interactive_long_dropdown_keeps_selected_item_visible(self):
        ui = TerminalUI("de")
        ui.interactive = True
        ui.color = False
        dropdown = [(None, ui.text["none"])] + [(key, key) for key in POSTINGS]
        with patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))), \
                contextlib.redirect_stdout(io.StringIO()):
            menu.draw(ui, 1, None, None, "chat", CHOICES, dropdown, 10, "")
            self.assertIn("› P-10", "\n".join(ui.view._previous))
            self.assertTrue(all(len(line) < 80 for line in ui.view._previous))

    def run_menu(self, keys, **kwargs):
        with patch.object(menu, "KeyReader") as reader, patch.object(catalog, "load", return_value=CHOICES), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            reader.return_value.__enter__.return_value.read.side_effect = keys
            result = menu.main_menu(TerminalUI("de"), **kwargs)
        return result, output.getvalue()

    def test_start_row_uses_no_presets_without_loading_the_catalog(self):
        with patch.object(menu, "KeyReader") as reader, patch.object(catalog, "load") as load, \
                contextlib.redirect_stdout(io.StringIO()):
            reader.return_value.__enter__.return_value.read.side_effect = ["down", "down", "down", "down", "enter"]
            self.assertEqual(menu.main_menu(TerminalUI("de")), (None, None, "de", "chat"))
        load.assert_not_called()

    def test_space_opens_dropdown_instead_of_starting_chat(self):
        result, output = self.run_menu(["space", "down", "space", "end", "enter"])
        self.assertEqual(result, ("S-04", None, "de", "chat"))
        self.assertIn("┌", output)
        self.assertIn("S-04", output)

    def test_voice_mode_is_opt_in_and_cancelling_keeps_chat(self):
        result, output = self.run_menu(["down", "down", "down", "space", "down", "enter", "end", "enter"])
        self.assertEqual(result, (None, None, "de", "voice"))
        self.assertIn(TEXT["de"]["mode_voice"], output)
        result, _ = self.run_menu(["down", "down", "down", "space", "down", "back", "end", "enter"])
        self.assertEqual(result, (None, None, "de", "chat"))

    def test_posting_replaces_scenario_and_can_be_cleared(self):
        result, _ = self.run_menu(["down", "space", "down", "down", "enter", "end", "enter"], scenario="S-04")
        self.assertEqual(result, (None, "P-02", "de", "chat"))
        result, _ = self.run_menu(["space", "down", "enter", "end", "enter"], posting="P-01")
        self.assertEqual(result, ("S-04", None, "de", "chat"))
        result, _ = self.run_menu(["down", "space", "home", "enter", "end", "enter"], posting="P-01")
        self.assertEqual(result, (None, None, "de", "chat"))

    def test_long_dropdown_scrolls_and_escape_preserves_selection(self):
        result, output = self.run_menu(["down", "space", "end", "enter", "space", "up", "back", "end", "enter"])
        self.assertEqual(result, (None, "P-10", "de", "chat"))
        self.assertIn("11/11", output)

    def test_language_changes_menu_choices_and_chat_handoff(self):
        for lang, steps in (("fr", 1), ("it", 2)):
            with self.subTest(lang=lang), patch("sys.argv", ["preptalk"]), \
                    patch.object(menu, "KeyReader") as reader, \
                    patch("builtins.input", side_effect=["Bonjour", ""]), \
                    patch.object(catalog, "load", return_value=CHOICES), \
                    patch.object(client, "post", side_effect=[{"thread_id": "test"}, {"messages": []}]) as post, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                reader.return_value.__enter__.return_value.read.side_effect = (
                    ["down", "down", "space"] + ["down"] * steps +
                    ["space", "up", "space", "down", "enter", "end", "enter"])
                client.main()
                turn = post.call_args_list[1].args[1]["input"]
                self.assertEqual(turn["lang"], lang)
                self.assertEqual(turn["posting_id"], "P-01")
                self.assertNotIn("scenario_id", turn)
                self.assertEqual(turn["messages"][0]["content"], TEXT[lang]["preset_greeting"])
                self.assertIn(TEXT[lang]["main_menu"], output.getvalue())
                self.assertIn(POSTINGS["P-01"]["occupation"][f"name_{lang}"], output.getvalue())

    def test_scenario_handoff_and_language_override(self):
        with patch("sys.argv", ["preptalk", "--lang", "it"]), patch.object(menu, "KeyReader") as reader, \
                patch("builtins.input", side_effect=["Ciao", ""]), \
                patch.object(catalog, "load", return_value=CHOICES), \
                patch.object(client, "post", side_effect=[{"thread_id": "test"}, {"messages": []}]) as post, \
                contextlib.redirect_stdout(io.StringIO()):
            reader.return_value.__enter__.return_value.read.side_effect = ["space", "down", "enter", "end", "enter"]
            client.main()
        turn = post.call_args_list[1].args[1]["input"]
        self.assertEqual(turn["scenario_id"], "S-04")
        self.assertEqual(turn["lang"], "it")
        self.assertNotIn("posting_id", turn)

    def test_catalog_failure_leaves_normal_chat_available(self):
        with patch.object(menu, "KeyReader") as reader, patch.object(catalog, "load", side_effect=OSError("offline")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            reader.return_value.__enter__.return_value.read.side_effect = ["space", "end", "enter"]
            self.assertEqual(menu.main_menu(TerminalUI("fr")), (None, None, "fr", "chat"))
        self.assertIn(TEXT["fr"]["catalog_error"], output.getvalue())

    def test_quit_escape_and_interrupt_do_not_connect(self):
        for event in ("quit", "back", KeyboardInterrupt):
            with self.subTest(event=event), patch("sys.argv", ["preptalk"]), \
                    patch.object(menu, "KeyReader") as reader, patch.object(client, "post") as post, \
                    contextlib.redirect_stdout(io.StringIO()):
                reader.return_value.__enter__.return_value.read.side_effect = [event]
                client.main()
                post.assert_not_called()
        reader.return_value.__exit__.assert_called_once()

    def test_no_menu_keeps_direct_cli_usage(self):
        with patch("sys.argv", ["preptalk", "--no-menu", "--posting", "P-01", "--lang", "fr"]), \
                patch("builtins.input", side_effect=["Bonjour", ""]), \
                patch.object(client, "post", side_effect=[{"thread_id": "test"}, {}]) as post, \
                patch.object(catalog, "load") as load, contextlib.redirect_stdout(io.StringIO()) as output:
            client.main()
        load.assert_not_called()
        self.assertNotIn(TEXT["fr"]["main_menu"], output.getvalue())
        self.assertEqual(post.call_args_list[1].args[1]["input"]["posting_id"], "P-01")


class CatalogTest(unittest.TestCase):
    def tearDown(self):
        catalog.load.cache_clear()

    def test_local_data_needs_no_download(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(catalog, "DATA", Path(directory)), \
                patch.object(catalog.urllib.request, "urlopen") as fetch:
            path = Path(directory) / "profiles/postings.jsonl"
            path.parent.mkdir()
            path.write_text('{"id":"P-01"}\n', encoding="utf-8")
            self.assertEqual(catalog.read_records("profiles/postings.jsonl"), [{"id": "P-01"}])
            fetch.assert_not_called()

    def test_remote_catalog_is_pinned_and_cached(self):
        catalog.load.cache_clear()
        with tempfile.TemporaryDirectory() as directory, patch.object(catalog, "DATA", Path(directory)), \
                patch.object(catalog.urllib.request, "urlopen") as fetch:
            fetch.return_value.__enter__.return_value.read.side_effect = [b'{"id":"P-01"}', b'{"id":"S-01"}']
            self.assertIn("S-01", catalog.load()["scenario"])
            catalog.load()
            self.assertEqual(fetch.call_count, 2)
            for call in fetch.call_args_list:
                self.assertIn(catalog.FHGR_COMMIT, call.args[0])


if __name__ == "__main__":
    unittest.main()
