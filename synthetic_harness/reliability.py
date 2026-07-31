"""Unattended-operation support: crash recovery, health, and alerting.

The goal of this module is that the service can run for months without a human
watching it, and that when something does go wrong it is visible instead of
silent. It provides three things:

1. `reconcile_interrupted_runs` -- on startup, flip any arm still marked
   "running" on disk to "interrupted". A run thread cannot survive a restart,
   so a persisted "running" status after a fresh boot is always a lie that
   would otherwise hang the UI and the retry guard forever.
2. `build_health` -- a rich, pure health snapshot the /api/health endpoint
   returns, including a `degraded` flag and human-readable reasons so an
   uptime check can page on real problems (missing key, unbuilt UI, budget
   paused) rather than just "is the port open".
3. `alert` -- log every failure through the stdlib logger and, if
   MDPLUS_ALERT_WEBHOOK is set, POST it (best-effort, off-thread) so failures
   reach a human channel.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from pathlib import Path
from typing import Any

from .integrity import utc_now, write_json_atomic

log = logging.getLogger("mdplus.harness")


def configure_logging() -> None:
    level = os.environ.get("MDPLUS_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def reconcile_interrupted_runs(episodes_root: Path) -> list[dict[str, str]]:
    """Mark orphaned "running" arms as interrupted after a restart.

    Returns the list of {episode_id, arm} it corrected.
    """
    reconciled: list[dict[str, str]] = []
    if not episodes_root.exists():
        return reconciled
    for status_path in episodes_root.glob("*/system/*/runtime_status.json"):
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("status") != "running":
            continue
        arm = status_path.parent.name
        episode_id = status_path.parents[2].name
        data.update(
            {
                "status": "interrupted",
                "error": "Run was interrupted by a server restart and did not finish. Retry it.",
                "finished_at": utc_now(),
                "interrupted": True,
            }
        )
        try:
            write_json_atomic(status_path, data)
        except OSError:
            continue
        reconciled.append({"episode_id": episode_id, "arm": arm})
    if reconciled:
        log.warning(
            "Reconciled %d interrupted run(s) left over from a prior restart: %s",
            len(reconciled),
            ", ".join(f"{r['episode_id']}/{r['arm']}" for r in reconciled),
        )
    return reconciled


def build_health(
    *,
    episodes_root: Path,
    engine: str,
    build_id: str,
    started_at: str,
    ui_built: bool,
    max_concurrent_arms: int,
    active_arms: int,
    spend: dict[str, Any],
    daily_budget_usd: float,
    budget_paused: bool,
) -> dict[str, Any]:
    """A pure health snapshot. `degraded` is true when a real problem exists."""
    reasons: list[str] = []
    if not ui_built:
        reasons.append("UI build missing (ui/dist) — run npm run build")
    if not os.environ.get("WEB_SEARCH_API_KEY"):
        reasons.append("WEB_SEARCH_API_KEY not set — web_search will fail")
    if engine == "api" and not os.environ.get("ANTHROPIC_API_KEY"):
        reasons.append("engine is api but ANTHROPIC_API_KEY not set")
    if budget_paused:
        reasons.append("daily model budget reached — new runs paused")
    try:
        episode_count = sum(1 for _ in episodes_root.glob("ep_*")) if episodes_root.exists() else 0
    except OSError:
        episode_count = None
    return {
        "ok": not reasons,
        "degraded": bool(reasons),
        "degraded_reasons": reasons,
        "engine": engine,
        "ui_built": ui_built,
        "server_started_at": started_at,
        "server_build_id": build_id,
        "web_worker_mode": "in_process_tools" if engine == "api" else "outer_os_barrier",
        "episode_count": episode_count,
        "concurrency": {
            "max_arms": max_concurrent_arms,
            "active_arms": active_arms,
            "available_slots": max(0, max_concurrent_arms - active_arms),
        },
        "spend": {
            "day": spend.get("day"),
            "estimated_usd": round(float(spend.get("usd", 0.0)), 4),
            "daily_budget_usd": daily_budget_usd or None,
            "paused": budget_paused,
        },
    }


def alert(kind: str, message: str, details: dict[str, Any] | None = None) -> None:
    """Record a failure and, if configured, push it to an external channel."""
    log.error("ALERT [%s] %s %s", kind, message, json.dumps(details or {}, default=str))
    webhook = os.environ.get("MDPLUS_ALERT_WEBHOOK")
    if not webhook:
        return
    payload = json.dumps(
        {"kind": kind, "message": message, "details": details or {}, "at": utc_now()},
        default=str,
    ).encode("utf-8")

    def _post() -> None:
        try:
            req = urllib.request.Request(
                webhook, data=payload, headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=5).read()  # noqa: S310 - operator-set URL
        except Exception:  # noqa: BLE001 - alerting must never crash a run
            log.warning("alert webhook POST failed for kind=%s", kind)

    threading.Thread(target=_post, daemon=True).start()
