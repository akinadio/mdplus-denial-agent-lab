#!/usr/bin/env python3
"""How hard each system worked: searches, fetches and tokens per case.

Accuracy is not the only thing that separates these systems. A free chatbot
that answers in 15 searches and one that needs 45 are different products even
when they score the same: the second is slower for the patient and three times
the search bill for whoever runs it. On 2026-09-19 that gap was the single
largest line in the study budget -- Gemini alone cost more than the other three
arms put together, and 45 searches a case was most of why.

Counts come from each run's tools.jsonl, which is the actual tool ledger rather
than anything the model claims. Traces are truncated per attempt (they used to
append, so a retried case carried both attempts and read as double), so a run
that was retried counts only its final attempt.

  python3 scripts/study/effort.py
"""
from __future__ import annotations
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "study"))
STUDY = ROOT / "study"
RUNS = STUDY / "runs"


def main() -> int:
    import spend
    key = json.loads((STUDY / "unblinding.json").read_text())
    per = defaultdict(lambda: defaultdict(list))
    for rid, info in key.items():
        f = RUNS / rid / "result.json"
        if not f.exists():
            continue
        try:
            res = json.loads(f.read_text())
        except ValueError:
            continue
        if res.get("error") or res.get("skipped"):
            continue
        s = info["system"]
        trace = RUNS / rid / "tools.jsonl"
        searches = fetches = 0
        if trace.exists():
            for line in trace.open(encoding="utf-8"):
                if '"web_search"' in line:
                    searches += 1
                elif '"http_fetch"' in line:
                    fetches += 1
        per[s]["search"].append(searches)
        per[s]["fetch"].append(fetches)
        u = res.get("usage") or {}
        tok = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
               + u.get("cache_creation_input_tokens", 0))
        if tok:
            per[s]["tokens_in"].append(tok)
        try:
            per[s]["usd"].append(spend.cost(res.get("model", ""), u) if u else 0.0)
        except Exception:  # noqa: BLE001
            pass
        if res.get("elapsed_s"):
            per[s]["secs"].append(res["elapsed_s"])

    def col(vals, fmt="{:.0f}"):
        if not vals:
            return "     -"
        return fmt.format(st.median(vals))

    print("EFFORT PER CASE (median), from each run's own tool ledger\n")
    print(f"{'arm':14s} {'n':>3s} {'searches':>9s} {'fetches':>8s} "
          f"{'input tok':>11s} {'seconds':>8s} {'$/case':>7s} {'search $':>9s}")
    for s in sorted(per):
        d = per[s]
        n = len(d["search"])
        msearch = st.median(d["search"]) if d["search"] else 0
        print(f"{s:14s} {n:>3d} {col(d['search']):>9s} {col(d['fetch']):>8s} "
              f"{col(d['tokens_in'], '{:,.0f}'):>11s} {col(d['secs']):>8s} "
              f"{col(d['usd'], '{:.2f}'):>7s} {msearch * 0.005:>9.3f}")
    print("\nSearch is billed per request ($5 per 1,000), so the last column is a")
    print("real cost the retrieval numbers do not show. An arm that answers in 15")
    print("searches and one that needs 45 are different products even at equal")
    print("accuracy: one is slower for the patient and 3x the search bill.")
    tot = sum(st.median(d["search"]) if d["search"] else 0 for d in per.values())
    print(f"\nAll arms, one case end to end: {tot:.0f} searches = ${tot * 0.005:.2f}")
    print(f"  x 60 cases  = ${tot * 0.005 * 60:>7.2f}")
    print(f"  x 350 cases = ${tot * 0.005 * 350:>7.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
