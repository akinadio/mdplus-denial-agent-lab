#!/usr/bin/env python3
"""Post-deploy readiness check: is the service healthy and hardened?

Run against a deployed instance (through the public HTTPS URL) to confirm the
basics before sending patients to it. Safe: it hits /api/health and probes the
rate limiter with empty bodies (rejected before any model run), so it never
spawns paid work.

  python3 scripts/readiness_check.py https://appeals.example.com

Exit code is non-zero if a check fails, so it can gate a deploy.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request

TIMEOUT = 15


def _get(url):
    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return r.status, r.read(), round((time.time() - started) * 1000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), round((time.time() - started) * 1000)
    except Exception as e:  # noqa: BLE001
        return None, str(e).encode(), round((time.time() - started) * 1000)


def _post_empty(url):
    req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: readiness_check.py <base_url>")
        return 2
    base = sys.argv[1].rstrip("/")
    ok = True

    # 1. Health + degraded reasons.
    status, body, ms = _get(base + "/api/health")
    if status != 200:
        print(f"FAIL  health returned {status}")
        return 1
    health = json.loads(body)
    print(f"health: {ms}ms  engine={health.get('engine')}  degraded={health.get('degraded')}")
    if health.get("degraded"):
        ok = False
        for reason in health.get("degraded_reasons", []):
            print(f"  - {reason}")

    # 2. Concurrency: a burst of health checks should all succeed.
    results = []
    def hit():
        results.append(_get(base + "/api/health")[0])
    threads = [threading.Thread(target=hit) for _ in range(12)]
    for t in threads: t.start()
    for t in threads: t.join()
    good = sum(1 for s in results if s == 200)
    print(f"concurrency: {good}/12 concurrent health checks OK")
    if good < 12:
        ok = False

    # 3. Rate limiting must engage (expect a 429 within a burst).
    codes = [_post_empty(base + "/api/episodes") for _ in range(15)]
    if 429 in codes:
        print(f"rate limiting: engaged (429 seen after {codes.index(429)} requests)")
    else:
        print(f"rate limiting: WARN no 429 in a 15-request burst (codes: {sorted(set(codes))})")
        ok = False

    print("\nREADY" if ok else "\nNOT READY — address the items above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
