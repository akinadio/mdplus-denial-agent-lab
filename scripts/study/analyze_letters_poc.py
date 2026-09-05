#!/usr/bin/env python3
"""Unblind the letter grades and report them by system and stratum."""
from __future__ import annotations
import collections, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study"

grades = json.loads((STUDY / "poc_letter_grades.json").read_text())
key = json.loads((STUDY / "poc_unblinding.json").read_text())
cases = {c["case_id"]: c for c in json.loads((STUDY / "poc_cases.json").read_text())["cases"]}

BOOLS = ["cites_correct_policy", "fabricated_criteria", "deadline_correct",
         "route_given", "demands_criteria", "appeal_fatal_error"]
agg = collections.defaultdict(lambda: collections.defaultdict(list))
for rid, g in grades.items():
    if g.get("outcome") != "graded":
        continue
    sysname = key.get(rid, {}).get("system", "?")
    stratum = cases[g["case_id"]]["stratum"]
    for k in BOOLS:
        agg[(sysname, stratum)][k].append(bool(g.get(k)))
    agg[(sysname, stratum)]["completeness"].append(int(g.get("completeness") or 0))
    agg[(sysname, stratum)]["n_errors"].append(len(g.get("factual_errors") or []))

print("LETTER QUALITY  (n = letters graded)")
for (sysname, stratum), d in sorted(agg.items()):
    n = len(d["appeal_fatal_error"])
    def pct(k): return f"{sum(d[k])/n:5.0%}" if n else "  n/a"
    print(f"\n  {sysname}  {stratum}  n={n}")
    print(f"    cites correct policy   {pct('cites_correct_policy')}")
    print(f"    fabricated criteria    {pct('fabricated_criteria')}   <- the one that discredits a letter")
    print(f"    deadline correct       {pct('deadline_correct')}")
    print(f"    route given            {pct('route_given')}")
    print(f"    demands criteria       {pct('demands_criteria')}")
    print(f"    APPEAL-FATAL ERROR     {pct('appeal_fatal_error')}")
    print(f"    completeness (0-4)     {sum(d['completeness'])/n:4.1f}")
    print(f"    factual errors/letter  {sum(d['n_errors'])/n:4.1f}")

print("\nAPPEAL-FATAL, paired by letter")
by_case = collections.defaultdict(dict)
for rid, g in grades.items():
    if g.get("outcome") == "graded":
        by_case[g["case_id"]][key.get(rid, {}).get("system", "?")] = bool(g.get("appeal_fatal_error"))
systems = sorted({s for v in by_case.values() for s in v})
for i, a in enumerate(systems):
    for b in systems[i+1:]:
        both = [v for v in by_case.values() if a in v and b in v]
        a_only = sum(1 for v in both if v[a] and not v[b])
        b_only = sum(1 for v in both if v[b] and not v[a])
        print(f"  n={len(both)}  {a} fatal only={a_only}  {b} fatal only={b_only}")

fatal = [(rid, g) for rid, g in grades.items()
         if g.get("outcome") == "graded" and g.get("appeal_fatal_error")]
if fatal:
    print(f"\nEVERY APPEAL-FATAL LETTER ({len(fatal)}) -- read these before reporting anything")
    for rid, g in fatal:
        print(f"  [{key.get(rid,{}).get('system','?'):13s}] {cases[g['case_id']]['stratum']:11s} "
              f"{(g.get('appeal_fatal_reason') or '')[:100]}")
