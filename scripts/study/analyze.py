#!/usr/bin/env python3
"""Unblind, tabulate, and test.

Run ONLY after scoring closes: this is the single place that joins
study/unblinding_map.json to study/scores_v1.json.

Statistics per the protocol:
- Primary comparison: OrthoAppeals vs each general arm on citation validity,
  paired by case -> exact McNemar test (binomial on the discordant pairs).
- Three comparisons -> Bonferroni, alpha = 0.05 / 3 = 0.0167.
- Per-stratum tables are reported descriptively (the study is not powered for
  stratum-level inference).

Power (fixed design, 200 paired cases): with alpha=0.0167 two-sided, the
exact McNemar test has >=80% power when the discordant-pair pattern is at
least ~24 vs ~8 out of 200 (i.e. the tool resolves ~12% of cases the model
misses, against ~4% the model gets and the tool misses). Larger validity gaps
need fewer discordant pairs. The 120/40/40 stratification serves coverage,
not power.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study"

ALPHA = 0.05 / 3


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar: binomial(b; b+c, 0.5)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def main() -> None:
    scores = json.loads((STUDY / "scores_v1.json").read_text())
    mapping = json.loads((STUDY / "unblinding_map.json").read_text())
    cases = {c["case_id"]: c for c in
             json.loads((STUDY / "cases_v1.json").read_text())["cases"]}

    # valid-by-(case, arm)
    grid: dict[str, dict[str, bool]] = {}
    for rid, s in scores.items():
        if "checks" not in s:
            continue
        m = mapping.get(rid)
        if not m:
            continue
        grid.setdefault(m["case_id"], {})[m["arm"]] = bool(s.get("valid"))

    arms = sorted({a for v in grid.values() for a in v})
    print("cases with any scored run:", len(grid))
    for arm in arms:
        xs = [v[arm] for v in grid.values() if arm in v]
        if xs:
            print(f"  {arm:14s} valid {sum(xs)}/{len(xs)} = {sum(xs)/len(xs):.1%}")

    if "orthoappeals" in arms:
        print(f"\npaired comparisons vs orthoappeals (exact McNemar, "
              f"Bonferroni alpha={ALPHA:.4f}):")
        for arm in arms:
            if arm == "orthoappeals":
                continue
            pairs = [(v["orthoappeals"], v[arm]) for v in grid.values()
                     if "orthoappeals" in v and arm in v]
            b = sum(1 for o, g in pairs if o and not g)   # tool right, model wrong
            c = sum(1 for o, g in pairs if g and not o)   # model right, tool wrong
            p = mcnemar_exact(b, c)
            sig = "SIGNIFICANT" if p < ALPHA else "n.s."
            print(f"  vs {arm:8s} n={len(pairs)} discordant {b}:{c} "
                  f"p={p:.4g} {sig}")

    # descriptive stratum table
    print("\nby stratum (descriptive):")
    for stratum in ("national", "regional", "revised6mo"):
        ids = [cid for cid, c in cases.items() if c["stratum"] == stratum]
        for arm in arms:
            xs = [grid[cid][arm] for cid in ids if cid in grid and arm in grid[cid]]
            if xs:
                print(f"  {stratum:10s} {arm:14s} {sum(xs)}/{len(xs)}")


if __name__ == "__main__":
    main()
