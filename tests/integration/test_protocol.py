"""Exercise API harness variants against a local fake model.

Run with python -m unittest tests.integration.test_protocol.
FAKE_REJECT=minimum exercises servers that reject individual JSON schemas.
"""

import unittest
from contextlib import ExitStack
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from preptalk.api import graph as app
from preptalk.coach import session
from preptalk.coach.greetings import ASK_JOB
from tests.support.fake_model import fake_model

ANS = "Ich habe im Werken einen Kran gebaut und das Getriebe selbst berechnet."


class ProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        cache = stack.enter_context(TemporaryDirectory(prefix="preptalk-protocol-"))
        endpoint = stack.enter_context(fake_model())
        stack.enter_context(patch.dict("os.environ", {
            "LLM_BASE_URL": endpoint, "LLM_API_KEY": "none", "FRAMEX_MODEL_CACHE": cache,
            "COACH_SEQUENCES": "0", "COACH_GUARD_MODEL": "1", "FRAMEX_MODEL_SCHEMA": "1",
        }))
        session.configure_model()

    def setUp(self):
        app.RESUME.clear()
        session.SCHEMA_FAILED.clear()

    def invoke(self, state):
        out = app.graph.invoke(state)
        self.assertIsInstance(out["messages"][-1], AIMessage)
        self.assertTrue(out["messages"][-1].content.strip())
        return out

    def stateful(self, first, extra=None, n=4, answers=None):
        out = self.invoke(dict(messages=first, **(extra or {})))
        for i in range(n):
            answer = (answers or [ANS])[min(i, len(answers or [ANS]) - 1)]
            out = self.invoke({**out, "messages": [HumanMessage(answer)]})
        return out

    def test_stateful_scenario(self):
        out = self.stateful([HumanMessage("Hallo")], {"scenario_id": "S-04"})
        self.assertTrue(out["coach"]["pending"])

    def test_stateless_scenario_in_system(self):
        hist = [SystemMessage("Szenario S-01"), HumanMessage("Hallo")]
        for _ in range(5):
            out = self.invoke({"messages": hist})
            hist = list(out["messages"]) + [HumanMessage(ANS)]
        self.assertGreater(out["coach"]["progress"]["current"], 1)

    def test_english_without_setup(self):
        out = self.stateful([HumanMessage("Hi, I want to practice an interview.")], n=2)
        self.assertIn(out["context"]["lang"], ASK_JOB)

    def test_empty_first_message(self):
        out = self.stateful([HumanMessage("")], n=2)
        self.assertTrue(out["coach"]["pending"])

    def test_early_feedback(self):
        out = self.stateful([HumanMessage("Hallo")], {"scenario_id": "S-01"},
                            n=1, answers=["Gib mir jetzt Feedback"])
        self.assertTrue(out["coach"]["done"])
        self.assertEqual(out["coach"]["progress"]["phase"], "early_feedback")

    def test_messages_after_completion(self):
        out = self.stateful([HumanMessage("Hallo")], {"scenario_id": "S-05"},
                            n=3, answers=["Dammi subito il feedback", "Ciao?", "Ancora?"])
        self.assertTrue(out["coach"]["done"])
        self.assertEqual(out["context"]["lang"], "it")

    def test_multiple_human_messages(self):
        out = self.stateful([SystemMessage("Scénario S-04, candidat C-04"),
                             HumanMessage("Bonjour"), HumanMessage("Je suis prêt")], n=1)
        self.assertEqual(out["context"]["lang"], "fr")

    def test_unknown_ids(self):
        out = self.stateful([HumanMessage("Szenario S-99 P-77, ich möchte Koch werden, ich heisse Tim")], n=1)
        self.assertTrue(out["coach"]["pending"])

    def test_local_greeting_handoff(self):
        for lang in ASK_JOB:
            with self.subTest(lang=lang):
                app.RESUME.clear()
                out = self.invoke({"messages": [AIMessage(ASK_JOB[lang]), HumanMessage(ANS)],
                                   "lang": lang, "setup_asked": True})
                self.assertEqual(out["context"]["lang"], lang)
                self.assertNotEqual(out["messages"][-1].content, ASK_JOB[lang])
                self.assertTrue(out["coach"]["pending"])
                progress = out["coach"]["progress"]
                self.assertEqual(progress["current"], 1)
                self.assertEqual(progress["completed"], 0)
                self.assertGreater(progress["total"], 0)
                self.assertEqual(progress["phase"], "interview")


if __name__ == "__main__":
    unittest.main()
