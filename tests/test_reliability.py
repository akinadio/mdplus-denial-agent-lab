"""Tests for unattended-operation support: crash recovery + health."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synthetic_harness.reliability import build_health, reconcile_interrupted_runs


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_status(self, episode: str, arm: str, status: str) -> Path:
        arm_dir = self.root / episode / "system" / arm
        arm_dir.mkdir(parents=True, exist_ok=True)
        path = arm_dir / "runtime_status.json"
        path.write_text(json.dumps({"status": status}), encoding="utf-8")
        return path

    def test_running_becomes_interrupted(self):
        p = self._write_status("ep_000000000001", "web_only", "running")
        done = self._write_status("ep_000000000001", "library_only", "completed")
        reconciled = reconcile_interrupted_runs(self.root)
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(reconciled[0], {"episode_id": "ep_000000000001", "arm": "web_only"})
        after = json.loads(p.read_text())
        self.assertEqual(after["status"], "interrupted")
        self.assertTrue(after["interrupted"])
        self.assertIn("error", after)
        # A completed arm is left untouched.
        self.assertEqual(json.loads(done.read_text())["status"], "completed")

    def test_no_episodes_is_safe(self):
        self.assertEqual(reconcile_interrupted_runs(self.root / "missing"), [])

    def test_corrupt_status_is_skipped(self):
        arm_dir = self.root / "ep_000000000002" / "system" / "web_only"
        arm_dir.mkdir(parents=True, exist_ok=True)
        (arm_dir / "runtime_status.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(reconcile_interrupted_runs(self.root), [])


class HealthTests(unittest.TestCase):
    def _health(self, **over):
        base = dict(
            episodes_root=Path("/nonexistent-for-test"),
            engine="api",
            build_id="abc123",
            started_at="2026-07-31T00:00:00Z",
            ui_built=True,
            max_concurrent_arms=4,
            active_arms=1,
            spend={"day": "2026-07-31", "usd": 2.5},
            daily_budget_usd=50.0,
            budget_paused=False,
        )
        base.update(over)
        return build_health(**base)

    def test_healthy_when_everything_present(self):
        with patch.dict(os.environ, {"WEB_SEARCH_API_KEY": "x", "ANTHROPIC_API_KEY": "y"}):
            h = self._health()
        self.assertTrue(h["ok"])
        self.assertFalse(h["degraded"])
        self.assertEqual(h["concurrency"]["available_slots"], 3)
        self.assertEqual(h["spend"]["estimated_usd"], 2.5)

    def test_degraded_lists_reasons(self):
        with patch.dict(os.environ, {}, clear=True):
            h = self._health(ui_built=False)
        self.assertFalse(h["ok"])
        self.assertTrue(h["degraded"])
        joined = " ".join(h["degraded_reasons"])
        self.assertIn("UI build missing", joined)
        self.assertIn("WEB_SEARCH_API_KEY", joined)
        self.assertIn("ANTHROPIC_API_KEY", joined)

    def test_budget_paused_is_degraded(self):
        with patch.dict(os.environ, {"WEB_SEARCH_API_KEY": "x", "ANTHROPIC_API_KEY": "y"}):
            h = self._health(budget_paused=True)
        self.assertTrue(h["degraded"])
        self.assertTrue(h["spend"]["paused"])


if __name__ == "__main__":
    unittest.main()
