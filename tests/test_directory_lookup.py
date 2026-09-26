"""The live site answers the policy question and writes the letter exactly the
way the study's OrthoAppeals arm did."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "study"))

from synthetic_harness import directory_lookup as dl  # noqa: E402
from synthetic_harness import server  # noqa: E402
from synthetic_harness.episode import Episode  # noqa: E402

CASES = json.loads((ROOT / "study" / "cases.json").read_text())["cases"]


def _drop(d, *keys):
    return {k: v for k, v in d.items() if k not in keys}


class SameAsStudy(unittest.TestCase):
    """Every one of the 167 study cases, run through the live entry point."""

    def test_policy_answer_matches_the_study_for_every_case(self):
        import retrieve
        for c in CASES:
            live = dl.live_answer(c["payer"], c["state"], c["cpt"], c["letter_text"], "claude-opus-5")
            self.assertIsNotNone(live, c["case_id"])
            study = retrieve.run_ortho(c, "claude-opus-5")
            self.assertEqual(live["source"], study["source"], c["case_id"])
            # The deadline is read off the notice live and off the case record in
            # the study; everything else must be identical.
            self.assertEqual(_drop(live["answer"], "appeal_deadline"),
                             _drop(study["answer"], "appeal_deadline"), c["case_id"])
            self.assertEqual(live["denial_reason"], c["denial_reason"], c["case_id"])

    def test_letter_input_matches_the_study_for_every_case(self):
        import draft_letters
        for c in CASES:
            live = dl.live_answer(c["payer"], c["state"], c["cpt"], c["letter_text"], "claude-opus-5")
            study = draft_letters._ortho_result(c, live["answer"])
            self.assertEqual(dl.letter_input_live(live, c["letter_text"]), study, c["case_id"])


class Coverage(unittest.TestCase):
    def test_untested_status_and_missing_row_fall_back_to_search(self):
        import csv
        rows = list(csv.DictReader(dl.DIRECTORY.open(encoding="utf-8")))
        unreachable = next(r for r in rows if r["status"].startswith("UNREACHABLE"))
        self.assertIsNone(dl.live_answer(unreachable["insurance_company"], unreachable["state"],
                                         unreachable["cpt"], ""))
        self.assertIsNone(dl.live_answer("No Such Insurer", "Ohio", "27447", ""))

    def test_loose_spelling_finds_the_same_row(self):
        c = CASES[0]
        a = dl.directory_row(c["payer"], c["state"], c["cpt"])
        b = dl.directory_row("  " + c["payer"].upper() + " ", c["state"].lower(), "CPT " + c["cpt"])
        self.assertEqual(a, b)


class Overlay(unittest.TestCase):
    def _d(self, stratum):
        c = next(c for c in CASES if c["stratum"] == stratum)
        return dl.live_answer(c["payer"], c["state"], c["cpt"], c["letter_text"])

    def test_directory_policy_replaces_the_agents_and_keeps_it(self):
        d = self._d("in_library")
        agent = {"retrieval": {"selected_source": {"title": "Something else", "url": "https://x"},
                               "citations": [{"excerpt": "made up"}]}}
        out = dl.apply_to_result(agent, d)
        self.assertEqual(out["retrieval"]["selected_source"]["url"], d["answer"]["policy_url"])
        self.assertEqual(out["retrieval"]["agent_selected_source"]["url"], "https://x")
        self.assertTrue(out["retrieval"]["citations"])
        self.assertEqual(agent["retrieval"]["selected_source"]["url"], "https://x")  # not mutated

    def test_no_policy_case_names_no_policy_and_still_gets_a_letter(self):
        d = self._d("no_policy")
        out = dl.apply_to_result({"retrieval": {"selected_source": {"title": "Invented", "url": "https://y"}}}, d)
        self.assertEqual(out["retrieval"]["selected_source"], {})
        self.assertTrue(dl.assessment(d, "")["recommended"])

    def test_benefit_exclusion_is_not_sent_a_criteria_letter(self):
        d = self._d("in_library")
        self.assertFalse(dl.assessment(d, "This service is a benefit exclusion under your plan.")["recommended"])

    def test_agent_is_told_the_directory_policy(self):
        d = self._d("in_library")
        self.assertIn(d["answer"]["policy_url"], dl.agent_block(d))
        self.assertIn("Do not name any document", dl.agent_block(self._d("no_policy")))


class LiveEndpoint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.episode = Episode.create(Path(self._tmp.name))
        self.case = next(c for c in CASES if c["stratum"] == "in_library")
        data = {"denial_letter": self.case["letter_text"], "payer": self.case["payer"],
                "state": self.case["state"], "cpt": self.case["cpt"]}
        req = self.episode.create_message(sender="orchestrator", recipient="patient_actor",
                                          body="start", message_type="episode_start")
        self.episode.create_message(sender="patient_actor", recipient="orchestrator",
                                    body=server.submission_text(data), message_type="patient_response",
                                    in_reply_to=req["message_id"])
        server._write_directory_answer(self.episode, data)
        arm_dir = self.episode.root / "system" / "web_only"
        arm_dir.mkdir(parents=True, exist_ok=True)
        (arm_dir / "result.json").write_text(json.dumps({"retrieval": {
            "selected_source": {"title": "Agent pick", "url": "https://agent.example"}}}))

    def tearDown(self):
        self._tmp.cleanup()

    def test_letter_is_written_from_the_study_input(self):
        import draft_letters
        seen = []

        def fake(result, patient_submission=None, sender="provider"):
            seen.append(result)
            return {"letter_markdown": "RE: Appeal", "model": "test", "sender": sender,
                    "usage": {}, "estimated_cost_usd": 0.0}

        with patch.object(server, "generate_appeal_letter", side_effect=fake), \
             patch.object(server, "budget_exceeded", return_value=False):
            out = server.generate_and_store_appeal_letter(self.episode, "web_only")
        self.assertTrue(out["assessment"]["recommended"])
        d = server.directory_answer(self.episode)
        # Intake trims surrounding whitespace off the pasted notice; otherwise the
        # live input is the study's, character for character.
        case = dict(self.case, letter_text=self.case["letter_text"].strip())
        expected = draft_letters._ortho_result(case, d["answer"])
        self.assertEqual(seen[0], expected)

    def test_snapshot_shows_the_directory_policy(self):
        snap = server.episode_snapshot(self.episode)
        src = snap["arms"]["web_only"]["result"]["retrieval"]["selected_source"]
        self.assertEqual(src["url"], server.directory_answer(self.episode)["answer"]["policy_url"])


if __name__ == "__main__":
    unittest.main()
