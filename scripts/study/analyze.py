#!/usr/bin/env python3
"""Unblind and tabulate the proof-of-concept. Run only after scoring."""
import json, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
S = ROOT / "study"

scores = json.loads((S / "scores.json").read_text())
mapping = json.loads((S / "unblinding.json").read_text())
cases = {c["case_id"]: c for c in json.loads((S / "cases.json").read_text())["cases"]}

grid = collections.defaultdict(dict)
outc = collections.defaultdict(collections.Counter)
for rid, s in scores.items():
    m = mapping.get(rid)
    if not m or "correct" not in s:
        continue
    grid[m["case_id"]][m["system"]] = s["correct"]
    outc[(m["system"], s["stratum"])][s["outcome"]] += 1

systems = sorted({m["system"] for m in mapping.values()})
print("ACCURACY")
for sysname in systems:
    for stratum in ("in_library", "vendor_held", "no_policy"):
        xs = [v for cid, v in grid.items()
              if sysname in v and cases[cid]["stratum"] == stratum]
        vals = [grid[c][sysname] for c in grid
                if sysname in grid[c] and cases[c]["stratum"] == stratum]
        if vals:
            print(f"  {sysname:14s} {stratum:11s} {sum(vals):2d}/{len(vals):2d} = {sum(vals)/len(vals):5.1%}")

print("\nOUTCOME BREAKDOWN")
for (sysname, stratum), c in sorted(outc.items()):
    print(f"  {sysname:14s} {stratum:11s} " + ", ".join(f"{k}={v}" for k, v in c.most_common()))

print("\nHEAD-TO-HEAD (paired, same letter)")
for sysname in systems:
    if not sysname.startswith("ortho"):
        continue
    for other in systems:
        if other == sysname or other.startswith("ortho"):
            continue
        pairs = [(grid[c][sysname], grid[c][other]) for c in grid
                 if sysname in grid[c] and other in grid[c]]
        b = sum(1 for o, g in pairs if o and not g)
        d = sum(1 for o, g in pairs if g and not o)
        print(f"  {sysname} vs {other}: n={len(pairs)}, {sysname} only={b}, {other} only={d}")
