#!/usr/bin/env python3
"""Answer-key corrections found by reading every in-library document in full.

build_section_criteria.py read each study document and reported, for five
cases, that it states NO medical-necessity criteria for the case's operation.
Each was checked by hand:

  Priority Health / 22551 (ACDF)       Spine Procedures 91581 names ACDF and
      says it is "medically necessary according to TurningPoint criteria" --
      the criteria are TurningPoint's, behind a login. That is VENDOR-HELD:
      cite the public policy and route for the criteria. Not in-library.
  CountyCare / 27446 (partial knee)    ECG_2734.CC lists 27446 in its code
      table but sets only inpatient-vs-outpatient site of service; the
      directory note records that InterQual governs medical necessity.
      VENDOR-HELD, for the same reason.
  HealthPartners / 63030               The answer was the policy's HTML page,
      which renders client-side: what a reader without a browser gets is
      navigation. The same policy is published as a PDF with the criteria in
      it (and 63030 in its code table). Answer re-pointed to the PDF; citing
      either copy is still correct (equivalence.py reads ENTRY_256055 as one id).
  Avera / 28296 and Avera / 29827      The answer is Cohere's index page for
      Avera; the criteria are in separate PDFs linked from it (Great Toe
      Surgical Treatments v3; Shoulder Arthroscopy v5). Not changed here --
      the PDFs are behind expiring links and have to be downloaded by hand
      (see docs/avera-pdfs.md).

The directory rows that carry the same errors are corrected too, so the
product stops making them. Idempotent; backups written once.
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
SECTIONS = ROOT / "data" / "policy_platform" / "section_criteria.json"

HP_HTML = "https://www.healthpartners.com/public/coverage-criteria/policy.html?contentid=ENTRY_256055"
HP_PDF = "https://www.healthpartners.com/ucm/groups/public/@hp/@public/@cc/documents/documents/entry_256055.pdf"
VH = "DOCUMENT PUBLIC, CRITERIA VENDOR-HELD"
TO_VENDOR_HELD = {   # (state, payer, cpt) -> vendor
    ("Michigan", "Priority Health", "22551"): "TurningPoint",
    ("Michigan", "Priority Health", "22612"): "TurningPoint",
    ("Michigan", "Priority Health", "63030"): "TurningPoint",
    ("Illinois", "CountyCare", "27446"): "InterQual",
    ("Illinois", "CountyCare", "27447"): "InterQual",
    ("Illinois", "CountyCare", "27130"): "InterQual",
}
NOTE = "2026-09-21 answer-key audit: "


def main() -> int:
    for f in (CASES, GOLD, DIRECTORY):
        b = f.with_name(f.name + ".pre-answer-key-audit")
        if not b.exists():
            shutil.copy2(f, b)

    cases = json.loads(CASES.read_text())
    gold = json.loads(GOLD.read_text())
    by_id = {c["case_id"]: c for c in cases["cases"]}
    n = 0
    for g in gold["entries"]:
        k = (g["state"], g["payer"], g["cpt"])
        if k in TO_VENDOR_HELD and g["stratum"] == "in_library":
            g.update(stratum="vendor_held", correct_behavior="cite_and_route",
                     vendor=TO_VENDOR_HELD[k], directory_status=VH,
                     stratum_before_2026_09_21="in_library")
            g["directory_note"] = (NOTE + f"the public policy names this code but the medical-"
                                   f"necessity criteria are {TO_VENDOR_HELD[k]}'s. "
                                   + g.get("directory_note", ""))
            by_id[g["case_id"]]["stratum"] = "vendor_held"
            n += 1
            print(f"  {g['case_id']} {g['payer']} {g['cpt']}: in_library -> vendor_held")
        if g.get("policy_url") == HP_HTML:
            g["policy_url_before_2026_09_21"] = HP_HTML
            g["policy_url"] = HP_PDF
            n += 1
            print(f"  {g['case_id']} HealthPartners {g['cpt']}: HTML page -> PDF")
    CASES.write_text(json.dumps(cases, indent=1))
    GOLD.write_text(json.dumps(gold, indent=1))

    with DIRECTORY.open(newline="") as f:
        rd = csv.DictReader(f)
        fields, rows = rd.fieldnames, list(rd)
    m = 0
    for r in rows:
        k = (r["state"], r["insurance_company"], r["cpt"])
        if k in TO_VENDOR_HELD and r["status"] == "VERIFIED":
            r["status"] = VH
            r["note"] = (NOTE + f"criteria are {TO_VENDOR_HELD[k]}'s; this public document names "
                         f"the code but does not state them. " + r["note"])
            m += 1
        if r["policy_url"] == HP_HTML:
            r["policy_url"] = HP_PDF
            r["note"] = NOTE + "HTML page renders client-side; the PDF carries the criteria. " + r["note"]
            m += 1
    with DIRECTORY.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # The section map's verdicts for the retired answers no longer apply.
    if SECTIONS.exists():
        sec = json.loads(SECTIONS.read_text())
        drop = [k for k in sec if k.startswith(HP_HTML + "||")]
        for k in drop:
            del sec[k]
        SECTIONS.write_text(json.dumps(sec, indent=1, ensure_ascii=False))
    print(f"answer key: {n} changes; directory: {m} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
