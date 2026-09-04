"""Stop abstaining when we are holding the payer's own public policy.

The 2026-09-04 pilot put ChatGPT and OrthoAppeals on the same 60 denial
letters. On six UnitedHealthcare letters ChatGPT returned the payer's real,
current, public policy -- surgery-knee.pdf, surgery-shoulder.pdf,
spinal-fusion-decompression.pdf -- and OrthoAppeals told the patient no
criteria exist. Our research was not wrong: those policies genuinely defer
medical-necessity criteria to InterQual. But we had the document, with its
URL, sitting in the row, and we handed the patient nothing.

Two changes, both reproducible from this script:

1. UnitedHealthcare commercial rows were repointed at the Medicare Advantage
   policies (MMP052.13, MMP089.18) by the 2026-08-26 national-catalog sweep.
   Serving a Medicare Advantage document to a commercial member is the same
   defect we already fixed once for HCSC portals. The correct commercial
   mapping was never lost -- the Oxford rows still carry it -- so those rows
   are repointed from the Oxford mapping for the same CPT.

2. A new status, DOCUMENT PUBLIC, CRITERIA VENDOR-HELD, for rows where the
   payer's applicable policy is public and names the code but sends criteria
   to InterQual or MCG. The app cites the document AND routes for criteria,
   instead of abstaining. A row only qualifies if the document's own audience
   matches the row's plan type; a URL that declares itself Medicare Advantage
   or Medicaid is never served to a commercial member.
"""
from __future__ import annotations

import csv
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

CSV = Path("data/policy_platform/app_option_policy_directory.csv")
NEW_STATUS = "DOCUMENT PUBLIC, CRITERIA VENDOR-HELD"
CANDIDATE_STATUSES = {"NO PUBLIC CRITERIA (vendor)", "CODE ONLY"}
STAMP = "2026-09-04 pilot fix"


def audience(url: str) -> str | None:
    """The plan type a URL declares for itself, if it declares one."""
    u = url.lower()
    if "medadv" in u or "medicare-advantage" in u:
        return "Medicare / Medicare Advantage"
    if "medicaid" in u:
        return "Medicaid"
    if "comm-medical-drug" in u or "/commercial" in u or "comm-plan" in u:
        return "Commercial/ACA"
    return None


def is_document(url: str) -> bool:
    u = url.lower().strip()
    return u.endswith(".pdf") and not re.search(r"index|search|home\.aspx|authtable", u)


def main() -> int:
    rows = list(csv.DictReader(CSV.open()))
    fields = list(rows[0])

    # 1. repoint UHC commercial rows off the Medicare Advantage catalog
    oxford: dict[str, dict] = {}
    for r in rows:
        if (r["insurance_company"] == "UnitedHealthcare / Oxford"
                and r["plan_type"] == "Commercial/ACA"
                and "comm-medical-drug" in r["policy_url"]):
            oxford.setdefault(r["cpt"], r)

    repointed = 0
    for r in rows:
        if (r["plan_type"] == "Commercial/ACA"
                and "UnitedHealthcare" in r["insurance_company"]
                and ("MMP052" in r["policy_title"] or "MMP089" in r["policy_title"])):
            src = oxford.get(r["cpt"])
            if not src:
                continue
            r["policy_title"] = src["policy_title"]
            r["policy_url"] = src["policy_url"]
            r["effective_date"] = src["effective_date"]
            r["note"] = (f"{STAMP}: was pointed at UHC's Medicare Advantage policy, which "
                         f"does not govern a commercial member. Repointed to the commercial "
                         f"policy. " + r["note"])[:1200]
            repointed += 1

    # 2. cite the document we are holding, and still route for the criteria
    promoted = 0
    withheld: Counter = Counter()
    for r in rows:
        if r["status"] not in CANDIDATE_STATUSES or not r["policy_url"].strip():
            continue
        if not is_document(r["policy_url"]):
            withheld["url is not a document"] += 1
            continue
        a = audience(r["policy_url"])
        if a and a != r["plan_type"]:
            withheld[f"document is for {a}, row is {r['plan_type']}"] += 1
            continue
        was = r["status"]
        r["status"] = NEW_STATUS
        r["note"] = (f"{STAMP}: promoted from {was}. The payer's own policy is public and "
                     f"names this code; criteria are vendor-held, so cite the document and "
                     f"route for the criteria. " + r["note"])[:1200]
        promoted += 1

    backup = CSV.with_suffix(".csv.pre-vendor-held-fix")
    if not backup.exists():
        shutil.copy2(CSV, backup)
    with CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f"repointed off the Medicare Advantage catalog : {repointed}")
    print(f"promoted to {NEW_STATUS!r} : {promoted}")
    print("still abstaining, and why:")
    for reason, n in withheld.most_common():
        print(f"   {n:5d}  {reason}")
    print("\nstatus counts now:")
    for s, n in Counter(r["status"] for r in rows).most_common():
        print(f"   {n:5d}  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
