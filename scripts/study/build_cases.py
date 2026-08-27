#!/usr/bin/env python3
"""Build the 200 synthetic denial-letter cases for the validation study.

Protocol (docs: orthoappeals-study-protocol.md): four arms, one case set,
citation validity as the primary endpoint. Cases are drawn ONLY from
(payer, state, procedure) combinations whose governing policy we have
independently fetched and verified, because a case is only scoreable if its
gold answer is real.

Strata (200 total):
  national     120  national payer, policy stable
  regional      40  regional payer with its own policy library
  revised6mo    40  policy revised within the six months before the study date

Everything is deterministic: a fixed RNG seed, sorted candidate lists, and a
frozen study date. Re-running this script byte-reproduces the case file.

Isolation: this script writes TWO files.
  study/cases_v1.json     -- what the arms see. Denial letters and case
                             metadata only. NO policy titles, NO URLs.
  study/gold_key_v1.json  -- what the graders see. The verified governing
                             document per case.
The case file must never contain the answer; test_study.py enforces that.
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "data" / "policy_platform" / "app_option_policy_directory.csv"
OUT_DIR = ROOT / "study"

SEED = 20260827
STUDY_DATE = datetime.date(2026, 8, 27)   # frozen; "current" is judged against this
REVISED_CUTOFF = STUDY_DATE - datetime.timedelta(days=182)

# "National" is judged by footprint, not by brand list: a payer the directory
# tracks in four or more states is a multi-state payer for stratification
# purposes. A fixed brand list undercounted -- UnitedHealthcare and Humana hold
# criteria in InterQual/Cohere and contribute no verified rows, while the
# multi-state Blues (Anthem, Healthy Blue, HCSC) are exactly the "national
# payer, policy stable" cases the protocol meant.
def _national_payers(rows) -> set[str]:
    import collections
    states = collections.defaultdict(set)
    for r in rows:
        states[r["insurance_company"]].add(r["state"])
    return {p for p, st in states.items() if len(st) >= 4}
# Medicare/Medicaid rows are excluded: the app's Medicare answer is often "no
# LCD exists", which is a different kind of gold answer than a citable document
# and would need its own scoring rule. Keep arm comparison clean: commercial
# and regional payers with a real document.

STRATA = {"national": 120, "regional": 40, "revised6mo": 40}

DENIAL_REASONS = [
    ("conservative_care", "the clinical records submitted do not document an "
     "adequate trial of conservative treatment prior to the requested surgery"),
    ("imaging", "the imaging findings submitted do not support the medical "
     "necessity of the requested procedure"),
    ("not_medically_necessary", "the requested procedure does not meet the "
     "plan's criteria for medical necessity"),
    ("incomplete_documentation", "the documentation submitted was incomplete "
     "and does not allow a determination of medical necessity"),
]

FIRST = ["Jordan", "Casey", "Morgan", "Riley", "Avery", "Quinn", "Taylor",
         "Cameron", "Reese", "Rowan", "Skyler", "Emerson"]
LAST = ["Alvarez", "Brooks", "Carter", "Delgado", "Ellison", "Foster",
        "Grant", "Hayes", "Iverson", "Jennings", "Kimura", "Lawson"]


def _parse_eff(raw: str) -> datetime.date | None:
    m = re.search(r"(20\d\d)[-/.](\d\d?)[-/.](\d\d?)", raw)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.search(r"(\d\d?)/(\d\d?)/(20\d\d)", raw)
        if not m:
            return None
        mo, d, y = map(int, m.groups())
    try:
        return datetime.date(y, mo, d)
    except ValueError:
        return None


def _stratum(row: dict, national: set[str]) -> str:
    eff = _parse_eff(row["effective_date"] or "")
    if eff and REVISED_CUTOFF <= eff <= STUDY_DATE:
        return "revised6mo"
    return "national" if row["insurance_company"] in national else "regional"


def _letter(case_id: str, rng: random.Random, row: dict, reason_key: str,
            reason_text: str, denial_date: datetime.date,
            deadline: datetime.date) -> str:
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    member = f"{rng.randint(100, 999)}{rng.randint(100000, 999999)}"
    return (
        f"NOTICE OF ADVERSE BENEFIT DETERMINATION\n\n"
        f"Date of notice: {denial_date.isoformat()}\n"
        f"Member: {name}\n"
        f"Member ID: W{member}\n"
        f"Plan: {row['insurance_company']} ({row['plan_type']}), "
        f"state of {row['state']}\n\n"
        f"Dear {name.split()[0]},\n\n"
        f"We reviewed the prior authorization request submitted by your "
        f"provider for the following service:\n\n"
        f"    Requested service: {row['surgery']}\n"
        f"    Procedure code (CPT): {row['cpt']}\n\n"
        f"After review, this request is DENIED. Reason for determination: "
        f"{reason_text}.\n\n"
        f"This determination was made under the plan's applicable medical "
        f"policy and clinical review criteria. You have the right to appeal "
        f"this decision. Your appeal must be received within 180 days of the "
        f"date of this notice (by {deadline.isoformat()}).\n\n"
        f"Reference number: {case_id.upper()}-{rng.randint(10000, 99999)}\n"
    )


def main() -> None:
    rng = random.Random(SEED)
    with DIRECTORY.open(encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh)
                if r["status"] in ("VERIFIED", "VERIFIED (procedure criteria)")
                and r["policy_url"].strip()
                and r["insurance_company"] not in ("Medicare", "Medicaid")]

    national = _national_payers(rows)
    pools: dict[str, list[dict]] = {k: [] for k in STRATA}
    for r in rows:
        pools[_stratum(r, national)].append(r)
    for pool in pools.values():
        pool.sort(key=lambda r: (r["state"], r["insurance_company"], r["cpt"]))

    # One case per (payer, state, cpt); spread across payers by shuffling the
    # sorted pool with the fixed seed rather than taking the head, so a single
    # alphabetically early payer cannot dominate a stratum.
    cases, gold = [], []
    for stratum, want in STRATA.items():
        pool = pools[stratum][:]
        rng.shuffle(pool)
        if len(pool) < want:
            raise SystemExit(
                f"stratum {stratum}: only {len(pool)} verified candidates for "
                f"{want} cases — refusing to pad from another stratum")
        # Cap any single payer at a quarter of its stratum so one large
        # verified library (Aetna's, in practice) cannot dominate the study.
        cap = max(4, want // 4)
        picked, seen_combo, per_payer = [], set(), {}
        for relax in (False, True):
            for r in pool:
                combo = (r["state"], r["insurance_company"], r["cpt"])
                if combo in seen_combo:
                    continue
                if not relax and per_payer.get(r["insurance_company"], 0) >= cap:
                    continue
                seen_combo.add(combo)
                per_payer[r["insurance_company"]] = per_payer.get(r["insurance_company"], 0) + 1
                picked.append(r)
                if len(picked) == want:
                    break
            if len(picked) == want:
                break
        for i, r in enumerate(picked):
            seed_str = "|".join([str(SEED), stratum, str(i), r["state"],
                                 r["insurance_company"], r["cpt"]])
            case_id = "case-" + hashlib.sha256(seed_str.encode()).hexdigest()[:10]
            reason_key, reason_text = DENIAL_REASONS[len(cases) % len(DENIAL_REASONS)]
            denial_date = STUDY_DATE - datetime.timedelta(days=rng.randint(5, 30))
            deadline = denial_date + datetime.timedelta(days=180)
            cases.append({
                "case_id": case_id,
                "stratum": stratum,
                "state": r["state"],
                "payer": r["insurance_company"],
                "plan_type": r["plan_type"],
                "surgery": r["surgery"],
                "cpt": r["cpt"],
                "denial_reason": reason_key,
                "denial_date": denial_date.isoformat(),
                "appeal_deadline": deadline.isoformat(),
                "letter_text": _letter(case_id, rng, r, reason_key,
                                       reason_text, denial_date, deadline),
            })
            gold.append({
                "case_id": case_id,
                "state": r["state"],
                "payer": r["insurance_company"],
                "cpt": r["cpt"],
                "policy_title": r["policy_title"],
                "policy_url": r["policy_url"],
                "effective_date": r["effective_date"],
                "directory_status": r["status"],
                "directory_note": r["note"],
            })

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "cases_v1.json").write_text(json.dumps({
        "version": 1, "seed": SEED, "study_date": STUDY_DATE.isoformat(),
        "strata": STRATA, "cases": cases}, indent=1), encoding="utf-8")
    (OUT_DIR / "gold_key_v1.json").write_text(json.dumps({
        "version": 1, "seed": SEED, "entries": gold}, indent=1),
        encoding="utf-8")
    import collections
    by = collections.Counter(c["stratum"] for c in cases)
    payers = collections.Counter(c["payer"] for c in cases)
    print(f"wrote {len(cases)} cases -> study/cases_v1.json; gold -> study/gold_key_v1.json")
    print("strata:", dict(by))
    print("top payers:", payers.most_common(8))


if __name__ == "__main__":
    main()
