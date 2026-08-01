"""Consistent backups of the episode store and the SQLite state.

For a service meant to run unmonitored for months, a lost disk should not mean
lost patient records. This makes a timestamped tar.gz containing:
  - the episodes directory (atomically-written files, safe to archive live), and
  - a consistent copy of the SQLite database taken via the online-backup API
    (never a raw file copy, which can catch a half-written page).

Backups hold PHI, so store them somewhere with the same protections as the live
data (encrypted, access-controlled), and apply the same retention.
"""

from __future__ import annotations

import sqlite3
import tarfile
import tempfile
from pathlib import Path


def backup_sqlite(db_path: Path, dest: Path) -> bool:
    """Copy the DB consistently via the online-backup API. False if no DB yet."""
    if not db_path.exists():
        return False
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return True


def make_backup(
    episodes_root: Path, db_path: Path, backup_dir: Path, stamp: str
) -> Path:
    """Write one backup archive named with `stamp`; returns its path."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    archive = backup_dir / f"mdplus-backup-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "state.sqlite3"
        have_db = backup_sqlite(db_path, db_copy)
        with tarfile.open(archive, "w:gz") as tar:
            if episodes_root.exists():
                tar.add(episodes_root, arcname="episodes")
            if have_db:
                tar.add(db_copy, arcname="state.sqlite3")
    return archive


def prune(backup_dir: Path, keep: int) -> list[Path]:
    """Keep the newest `keep` archives; delete the rest. Returns removed paths."""
    if keep <= 0 or not backup_dir.exists():
        return []
    archives = sorted(
        backup_dir.glob("mdplus-backup-*.tar.gz"),
        key=lambda p: p.name,
        reverse=True,
    )
    removed = []
    for old in archives[keep:]:
        try:
            old.unlink()
            removed.append(old)
        except OSError:
            pass
    return removed
