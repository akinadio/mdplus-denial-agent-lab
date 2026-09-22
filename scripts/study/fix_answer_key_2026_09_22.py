#!/usr/bin/env python3
"""Answer-key corrections from the 2026-09-22 audit of 'equivalent' verdicts.

Every chatbot 'correct' verdict in stratum A was re-derived independently:
does the cited document contain the reviewed criteria of the governing one?
Seventeen did not. Most were another publisher's guideline (fixed in
equivalence.py). Two groups were the answer key's fault:

  Excellus BCBS / 27130   The key said eviCore CMM-313 governs and that
      Excellus publishes no arthroplasty policy. Excellus publishes Medical
      Policy 7.01.96 Hip Arthroplasty (current effective 2026-02-16), with
      criteria and 27130 in its code table. All three chatbots cited it;
      OrthoAppeals cited eviCore. Both documents bear on the denial (eviCore
      administers the review), so either is accepted; the plan's own policy
      becomes the primary answer and the directory row is corrected.

  Centene plans / 63030   (Ambetter IL, Ambetter NC, Oklahoma Complete
      Health, Peach State) The key said Centene's CP.MP.114 governs. Ambetter's
      own provider notices say NIA (now Evolent) manages prior authorization
      for lumbar spine surgery and points providers to NIA's guidelines on
      radmd.com; the directory itself points these plans to Evolent for every
      OTHER surgery. Evolent's Musculoskeletal Surgery Guideline is accepted
      as an alternate governing document; CP.MP.114 stays primary (Ambetter
      'retains medical policies') and the directory rows say both.

Idempotent. Backups written once.
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "study" / "gold.json"
DIRECTORY = ROOT / "data" / "policy_platform" / "app_option_policy_directory.csv"
NOTE = "2026-09-22 answer-key audit: "

EXCELLUS = {
    "policy_url": "https://www.excellusbcbs.com/documents/d/global/exc-prv-hip-arthroplasty-effective-on-2026-02-16-",
    "policy_title": "Excellus BlueCross BlueShield Medical Policy 7.01.96 Hip Arthroplasty",
    "effective_date": "2026-02-16", "vendor": "",
}
EVOLENT = {
    "policy_url": "https://www1.radmd.com/sites/default/files/2026-05/2026%20Evolent%20Musculoskeletal%20Surgery%20Guidelines.pdf",
    "policy_title": "2026 Evolent Clinical Guidelines - Musculoskeletal Surgery", "vendor": "Evolent",
}
CENTENE_63030 = {("Illinois", "Ambetter"), ("North Carolina", "Ambetter (WellCare)"),
                 ("Oklahoma", "Oklahoma Complete Health (Ambetter)"), ("Georgia", "Peach State Health Plan")}


def main() -> int:
    for f in (GOLD, DIRECTORY):
        b = f.with_name(f.name + ".pre-answer-key-audit-2")
        if not b.exists():
            shutil.copy2(f, b)
    gold = json.loads(GOLD.read_text())
    n = 0
    for g in gold["entries"]:
        if g["payer"].startswith("Excellus") and g["cpt"] == "27130" and "excellus" not in g["policy_url"]:
            g["accepted_alternates"] = [{"policy_url": g["policy_url"], "policy_title": g["policy_title"],
                                         "vendor": g.get("vendor") or "eviCore",
                                         "why": "eviCore administers joint-surgery review for Excellus"}]
            g["policy_url_before_2026_09_22"] = g["policy_url"]
            g.update(EXCELLUS)
            g["directory_note"] = NOTE + "Excellus publishes its own Hip Arthroplasty policy 7.01.96; " \
                                  "eviCore CMM-313 accepted as alternate. " + g.get("directory_note", "")
            n += 1
            print(f"  {g['case_id']} Excellus 27130: primary -> 7.01.96, eviCore as alternate")
        key = (g["state"], g["payer"])
        if g["cpt"] == "63030" and "CP.MP.114" in g["policy_url"] and not g.get("accepted_alternates"):
            g["accepted_alternates"] = [dict(EVOLENT, why="NIA/Evolent manages lumbar spine surgery "
                                                            "review for this plan (plan's own notice)")]
            g["directory_note"] = NOTE + "Evolent MSK guideline accepted as alternate (NIA-delegated review). " \
                                  + g.get("directory_note", "")
            n += 1
            print(f"  {g['case_id']} {g['payer']} 63030: Evolent accepted as alternate")
    GOLD.write_text(json.dumps(gold, indent=1))

    with DIRECTORY.open(newline="") as f:
        rd = csv.DictReader(f)
        fields, rows = rd.fieldnames, list(rd)
    m = 0
    for r in rows:
        if r["insurance_company"].startswith("Excellus") and r["cpt"] == "27130" and "excellus" not in r["policy_url"]:
            r["note"] = (NOTE + f"was {r['policy_url']} (eviCore CMM-313, which administers review); "
                         "Excellus publishes its own policy 7.01.96, which the appeal should quote. " + r["note"])
            r["policy_url"], r["policy_title"], r["effective_date"] = \
                EXCELLUS["policy_url"], EXCELLUS["policy_title"], EXCELLUS["effective_date"]
            m += 1
        if r["cpt"] == "63030" and "CP.MP.114" in r["policy_url"] and NOTE not in r["note"]:
            r["note"] = (NOTE + "NIA/Evolent manages lumbar spine surgery review for Ambetter plans; "
                         "Evolent's MSK guideline (radmd.com) applies alongside CP.MP.114. " + r["note"])
            m += 1
    with DIRECTORY.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"gold: {n} entries; directory: {m} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
