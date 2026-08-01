#!/usr/bin/env python3
"""Create a backup of the episode store + SQLite state, and prune old ones.

  python3 scripts/backup.py                 # write a backup, keep the newest N
  MDPLUS_BACKUP_DIR=/backups python3 scripts/backup.py

Schedule it (deploy/mdplus-backup.timer) so backups happen without a human.
Backups contain PHI — put MDPLUS_BACKUP_DIR on encrypted, access-controlled
storage and apply the same retention as the live data.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from synthetic_harness import backup  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    episodes_root = Path(
        os.environ.get(
            "MDPLUS_EPISODES_ROOT",
            ROOT / "outputs" / "synthetic_patient_simulations" / "episodes",
        )
    ).expanduser()
    db_path = Path(
        os.environ.get("MDPLUS_DB_PATH", ROOT / "outputs" / "state.sqlite3")
    ).expanduser()
    backup_dir = Path(
        os.environ.get("MDPLUS_BACKUP_DIR", ROOT / "backups")
    ).expanduser()
    keep = int(os.environ.get("MDPLUS_BACKUP_KEEP", "14"))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = backup.make_backup(episodes_root, db_path, backup_dir, stamp)
    size_mb = archive.stat().st_size / 1_000_000
    print(f"Wrote {archive} ({size_mb:.1f} MB)")
    removed = backup.prune(backup_dir, keep)
    if removed:
        print(f"Pruned {len(removed)} old backup(s), keeping newest {keep}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
