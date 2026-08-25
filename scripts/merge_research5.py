#!/usr/bin/env python3
"""Merge the research5 sweeps into the app-option policy directory.

Four sweeps land here:
  notfound_resolution.json  -- the 40 rows that carried no note at all
  carelon_small_joint.json  -- whether payers actually bought Carelon's
                               separately-sold Small Joint Surgery module
  horizontal_libraries.json -- walking 14 payer policy libraries end to end
  imaging.json              -- the new advanced-imaging procedure area,
                               merged separately by add_imaging.py

A merge only ever overwrites a cell when the new finding is at least as
settled as what is already there. A VERIFIED cell is never downgraded by
this script.
"""
import csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAT = ROOT / "data" / "policy_platform"
CSV_PATH = PLAT / "app_option_policy_directory.csv"
R5 = PLAT / "research5"

VERDICT_TO_STATUS = {
    "verified": "VERIFIED",
    "no_prior_auth_required": "NO PRIOR AUTH REQUIRED",
    "no_procedure_specific_criteria": "CONFIRMED NO POLICY",
    "criteria_proprietary_not_public": "NO PUBLIC CRITERIA (vendor)",
    "gated_login": "GATED",
    "unreachable": "UNREACHABLE",
    "stale_superseded": "STALE",
    "rejected_code_only": "CODE ONLY",
    "not_found": "NOT FOUND",
}

# How settled each status is. A merge is refused if it would lower this.
RANK = {
    "VERIFIED": 100, "VERIFIED (CMS LCD/NCD)": 100,
    "VERIFIED (state Medicaid doc)": 100, "VERIFIED (procedure criteria)": 100,
    "VERIFIED (criteria public, no stable link)": 95,
    "CRITERIA EXIST, TEXT NOT EXTRACTED": 90,
    "NO PRIOR AUTH REQUIRED": 85,
    "NO LCD — general medical necessity": 80,
    "CONFIRMED NO POLICY": 70,
    "NO PUBLIC CRITERIA (vendor)": 60,
    "PROCESS DOC ONLY (no procedure criteria)": 50,
    "GATED": 40, "STALE": 35, "CODE ONLY": 30, "UNREACHABLE": 25,
    "NOT FOUND": 10, "NOT RESEARCHED": 0,
}

DATE = "2026-08-25"


def load(name):
    p = R5 / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"findings": []}


def note_for(f, prefix):
    bits = [f"{DATE} {prefix}"]
    if f.get("policy_number"):
        bits.append(f"policy {f['policy_number']}")
    if f.get("vendor"):
        bits.append(f"vendor: {f['vendor']}")
    if f.get("criteria_quote"):
        bits.append(f"criteria: “{f['criteria_quote']}”")
    if f.get("evidence"):
        bits.append(f["evidence"])
    if f.get("warning"):
        bits.append(f"WARNING: {f['warning']}")
    if f.get("confidence"):
        bits.append(f"confidence: {f['confidence']}")
    return ". ".join(bits)


def apply(rows, match, f, prefix, dry):
    """match(row) -> bool. Returns number of rows changed."""
    status = VERDICT_TO_STATUS[f["verdict"]]
    changed = 0
    for r in rows:
        if not match(r):
            continue
        if RANK.get(status, 0) < RANK.get(r["status"], 0):
            continue
        if status == r["status"] and r["policy_url"] == f.get("policy_url", "") and r["note"]:
            continue
        if not dry:
            r["status"] = status
            r["policy_title"] = f.get("policy_title", "") or r["policy_title"]
            r["effective_date"] = f.get("effective_date", "") or r["effective_date"]
            r["policy_url"] = f.get("policy_url", "")
            r["note"] = note_for(f, prefix)
        changed += 1
    return changed


def main(dry=False):
    with CSV_PATH.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        rows = list(reader)

    total = 0

    # --- Sweep 1: the 40 rows that carried no note -----------------------
    nf = {x["question"]: x for x in load("notfound_resolution.json")["findings"]}
    total += apply(rows, lambda r: r["insurance_company"] == "Cigna" and r["cpt"] == "28296",
                   nf["cigna_28296"], "Cigna national sweep", dry)
    total += apply(rows, lambda r: r["insurance_company"] == "Florida Blue" and r["cpt"] == "23472",
                   dict(nf["florida_blue_23472"], verdict="no_procedure_specific_criteria"),
                   "Florida Blue master index enumeration", dry)
    total += apply(rows, lambda r: r["insurance_company"] == "Aetna Better Health of West Virginia"
                   and r["cpt"] == "29827",
                   nf["abhwv_29827"], "ABHWV sweep", dry)

    # --- Sweep 2: Carelon Small Joint delegation -------------------------
    CARELON_PAYER = {
        "Blue Cross and Blue Shield of Illinois": ("Illinois", "Blue Cross Blue Shield of Illinois"),
        "Blue Cross Blue Shield of Montana": ("Montana", "Blue Cross Blue Shield of Montana"),
        "Blue Cross Blue Shield of New Mexico": ("New Mexico", "Blue Cross Blue Shield of New Mexico"),
        "Blue Cross Blue Shield of Oklahoma": ("Oklahoma", "Blue Cross Blue Shield of Oklahoma"),
        "Blue Cross Blue Shield of Texas": ("Texas", "Blue Cross Blue Shield of Texas"),
        "AmeriHealth New Jersey": ("New Jersey", "AmeriHealth New Jersey"),
        "Independence Blue Cross": ("Pennsylvania", "Independence Blue Cross"),
        "Simply Healthcare": ("Florida", "Simply Healthcare"),
        "Blue Cross and Blue Shield of Louisiana": ("Louisiana", "Blue Cross and Blue Shield of Louisiana"),
        "UniCare Health Plan of West Virginia": ("West Virginia", "UniCare Health Plan of West Virginia"),
    }
    for f in load("carelon_small_joint.json")["findings"]:
        key = CARELON_PAYER.get(f["payer"])
        if not key:
            continue  # Idaho / Dean stay unreachable, already labelled
        st, ins = key
        for cpt in f["cpt"].split(","):
            cpt = cpt.strip()
            total += apply(rows,
                           lambda r, st=st, ins=ins, cpt=cpt: r["state"] == st
                           and r["insurance_company"] == ins and r["cpt"] == cpt,
                           f, "Carelon module-scope check", dry)

    # --- Sweep 3: payer library walks ------------------------------------
    LIB_PAYER = {
        "Premera Blue Cross": [("Washington", "Premera Blue Cross"),
                               ("Alaska", "Premera Blue Cross Blue Shield of Alaska")],
        "Blue Shield of California": [("California", "Blue Shield of California")],
        "Capital Blue Cross": [("Pennsylvania", "Capital Blue Cross")],
        "CareFirst BlueCross BlueShield": [("Maryland", "CareFirst BlueCross BlueShield"),
                                           ("District of Columbia", "CareFirst BlueCross BlueShield"),
                                           ("Virginia", "CareFirst BlueCross BlueShield")],
        "Blue Cross Blue Shield of Michigan": [("Michigan", "Blue Cross Blue Shield of Michigan")],
        "Priority Health": [("Michigan", "Priority Health")],
        "Medical Mutual of Ohio": [("Ohio", "Medical Mutual of Ohio")],
        "Blue Cross Blue Shield of Kansas City (Blue KC)": [
            ("Kansas", "Blue Cross and Blue Shield of Kansas City"),
            ("Missouri", "Blue Cross and Blue Shield of Kansas City")],
        "Blue Cross and Blue Shield of Minnesota": [("Minnesota", "Blue Cross and Blue Shield of Minnesota")],
        "HealthPartners": [("Minnesota", "HealthPartners")],
        "Blue Cross Blue Shield of Arizona": [("Arizona", "Blue Cross Blue Shield of Arizona")],
        "Moda Health": [("Oregon", "Moda Health"), ("Alaska", "Moda Health")],
        "Providence Health Plan": [("Oregon", "Providence Health Plan")],
        "Blue Cross Blue Shield of Wyoming": [("Wyoming", "Blue Cross Blue Shield of Wyoming")],
    }
    for f in load("horizontal_libraries.json")["findings"]:
        for st, ins in LIB_PAYER.get(f["payer"], []):
            total += apply(rows,
                           lambda r, st=st, ins=ins, f=f: r["state"] == st
                           and r["insurance_company"] == ins and r["cpt"] == f["cpt"],
                           f, "payer library walk", dry)

    if not dry:
        with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    print(f"{'would change' if dry else 'changed'}: {total} rows")


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
