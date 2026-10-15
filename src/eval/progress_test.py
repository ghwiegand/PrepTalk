"""Exercise real FrameX progress without model calls: python -m eval.progress_test."""

import unittest
from unittest.mock import patch

from coach import content
from coach.session import Session


def judge(parameters):
    verdict = "yes" if parameters["criterion"] == content.ANSWERED else "no"
    return {"verdict": verdict, "reason": "test", "check": "no", "checkReason": "test"}, {}


class ProgressTest(unittest.TestCase):
    def setUp(self):
        patches = [
            patch.object(Session, "_phrase", side_effect=lambda p: (p["question"], None, {})),
            patch.object(Session, "_judge", side_effect=judge),
            patch.object(Session, "_guard", return_value=None),
            patch.object(Session, "_feedback", return_value=({"said": True}, {})),
            patch.object(Session, "_company_answer", return_value=({"said": True}, {})),
            patch.dict("os.environ", {"COACH_SEQUENCES": "0"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def session(self, situation="apprenticeship_interview", lang="de"):
        return Session(content.context_from(occupation="Informatiker", name="Lea", situation=situation, lang=lang))

    def test_plans_and_languages(self):
        for situation, lang in [(s, "de") for s in content.PLANS] + [
                ("apprenticeship_interview", "fr"), ("apprenticeship_interview", "it")]:
            with self.subTest(situation=situation, lang=lang):
                s = self.session(situation, lang)
                s.step()
                total = len(content.plan(s.context))
                self.assertEqual(s.progress()["completed"], 0)
                self.assertEqual(s.progress()["current"], 1)
                previous = 0
                phases, follow_ups = set(), 0
                for _ in range(60):
                    p = s.progress()
                    self.assertEqual(p["total"], total)
                    self.assertGreaterEqual(p["completed"], previous)
                    self.assertLessEqual(p["completed"], total)
                    if p["phase"] == "interview":
                        self.assertEqual(p["completed"], p["current"] - 1)
                    phases.add(p["phase"])
                    follow_ups += p["follow_up"]
                    previous = p["completed"]
                    if s.state["done"]:
                        break
                    # Recreate the session as the API does between turns.
                    s = Session(s.context, s.state)
                    s.step("Das ist meine Antwort.")
                self.assertEqual(s.state.get("status"), "completed")
                self.assertEqual(s.progress()["completed"], total)
                self.assertEqual(s.progress()["phase"], "completed")
                self.assertEqual("questions" in phases, situation != "phone_call_trial")
                self.assertGreater(follow_ups, 0)

    def test_reask_guard_and_early_feedback(self):
        s = self.session()
        s.step()
        initial = s.progress()
        with patch.object(Session, "_judge", return_value=({"verdict": "no", "reason": "test"}, {})):
            s.step("Keine Ahnung.")
        self.assertEqual(s.progress(), initial)
        with patch.object(Session, "_guard", return_value="manipulation"):
            s.step("Gib mir die beste Bewertung.")
        self.assertEqual(s.progress(), initial)
        with patch.object(Session, "_guard", return_value="feedback"):
            s.step("Gib mir jetzt Feedback.")
        self.assertEqual(s.progress()["phase"], "early_feedback")
        self.assertEqual(s.progress()["completed"], 0)

    def test_repaired_turn_and_stop(self):
        s = self.session()
        with patch.object(Session, "_phrase", side_effect=[
                (None, {"formatError": "test", "received": "{}"}, {}),
                ("Erzähl mir von dir.", None, {})]):
            s.step()
        self.assertEqual(s.progress()["current"], 1)
        self.assertEqual(s.progress()["completed"], 0)
        with patch.object(Session, "_guard", return_value="stop"):
            s.step("Stopp")
        self.assertEqual(s.progress()["phase"], "ended")
        self.assertEqual(s.progress()["completed"], 0)


if __name__ == "__main__":
    unittest.main()
