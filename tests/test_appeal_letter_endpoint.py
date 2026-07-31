"""Integration test for the server glue that stores an appeal letter."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synthetic_harness import server
from synthetic_harness.episode import Episode
from tests.test_appeal_letter import _grounded_result


class AppealLetterEndpointTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.episode = Episode.create(Path(self._tmp.name))
        arm_dir = self.episode.root / "system" / "web_only"
        arm_dir.mkdir(parents=True, exist_ok=True)
        (arm_dir / "result.json").write_text(
            json.dumps(_grounded_result()), encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_recommended_letter_is_drafted_and_stored(self):
        fake = {
            "letter_markdown": "RE: Appeal\n\nYour plan's own policy states...",
            "model": "test", "usage": {"input_tokens": 100, "output_tokens": 100},
            "estimated_cost_usd": 0.02,
        }
        with patch.object(server, "generate_appeal_letter", return_value=fake), \
             patch.object(server, "budget_exceeded", return_value=False):
            out = server.generate_and_store_appeal_letter(self.episode, "web_only")
        self.assertTrue(out["assessment"]["recommended"])
        self.assertIn("letter", out)
        stored = self.episode.root / "system" / "web_only" / "appeal_letter.md"
        self.assertTrue(stored.exists())
        self.assertIn("Your plan's own policy", stored.read_text())
        self.assertTrue((self.episode.root / "system" / "web_only" / "appeal_letter_meta.json").exists())

    def test_not_recommended_skips_generation(self):
        blocked = _grounded_result(status="blocked")
        (self.episode.root / "system" / "web_only" / "result.json").write_text(
            json.dumps(blocked), encoding="utf-8"
        )
        with patch.object(server, "generate_appeal_letter") as gen:
            out = server.generate_and_store_appeal_letter(self.episode, "web_only")
        self.assertFalse(out["assessment"]["recommended"])
        self.assertNotIn("letter", out)
        gen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
