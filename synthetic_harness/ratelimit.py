"""Per-client rate limiting and operator-endpoint protection.

The API is public and every expensive call (creating an episode, drafting a
letter) spawns paid model work. The daily spend guard caps the bill, but a flood
of requests can still burn the whole budget in minutes and starve real patients.
This adds a cheap first line of defence: a per-client fixed-window limiter on the
expensive endpoints, and an optional shared-secret gate on operator-only
endpoints (evaluate / adjudicate / metrics) so they are not world-callable.

In-process only (resets on restart, per-instance). Behind a load balancer, put a
real edge limiter in front too; this protects a single instance and bounds cost.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any


class FixedWindowLimiter:
    """Allow up to `limit` events per `window` seconds per key (e.g. per IP)."""

    def __init__(self, limit: int, window: float):
        self.limit = max(1, int(limit))
        self.window = float(window)
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds). Records the hit when allowed."""
        t = time.time() if now is None else now
        cutoff = t - self.window
        with self._lock:
            hits = [h for h in self._hits.get(key, ()) if h > cutoff]
            if len(hits) >= self.limit:
                retry = round(hits[0] + self.window - t, 1)
                self._hits[key] = hits
                return False, max(0.0, retry)
            hits.append(t)
            self._hits[key] = hits
            # Opportunistic cleanup so the dict can't grow without bound.
            if len(self._hits) > 4096:
                for k in [k for k, v in self._hits.items()
                          if not any(h > cutoff for h in v)]:
                    self._hits.pop(k, None)
            return True, 0.0


def client_key(handler: Any, trust_proxy: bool) -> str:
    """Best-effort client identity for limiting.

    Behind a trusted reverse proxy, honor the first X-Forwarded-For hop;
    otherwise use the socket peer so a spoofed header can't dodge the limit.
    """
    if trust_proxy:
        fwd = handler.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    try:
        return handler.client_address[0]
    except Exception:  # noqa: BLE001
        return "unknown"


class ApiGuards:
    """Bundles the limiters and the operator token; reads config from env."""

    def __init__(self) -> None:
        self.trust_proxy = os.environ.get("MDPLUS_TRUST_PROXY", "").lower() in (
            "1", "true", "yes"
        )
        self.create = FixedWindowLimiter(
            int(os.environ.get("MDPLUS_RATE_CREATE_PER_MIN", "8")), 60.0
        )
        self.letter = FixedWindowLimiter(
            int(os.environ.get("MDPLUS_RATE_LETTER_PER_MIN", "12")), 60.0
        )
        self.admin_token = os.environ.get("MDPLUS_ADMIN_TOKEN", "")

    def limit(self, which: str, handler: Any) -> tuple[bool, float]:
        limiter = getattr(self, which)
        return limiter.check(client_key(handler, self.trust_proxy))

    def admin_ok(self, handler: Any) -> bool:
        """True when operator endpoints may proceed.

        If no admin token is configured the gate is open (preserves current
        behavior); once set, callers must present it via X-Admin-Token.
        """
        if not self.admin_token:
            return True
        return handler.headers.get("X-Admin-Token", "") == self.admin_token
