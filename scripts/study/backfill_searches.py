#!/usr/bin/env python3
"""Put the searches already made onto the ledger.

Search is billed per request and never passed through spend.cost(), so until
2026-09-21 the running total left it out entirely: $41 across 8,281 requests,
a fifth of the study, outside the one number that was meant to be auditable.
webtools.search() records each request as it happens now. This adds the ones
made before that, read from each run's own tool trace.

Idempotent: a run whose searches are already on the ledger is skipped, so this
can be run again without double-charging. A request the backend never received
-- a DNS failure -- is not billed and is not counted.

  python3 scripts/study/backfill_searches.py          # report
  python3 scripts/study/backfill_searches.py --apply
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "study"))
import spend  # noqa: E402

RUNS = ROOT / "study" / "runs"
NOT_BILLED = ("unreachable", "DNS resolution failed", "not set")


def billed(trace: Path) -> int:
    n = 0
    for line in trace.open(encoding="utf-8"):
        if '"web_search"' not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        err = str((rec.get("obs") or {}).get("error") or "")
        if any(m in err for m in NOT_BILLED):
            continue     # never reached them, so never billed
        n += 1
    return n


def main() -> int:
    apply = "--apply" in sys.argv
    done = {r.get("ref") for r in json.loads(spend.LEDGER.read_text() or "[]")
            if r.get("step") == "search"}
    rows, total, skipped = [], 0, 0
    for trace in sorted(RUNS.glob("r-*/tools.jsonl")):
        rid = trace.parent.name
        if rid in done:
            skipped += 1
            continue
        n = billed(trace)
        if n:
            rows.append((rid, n))
            total += n
    print(f"{len(rows)} runs with unrecorded searches; {skipped} already on the ledger")
    print(f"{total:,} billed requests = ${total * spend.SEARCH_PRICE_PER_1000 / 1000:.2f}")
    if not apply:
        print("\nRe-run with --apply to add them.")
        return 0
    for rid, n in rows:
        spend.record_search(n, rid)
    print(f"\nadded. ledger total is now ${spend.total():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
