"""Tests for the retention sweep and targeted deletion."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from synthetic_harness import retention, store


def _make_episode(root: Path, episode_id: str, created: datetime) -> Path:
    d = root / episode_id
    (d / "system").mkdir(parents=True)
    (d / "manifest.json").write_text(
        json.dumps({"episode_id": episode_id, "created_at":
                    created.isoformat().replace("+00:00", "Z")}),
        encoding="utf-8",
    )
    (d / "system" / "note.txt").write_text("data", encoding="utf-8")
    return d


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        _make_episode(self.root, "ep_000000000001", self.now - timedelta(days=40))
        _make_episode(self.root, "ep_000000000002", self.now - timedelta(days=10))
        store.init(self.root / "state.sqlite3")

    def tearDown(self):
        self._tmp.cleanup()

    def test_find_expired_respects_window(self):
        expired = retention.find_expired(self.root, days=30, now=self.now)
        self.assertEqual([d.name for d in expired], ["ep_000000000001"])

    def test_days_zero_disables(self):
        self.assertEqual(retention.find_expired(self.root, days=0, now=self.now), [])

    def test_dry_run_does_not_delete(self):
        ids = retention.purge_expired(self.root, days=30, apply=False, now=self.now)
        self.assertEqual(ids, ["ep_000000000001"])
        self.assertTrue((self.root / "ep_000000000001").exists())  # still there

    def test_apply_deletes_dir_and_index(self):
        store.upsert_episode("ep_000000000001", payer="Aetna")
        ids = retention.purge_expired(self.root, days=30, apply=True, now=self.now)
        self.assertEqual(ids, ["ep_000000000001"])
        self.assertFalse((self.root / "ep_000000000001").exists())
        self.assertTrue((self.root / "ep_000000000002").exists())  # newer kept
        self.assertEqual(store.list_episodes(), [])  # index row removed

    def test_delete_specific_episode(self):
        self.assertTrue(retention.delete_episode(self.root, "ep_000000000002"))
        self.assertFalse((self.root / "ep_000000000002").exists())
        # Deleting a missing one is a no-op returning False.
        self.assertFalse(retention.delete_episode(self.root, "ep_000000000099"))


if __name__ == "__main__":
    unittest.main()
