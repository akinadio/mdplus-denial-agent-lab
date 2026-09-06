#!/usr/bin/env python3
"""Overlay imaging cells recovered from coverage.js onto the rebuilt directory.

The imaging directory was lost with the rest of data/policy_platform's
uncommitted files, and with it every cell settled by the browser sessions that
took imaging coverage from a third to a half. build_imaging_directory.py
regenerates the cells whose evidence is written into its rules; the rest
survive only as their build product in coverage.js at d0c2861 -- code, url,
title, no note, no effective date.

A recovered cell is overlaid only where the rebuilt directory says NOT
RESEARCHED, so nothing the builder knows from evidence is overwritten by a
build product, and every recovered row says in its note where it came from
and what it is missing.

  python3 scripts/policy_platform/recover_imaging_cells.py
"""
from __future__ import annotations

import csv
import json
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMG = ROOT / "data" / "policy_platform" / "app_option_imaging_directory.csv"
COMMIT = "d0c2861"
IMAGING = {"73721", "73221", "72148", "72141"}
CODE_TO_STATUS = {
    "V": "VERIFIED", "P": "PROCESS DOC ONLY (no procedure criteria)",
    "B": "VERIFIED (criteria public, no stable link)", "A": "NO PRIOR AUTH REQUIRED",
    "X": "CONFIRMED NO POLICY", "L": "NO LCD — general medical necessity",
    "N": "NO PUBLIC CRITERIA (vendor)", "G": "GATED", "C": "CODE ONLY",
    "S": "STALE", "U": "UNREACHABLE", "D": "DOCUMENT PUBLIC, CRITERIA VENDOR-HELD",
}
NOTE = (f"recovered 2026-09-05 from coverage.js at {COMMIT}: the research note and "
        "effective date were lost with the original directory; status, document and "
        "title are the build product of that research.")


def main() -> int:
    js = subprocess.run(["git", "show", f"{COMMIT}:mockups/assets/coverage.js"],
                        cwd=ROOT, capture_output=True, text=True, check=True).stdout
    d = json.loads(js[js.index("{"):js.rindex("}") + 1])
    urls = d["urls"]

    def ent(e):
        code, uix, title = e[0], e[1], e[2]
        return CODE_TO_STATUS.get(code, "NOT RESEARCHED"), (urls[uix] if uix >= 0 else ""), title

    rows = list(csv.DictReader(IMG.open(encoding="utf-8", newline="")))
    fields = list(rows[0])
    tally = Counter()
    for r in rows:
        if r["cpt"] not in IMAGING or r["status"] != "NOT RESEARCHED":
            continue
        if r["insurance_company"] == "Medicare":
            e = d["medicare"].get(f"{r['state']}|{r['cpt']}")
        elif r["insurance_company"] == "Medicaid":
            e = d["medicaid"].get(f"{r['state']}|{r['cpt']}")
        else:
            e = d["comm"].get(f"{r['insurance_company']}|{r['cpt']}")
        if not e:
            continue
        status, url, title = ent(e)
        if status == "NOT RESEARCHED":
            continue
        r["status"], r["policy_url"], r["policy_title"], r["note"] = status, url, title, NOTE
        tally[status] += 1

    with IMG.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"overlaid {sum(tally.values())} recovered imaging cells:")
    for k, n in tally.most_common():
        print(f"  {n:5d}  {k}")
    print("\nimaging directory now:")
    for k, n in Counter(r["status"] for r in rows).most_common():
        print(f"  {n:5d}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
