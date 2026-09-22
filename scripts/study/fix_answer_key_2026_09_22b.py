#!/usr/bin/env python3
"""Five 'vendor-held' cases whose document does not name the procedure.

Stratum B is defined as: the plan's own public policy NAMES THE CODE and sends
the criteria to a vendor. The audit (audit.py, check 2) found five answer-key
documents that name neither the code nor the operation: MedStar Family Choice
MD and DC's Policy 115 'Utilization Management Criteria', UPMC Health Plan's
provider manual chapter G, MVP Health Care's annual provider notice. Each
says, in general, that InterQual criteria are applied. That is a plan with NO
procedure-specific policy -- stratum C -- whose general UM policy is worth
citing for the route to the criteria.

So: the five cases move to stratum C; the general document is kept on the
entry as generic_um_url, and citing it is not a hallucination (score.py). The
directory rows get the status 'UM POLICY ONLY', which the product answers as
'no policy for this procedure; the plan's UM policy says which criteria set
applies; ask for it in writing' -- instead of telling the patient a document
'governs your procedure code' when it never mentions the procedure.
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "study" / "cases.json"
GOLD = ROOT / "study" / "gold.json"
DIRECTORY = ROOT / "data" / "policy_platform" / "app_option_policy_directory.csv"
STATUS = "UM POLICY ONLY (vendor criteria; no procedure-specific policy)"
NOTE = "2026-09-22 answer-key audit: "
PAYERS = {"MedStar Family Choice", "MedStar Family Choice DC", "UPMC Health Plan", "MVP Health Care"}


def main() -> int:
    for f in (CASES, GOLD, DIRECTORY):
        b = f.with_name(f.name + ".pre-answer-key-audit-3")
        if not b.exists():
            shutil.copy2(f, b)
    cases = json.loads(CASES.read_text())
    gold = json.loads(GOLD.read_text())
    by_id = {c["case_id"]: c for c in cases["cases"]}
    n = 0
    for g in gold["entries"]:
        if g["stratum"] == "vendor_held" and g["payer"] in PAYERS:
            g["generic_um_url"] = g["policy_url"]
            g["generic_um_title"] = g.get("policy_title", "")
            g["stratum_before_2026_09_22"] = "vendor_held"
            g.update(stratum="no_policy", correct_behavior="abstain_and_route",
                     policy_url="", policy_title="", directory_status=STATUS)
            g["directory_note"] = NOTE + ("the document does not name the procedure; it is the plan's "
                                          "general UM policy naming the criteria vendor. ") + g.get("directory_note", "")
            by_id[g["case_id"]]["stratum"] = "no_policy"
            n += 1
            print(f"  {g['case_id']} {g['payer']} {g['cpt']}: vendor_held -> no_policy (UM policy kept as route)")
    CASES.write_text(json.dumps(cases, indent=1))
    GOLD.write_text(json.dumps(gold, indent=1))

    with DIRECTORY.open(newline="") as f:
        rd = csv.DictReader(f)
        fields, rows = rd.fieldnames, list(rd)
    m = 0
    for r in rows:
        if r["insurance_company"] in PAYERS and r["status"].startswith("DOCUMENT PUBLIC"):
            r["status"] = STATUS
            r["note"] = NOTE + "general UM policy; names no procedure. " + r["note"]
            m += 1
    with DIRECTORY.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"answer key: {n} cases; directory: {m} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
