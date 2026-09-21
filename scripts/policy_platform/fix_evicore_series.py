#!/usr/bin/env python3
"""Give each eviCore "series" row the guideline for ITS operation.

Forty directory rows carry the title "eviCore CMM-311/312/313/314/315/601/
606/609 series (generic EviCore editions, same URLs as WellSense entry)" and,
for every operation, the URL of CMM-311 -- the KNEE replacement guideline. A
hip replacement or a shoulder labral repair for Security Health Plan was
pointed at knee criteria; two such cases are in the study's answer key, and
OrthoAppeals read the same row, so it cited the knee guideline too.

The fix follows the row's own title and note: the generic EviCore edition of
the guideline for that operation, the same URL the WellSense rows use. Where
the note says there is no plan-agnostic public guideline for the operation
(23472 under CMM-318) or that eviCore does not cover it (27702, 28296), the
row is marked NEEDS REVIEW instead of being given a document that is wrong.

Idempotent. Writes a .pre-evicore-series-fix backup the first time.
Also corrects study/gold.json for the same payer/operation pairs.
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "data" / "policy_platform" / "app_option_policy_directory.csv"
GOLD = ROOT / "study" / "gold.json"
BASE = "https://www.evicore.com/sites/default/files/clinical-guidelines/"
BY_CPT = {
    "27447": ("eviCore CMM-311 Knee Replacement/Arthroplasty",
              BASE + "2025-08/EviCore_CMM-311%20Knee%20Replacement%20Arthroplasty_V2.0.2025_Eff11.05.2025_upd08.12.2025.pdf"),
    "27446": ("eviCore CMM-311 Knee Replacement/Arthroplasty",
              BASE + "2025-08/EviCore_CMM-311%20Knee%20Replacement%20Arthroplasty_V2.0.2025_Eff11.05.2025_upd08.12.2025.pdf"),
    "29881": ("eviCore CMM-312 Knee Surgery - Arthroscopic and Open Procedures",
              BASE + "2025-02/EviCore_CMM-312%20Knee%20Surg%20Arthro_Final_V1.0.2025_Pub02.25.2025.pdf"),
    "29888": ("eviCore CMM-312 Knee Surgery - Arthroscopic and Open Procedures",
              BASE + "2025-02/EviCore_CMM-312%20Knee%20Surg%20Arthro_Final_V1.0.2025_Pub02.25.2025.pdf"),
    "27130": ("eviCore CMM-313 Hip Replacement/Arthroplasty",
              BASE + "2025-07/EviCore_CMM-313%20Hip%20Replac%20Arthro_Final_V2.0.2025_eff11.05.2025_pub07.22.2025.pdf"),
    "29914": ("eviCore CMM-314 Hip Surgery - Arthroscopic and Open Procedures",
              BASE + "2025-02/EviCore_CMM-314%20Hip%20Surg%20Arthro%20Open%20Proc_Final_V1.0.2025_Pub02.25.2025.pdf"),
    "29827": ("eviCore CMM-315 Shoulder Surgery - Arthroscopic and Open Procedures",
              BASE + "2025-02/EviCore_CMM-315%20Shoulder%20Surg%20Arthro_Final_V1.0.2025_Pub02.25.2025.pdf"),
    "29806": ("eviCore CMM-315 Shoulder Surgery - Arthroscopic and Open Procedures",
              BASE + "2025-02/EviCore_CMM-315%20Shoulder%20Surg%20Arthro_Final_V1.0.2025_Pub02.25.2025.pdf"),
    "22551": ("eviCore CMM-601 Anterior Cervical Discectomy and Fusion",
              BASE + "2025-02/EviCore_CMM-601%20Ant%20Cerv%20Disc_Final_V1.0.2025_Pub02.26.2025.pdf"),
    "22612": ("eviCore CMM-609 Lumbar Fusion (Arthrodesis)",
              BASE + "2025-02/EviCore_CMM-609%20Lumbar%20Fusion_FINAL_V1.0.2025_Pub02.26.2025.pdf"),
    "63030": ("eviCore CMM-606 Lumbar Microdiscectomy (Laminotomy, Laminectomy or Hemilaminectomy)",
              BASE + "2025-03/EviCore_CMM-606%20Lumb%20Microdis_Final_V1.0.2025_Pub03.11.2025.pdf"),
}
REVIEW = {"23472", "27702", "28296"}


KNEE_311 = BY_CPT["27447"][1]


def is_series(title: str, url: str = "") -> bool:
    """A 'series' placeholder row: the title names several eviCore guidelines
    and the URL is the knee one, whatever the operation."""
    t = (title or "").lower()
    return "series" in t and "cmm" in t and (not url or url == KNEE_311)


def main() -> int:
    backup = DIRECTORY.with_suffix(".csv.pre-evicore-series-fix")
    if not backup.exists():
        shutil.copy2(DIRECTORY, backup)
    with DIRECTORY.open(newline="") as f:
        rd = csv.DictReader(f)
        fields, rows = rd.fieldnames, list(rd)
    n_fix = n_rev = 0
    for r in rows:
        if not is_series(r["policy_title"], r["policy_url"]):
            continue
        note = "2026-09-21: series row pointed every operation at CMM-311 (knee)."
        if r["cpt"] in BY_CPT:
            title, url = BY_CPT[r["cpt"]]
            if r["policy_url"] != url or r["policy_title"] != title:
                r["policy_title"], r["policy_url"] = title, url
                r["note"] = f"{note} Now the generic EviCore guideline for this operation. {r['note']}"
                n_fix += 1
        elif r["cpt"] in REVIEW and r["status"] == "VERIFIED":
            r["status"] = "NEEDS REVIEW"
            r["note"] = (f"{note} No plan-agnostic public eviCore guideline verified for this "
                         f"operation; do not cite CMM-311. {r['note']}")
            n_rev += 1
    with DIRECTORY.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"directory: {n_fix} rows re-pointed, {n_rev} marked NEEDS REVIEW")

    gold = json.loads(GOLD.read_text())
    n_gold = 0
    for g in gold["entries"]:
        if is_series(g.get("policy_title", ""), g.get("policy_url", "")) and g.get("cpt") in BY_CPT:
            title, url = BY_CPT[g["cpt"]]
            if g["policy_url"] != url:
                g["policy_url_before_2026_09_21"] = g["policy_url"]
                g["policy_title"], g["policy_url"] = title, url
                n_gold += 1
                print(f"  gold {g['case_id']} {g['payer']} {g['cpt']} -> {title}")
    GOLD.write_text(json.dumps(gold, indent=1))
    print(f"gold: {n_gold} entries corrected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
