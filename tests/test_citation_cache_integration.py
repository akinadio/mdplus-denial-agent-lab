"""Integration tests for wiring the citation cache into the live prompt flow.

citation_cache.py itself is covered by test_citation_cache.py. These tests
cover the plumbing around it: a cache hit written to an episode's directory
by server.py must reach prepare_arm()'s work_order, and from there into the
text both prompt builders (the API/claude engine's claude_prompt() and the
codex/CLI engine's agent_prompt()) actually send to the model -- always
framed as something to verify, never as a ready-made answer.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from synthetic_harness import citation_cache as cc
from synthetic_harness.agent_runner import claude_prompt
from synthetic_harness.arms import known_citation_hint, known_citation_hint_block
from synthetic_harness.episode import Episode

SAMPLE_HIT = {
    "payer_key": "aetna",
    "payer_display": "Aetna",
    "state": "TX",
    "cpt": ["27447"],
    "selected_source_title": "Aetna CPB 0660",
    "selected_source_url": "https://www.aetna.com/cpb/medical/data/600_699/0660.html",
    "confidence_overall": "medium",
    "human_reviewed": False,
}


class KnownCitationHintTests(unittest.TestCase):
    def test_missing_hint_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            episode = Episode.create(Path(tmp))
            self.assertIsNone(known_citation_hint(episode))

    def test_hint_file_present_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            episode = Episode.create(Path(tmp))
            hint_path = episode.root / "system" / "known_citation_hint.json"
            hint_path.parent.mkdir(parents=True, exist_ok=True)
            hint_path.write_text(json.dumps(SAMPLE_HIT), encoding="utf-8")
            hint = known_citation_hint(episode)
            self.assertIsNotNone(hint)
            self.assertEqual(hint["selected_source_title"], "Aetna CPB 0660")

    def test_corrupt_hint_file_misses_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            episode = Episode.create(Path(tmp))
            hint_path = episode.root / "system" / "known_citation_hint.json"
            hint_path.parent.mkdir(parents=True, exist_ok=True)
            hint_path.write_text("not json", encoding="utf-8")
            self.assertIsNone(known_citation_hint(episode))


class KnownCitationHintBlockTests(unittest.TestCase):
    def test_no_hint_renders_empty(self):
        self.assertEqual(known_citation_hint_block(None), "")

    def test_hint_renders_verify_first_language(self):
        block = known_citation_hint_block(SAMPLE_HIT)
        self.assertIn("KNOWN PRIOR CITATION", block)
        self.assertIn("verify before use, do not assume", block)
        self.assertIn(SAMPLE_HIT["selected_source_title"], block)
        self.assertIn(SAMPLE_HIT["selected_source_url"], block)
        # It must instruct the agent to check the document still applies --
        # never to accept it as a substitute for retrieval.
        self.assertIn("Confirm it is still", block)
        self.assertIn("disregard it and retrieve fresh evidence", block)

    def test_no_verdict_renders_no_verdict_line(self):
        block = known_citation_hint_block(SAMPLE_HIT)
        self.assertNotIn("Our own verification", block)

    def test_verified_verdict_is_stated_without_a_warning(self):
        hit = dict(SAMPLE_HIT, ledger_verdict="verified", ledger_note="Real criteria; KL grade 3-4.")
        block = known_citation_hint_block(hit)
        self.assertIn("Our own verification of this document for this CPT: verified", block)
        self.assertIn("Real criteria; KL grade 3-4.", block)
        self.assertNotIn("IMPORTANT", block)

    def test_non_verified_verdict_warns_before_the_round_trip_is_spent(self):
        """The UnitedHealthcare case: a real, current document whose criteria
        live in InterQual. The agent has to be told that up front, or it
        fetches the PDF and finds nothing to quote."""
        hit = dict(
            SAMPLE_HIT,
            ledger_verdict="criteria_proprietary_not_public",
            ledger_note="TKA criteria outsourced to InterQual.",
        )
        block = known_citation_hint_block(hit)
        self.assertIn("criteria_proprietary_not_public", block)
        self.assertIn("IMPORTANT", block)
        self.assertIn("NOT yield usable medical-necessity criteria", block)
        self.assertIn("InterQual", block)


class ClaudePromptCitationHintTests(unittest.TestCase):
    """claude_prompt() is what the sustainable API engine (run_api_arm) and
    the legacy claude-CLI engine (run_claude_arm) both actually send to the
    model, so this is the path that matters most for the live product."""

    def _work_order(self, **overrides):
        work_order = {
            "episode_id": "ep_test",
            "case_id": "case_test",
            "arm": "web_only",
            "objective": "test objective",
            "patient_visible_transcript": [],
            "result_schema": {"type": "object"},
        }
        work_order.update(overrides)
        return work_order

    def test_prompt_without_hint_omits_section(self):
        prompt = claude_prompt(self._work_order())
        self.assertNotIn("KNOWN PRIOR CITATION", prompt)

    def test_prompt_with_hint_includes_section(self):
        prompt = claude_prompt(self._work_order(known_citation_hint=SAMPLE_HIT))
        self.assertIn("KNOWN PRIOR CITATION", prompt)
        self.assertIn(SAMPLE_HIT["selected_source_title"], prompt)
        self.assertIn("verify before use, do not assume", prompt)


if __name__ == "__main__":
    unittest.main()
