"""Data retention: find and purge episodes past their retention window.

The Privacy Notice promises we keep patient information only for a limited period
and can delete it on request. This module implements both:

- `find_expired` / `purge_expired` — for a scheduled retention sweep (see
  scripts/purge_expired.py), deleting whole episode directories older than the
  configured number of days.
- `delete_episode` — a targeted delete for a specific episode (a deletion
  request), wired to an admin endpoint in the server.

Deletion removes the on-disk episode directory and its rows in the SQLite index.
It is irreversible, so the sweep defaults to a dry run and only deletes with an
explicit apply flag.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import store


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def episode_created(root: Path) -> datetime | None:
    """When the episode was created: manifest timestamp, else directory mtime."""
    manifest = root / "manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            parsed = _parse_ts(data.get("created_at"))
            if parsed:
                return parsed
        except (json.JSONDecodeError, OSError):
            pass
    try:
        return datetime.fromtimestamp(root.stat().st_mtime, timezone.utc)
    except OSError:
        return None


def find_expired(
    episodes_root: Path, days: int, now: datetime | None = None
) -> list[Path]:
    """Episode directories older than `days`. Returns [] when days <= 0."""
    if days <= 0 or not episodes_root.exists():
        return []
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    expired = []
    for d in sorted(episodes_root.glob("ep_*")):
        if not d.is_dir():
            continue
        created = episode_created(d)
        if created and created < cutoff:
            expired.append(d)
    return expired


def delete_episode(episodes_root: Path, episode_id: str) -> bool:
    """Purge one episode (directory + index rows). Returns True if it existed."""
    root = episodes_root / episode_id
    existed = root.is_dir()
    if existed:
        shutil.rmtree(root, ignore_errors=True)
    store.delete_episode(episode_id)
    return existed


def purge_expired(
    episodes_root: Path, days: int, apply: bool = False, now: datetime | None = None
) -> list[str]:
    """Find expired episodes and, when apply=True, delete them.

    Returns the list of episode ids that were (or would be) purged.
    """
    expired = find_expired(episodes_root, days, now=now)
    ids = [d.name for d in expired]
    if apply:
        for episode_id in ids:
            delete_episode(episodes_root, episode_id)
    return ids
