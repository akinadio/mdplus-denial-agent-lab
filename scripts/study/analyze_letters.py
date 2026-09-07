#!/usr/bin/env python3
"""Unblind the letter grades and report them by system and stratum."""
from __future__ import annotations
import collections, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study"

grades = json.loads((STUDY / "letter_grades.json").read_text())
key = json.loads((STUDY / "unblinding.json").read_text())
cases = {c["case_id"]: c for c in json.loads((STUDY / "cases.json").read_text())["cases"]}

DEFECTS = [("quote_not_in_policy", "quote NOT in the policy"),
           ("unsupported_attribution", "rule attributed to plan, no source"),
           ("wrong_policy_cited",  "wrong policy cited"),
           ("wrong_recipient",     "wrong insurer addressed"),
           ("wrong_deadline",      "wrong deadline"),
           ("invented_identifier", "invented policy number/date"),
           ("unfinished",          "unfinished (records were available)")]
GOOD = [("cites_correct_policy", "cites the correct policy"),
        ("uses_records",         "maps criteria to the records"),
        ("deadline_correct",     "deadline correct"),
        ("route_given",          "tells them where to send it"),
        ("demands_criteria",     "demands the criteria")]

agg = collections.defaultdict(lambda: collections.defaultdict(list))
for rid, g in grades.items():
    if g.get("outcome") != "graded":
        continue
    k = (key.get(rid, {}).get("system", "?"), cases[g["case_id"]]["stratum"])
    for f, _ in GOOD + DEFECTS:
        agg[k][f].append(bool(g.get(f)))
    agg[k]["completeness"].append(int(g.get("completeness") or 0))
    q = g.get("quotes") or {}
    agg[k]["_q"].append(q.get("quotes", 0))
    agg[k]["_bad"].append(q.get("not_in_policy", 0))
    agg[k]["_unver"].append(q.get("unverifiable", 0))
    agg[k]["_g"].append(g)

import collections as _c
_inc = _c.Counter(key.get(r, {}).get("system", "?") for r, g in grades.items()
                  if g.get("outcome") in ("grader_incomplete", "grader_error"))
if _inc:
    print(f"NOT GRADED (retry with --resume): {dict(_inc)}\n")
print("LETTER QUALITY")
for (sysname, stratum), d in sorted(agg.items()):
    n = len(d["completeness"])
    print(f"\n  {sysname}  {stratum}  n={n}")
    for f, label in GOOD:
        if f == "demands_criteria" and stratum == "in_library":
            continue   # the criteria are in hand; there is nothing to demand
        print(f"    {label:34s} {sum(d[f])/n:5.0%}")
    print(f"    {'completeness (0-4)':34s} {sum(d['completeness'])/n:5.1f}")
    print("    defects")
    for f, label in DEFECTS:
        c = sum(d[f])
        print(f"      {label:32s} {c:2d}/{n} = {c/n:4.0%}")
    tot, bad, unver = sum(d["_q"]), sum(d["_bad"]), sum(d["_unver"])
    other = sum((g.get("quotes") or {}).get("from_other_sources", 0) for g in d["_g"])
    print(f"    quotations: {tot} of the policy, {bad} not found in it, "
          f"{unver} unverifiable; {other} of the denial notice or records (fine)")

print("\nPAIRED, same letter")
by_case = collections.defaultdict(dict)
for rid, g in grades.items():
    if g.get("outcome") == "graded":
        by_case[g["case_id"]][key.get(rid, {}).get("system", "?")] = g
systems = sorted({s for v in by_case.values() for s in v})
for i, a in enumerate(systems):
    for b in systems[i+1:]:
        both = [v for v in by_case.values() if a in v and b in v]
        for f, label in DEFECTS[:2]:
            ao = sum(1 for v in both if v[a].get(f) and not v[b].get(f))
            bo = sum(1 for v in both if v[b].get(f) and not v[a].get(f))
            print(f"  {label:26s} n={len(both)}  {a} only={ao}  {b} only={bo}")

bad = [(rid, g) for rid, g in grades.items()
       if g.get("outcome") == "graded" and g.get("quote_not_in_policy")]
if bad:
    print(f"\nEVERY UNSUPPORTED QUOTATION ({len(bad)} letters) -- these are checkable, read them")
    for rid, g in bad:
        sysname = key.get(rid, {}).get("system", "?")
        for ex in (g.get("quotes") or {}).get("examples", [])[:1]:
            print(f"  [{sysname:13s}] {cases[g['case_id']]['stratum']:11s} \"{ex[:110]}\"")
