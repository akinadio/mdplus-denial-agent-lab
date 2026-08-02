"""A small SQLite state layer: durable spend, run index, and episode index.

Why this exists
---------------
Two pieces of state that must survive a restart were in-memory only:

- the daily spend total behind the budget guard, and
- the run index (which arm is running / done for which episode).

For a service meant to run untouched for months, losing those on every restart
is a real gap: the budget silently resets, and the run index has to be
reconstructed from scattered files. This module puts them in a single SQLite
file (WAL mode), which is the first, additive slice of the larger "move state to
a database" migration. The filesystem remains the source of truth for episode
*content* (results, logs, uploads); this only holds the small operational state
and an index for listing.

Design notes
------------
- One connection per operation, guarded by a process lock. Volume is low, so the
  simplicity is worth more than a connection pool.
- Every write is best-effort: a storage hiccup must never crash a patient run.
  Callers treat this as a durable cache, not a hard dependency.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .integrity import utc_now

# Reentrant: a write helper holds _LOCK and then calls _connect(), which may
# lazily call init(), which also takes _LOCK. A plain Lock would self-deadlock
# when init() hasn't been called yet (e.g. a direct caller that isn't the
# server's main()). RLock makes the same-thread re-acquire safe.
_LOCK = threading.RLock()
_DB_PATH: Path | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spend (
    day TEXT PRIMARY KEY,
    usd REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
    episode_id TEXT NOT NULL,
    arm TEXT NOT NULL,
    status TEXT,
    revision INTEGER,
    updated_at TEXT,
    PRIMARY KEY (episode_id, arm)
);
CREATE TABLE IF NOT EXISTS episodes (
    episode_id TEXT PRIMARY KEY,
    created_at TEXT,
    payer TEXT,
    procedure TEXT,
    state TEXT
);
"""


def init(db_path: str | os.PathLike | None = None) -> None:
    """Create the database and schema. Safe to call more than once."""
    global _DB_PATH
    path = Path(
        db_path
        or os.environ.get("MDPLUS_DB_PATH")
        or (Path(__file__).resolve().parents[1] / "outputs" / "state.sqlite3")
    ).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        _DB_PATH = path
        con = sqlite3.connect(str(path))
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_SCHEMA)
            con.commit()
        finally:
            con.close()


def _connect() -> sqlite3.Connection:
    if _DB_PATH is None:
        init()
    con = sqlite3.connect(str(_DB_PATH), timeout=10)
    con.row_factory = sqlite3.Row
    return con


def add_spend(day: str, delta: float) -> float:
    """Add to the day's spend and return the new total (0.0 on failure)."""
    try:
        with _LOCK:
            con = _connect()
            try:
                con.execute(
                    "INSERT INTO spend(day, usd) VALUES(?, ?) "
                    "ON CONFLICT(day) DO UPDATE SET usd = usd + excluded.usd",
                    (day, float(delta)),
                )
                con.commit()
                row = con.execute(
                    "SELECT usd FROM spend WHERE day = ?", (day,)
                ).fetchone()
                return float(row["usd"]) if row else 0.0
            finally:
                con.close()
    except sqlite3.Error:
        return 0.0


def get_spend(day: str) -> float:
    try:
        with _LOCK:
            con = _connect()
            try:
                row = con.execute(
                    "SELECT usd FROM spend WHERE day = ?", (day,)
                ).fetchone()
                return float(row["usd"]) if row else 0.0
            finally:
                con.close()
    except sqlite3.Error:
        return 0.0


def upsert_run(episode_id: str, arm: str, status: str, revision: int = 0) -> None:
    try:
        with _LOCK:
            con = _connect()
            try:
                con.execute(
                    "INSERT INTO runs(episode_id, arm, status, revision, updated_at) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(episode_id, arm) DO UPDATE SET "
                    "status=excluded.status, revision=excluded.revision, "
                    "updated_at=excluded.updated_at",
                    (episode_id, arm, status, int(revision or 0), utc_now()),
                )
                con.commit()
            finally:
                con.close()
    except sqlite3.Error:
        pass


def running_runs() -> list[dict[str, Any]]:
    """Runs the index still believes are running (for restart reconciliation)."""
    try:
        with _LOCK:
            con = _connect()
            try:
                rows = con.execute(
                    "SELECT episode_id, arm, status, revision FROM runs "
                    "WHERE status = 'running'"
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()
    except sqlite3.Error:
        return []


def upsert_episode(
    episode_id: str,
    payer: str | None = None,
    procedure: str | None = None,
    state: str | None = None,
) -> None:
    try:
        with _LOCK:
            con = _connect()
            try:
                con.execute(
                    "INSERT INTO episodes(episode_id, created_at, payer, procedure, state) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(episode_id) DO UPDATE SET "
                    "payer=excluded.payer, procedure=excluded.procedure, state=excluded.state",
                    (episode_id, utc_now(), payer, procedure, state),
                )
                con.commit()
            finally:
                con.close()
    except sqlite3.Error:
        pass


def delete_episode(episode_id: str) -> None:
    """Remove an episode's index + run rows (called when its data is purged)."""
    try:
        with _LOCK:
            con = _connect()
            try:
                con.execute("DELETE FROM episodes WHERE episode_id = ?", (episode_id,))
                con.execute("DELETE FROM runs WHERE episode_id = ?", (episode_id,))
                con.commit()
            finally:
                con.close()
    except sqlite3.Error:
        pass


def list_episodes(limit: int = 200) -> list[dict[str, Any]]:
    try:
        with _LOCK:
            con = _connect()
            try:
                rows = con.execute(
                    "SELECT episode_id, created_at, payer, procedure, state "
                    "FROM episodes ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()
    except sqlite3.Error:
        return []
