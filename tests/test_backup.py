"""Tests for backup creation, DB consistency, and pruning."""

from __future__ import annotations

import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

from synthetic_harness import backup


class BackupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.episodes = self.base / "episodes"
        (self.episodes / "ep_1" / "system").mkdir(parents=True)
        (self.episodes / "ep_1" / "manifest.json").write_text("{}", encoding="utf-8")
        self.db = self.base / "state.sqlite3"
        con = sqlite3.connect(str(self.db))
        con.execute("CREATE TABLE t(x)")
        con.execute("INSERT INTO t VALUES (42)")
        con.commit()
        con.close()
        self.backup_dir = self.base / "backups"

    def tearDown(self):
        self._tmp.cleanup()

    def test_archive_contains_episodes_and_db(self):
        archive = backup.make_backup(self.episodes, self.db, self.backup_dir, "20260801T000000Z")
        self.assertTrue(archive.exists())
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
        self.assertIn("state.sqlite3", names)
        self.assertTrue(any(n.startswith("episodes") for n in names))

    def test_db_copy_is_readable(self):
        archive = backup.make_backup(self.episodes, self.db, self.backup_dir, "20260801T000001Z")
        with tempfile.TemporaryDirectory() as out:
            with tarfile.open(archive, "r:gz") as tar:
                tar.extract("state.sqlite3", out)
            con = sqlite3.connect(str(Path(out) / "state.sqlite3"))
            self.assertEqual(con.execute("SELECT x FROM t").fetchone()[0], 42)
            con.close()

    def test_missing_db_is_tolerated(self):
        archive = backup.make_backup(self.episodes, self.base / "nope.sqlite3", self.backup_dir, "20260801T000002Z")
        with tarfile.open(archive, "r:gz") as tar:
            self.assertNotIn("state.sqlite3", tar.getnames())

    def test_prune_keeps_newest(self):
        for stamp in ("20260801T000000Z", "20260802T000000Z", "20260803T000000Z"):
            backup.make_backup(self.episodes, self.db, self.backup_dir, stamp)
        removed = backup.prune(self.backup_dir, keep=2)
        self.assertEqual(len(removed), 1)
        remaining = sorted(p.name for p in self.backup_dir.glob("mdplus-backup-*.tar.gz"))
        self.assertEqual(remaining, [
            "mdplus-backup-20260802T000000Z.tar.gz",
            "mdplus-backup-20260803T000000Z.tar.gz",
        ])


if __name__ == "__main__":
    unittest.main()
