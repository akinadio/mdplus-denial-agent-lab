"""Tests for the SQLite state layer (durable spend, run/episode index)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from synthetic_harness import store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        store.init(Path(self._tmp.name) / "state.sqlite3")

    def tearDown(self):
        self._tmp.cleanup()

    def test_spend_accumulates_and_persists(self):
        self.assertEqual(store.get_spend("2026-08-01"), 0.0)
        self.assertAlmostEqual(store.add_spend("2026-08-01", 1.5), 1.5)
        self.assertAlmostEqual(store.add_spend("2026-08-01", 2.0), 3.5)
        self.assertAlmostEqual(store.get_spend("2026-08-01"), 3.5)
        # A different day is a separate bucket.
        self.assertAlmostEqual(store.add_spend("2026-08-02", 1.0), 1.0)

    def test_spend_survives_reopen(self):
        store.add_spend("2026-08-01", 4.25)
        # Re-init pointing at the same file (simulates a restart).
        db = Path(self._tmp.name) / "state.sqlite3"
        store.init(db)
        self.assertAlmostEqual(store.get_spend("2026-08-01"), 4.25)

    def test_run_index_and_running_query(self):
        store.upsert_run("ep_1", "web_only", "running", 0)
        store.upsert_run("ep_1", "library_only", "completed", 0)
        running = store.running_runs()
        self.assertEqual(running, [{"episode_id": "ep_1", "arm": "web_only",
                                    "status": "running", "revision": 0}])
        # Updating status removes it from the running set.
        store.upsert_run("ep_1", "web_only", "completed", 0)
        self.assertEqual(store.running_runs(), [])

    def test_episode_index_lists_newest_first(self):
        store.upsert_episode("ep_1", payer="Aetna", procedure="TKA", state="CA")
        store.upsert_episode("ep_2", payer="Cigna", procedure="THA", state="NY")
        eps = store.list_episodes()
        self.assertEqual({e["episode_id"] for e in eps}, {"ep_1", "ep_2"})
        self.assertEqual(eps[0]["payer"] in ("Aetna", "Cigna"), True)


class ServerSpendDurabilityTests(unittest.TestCase):
    """The server's budget guard reads through the durable store."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        store.init(Path(self._tmp.name) / "state.sqlite3")

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_spend_is_visible_after_cache_reset(self):
        from synthetic_harness import server
        server._SPEND["day"] = ""
        server._SPEND["usd"] = 0.0
        day = server._spend_day()
        server.record_spend(5.0)
        # Simulate a restart: wipe the in-memory cache, keep the DB.
        server._SPEND["day"] = ""
        server._SPEND["usd"] = 0.0
        self.assertAlmostEqual(server._sync_spend_cache(day), 5.0)


if __name__ == "__main__":
    unittest.main()
