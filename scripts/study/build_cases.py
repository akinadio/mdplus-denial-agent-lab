#!/usr/bin/env python3
"""Build the proof-of-concept case set: two strata, per Kassam 2026-08-30.

Kassam's rulings on the protocol draft:
  - "Fine to include ones we don't have" -> stratum C is back. The claim that
    OrthoAppeals declines instead of hallucinating is only testable on cases
    where it holds nothing, so those cases have to be in the set.
  - "We should use the tier we are using in the final product and compare to
    the free versions of others."
  - "[one comparator first] Yes that's fine. If it works we can expand."

Two strata:
  A  in_library   40  OrthoAppeals holds a verified public policy.
                      Correct answer = that document.
  C  no_policy    20  The payer keeps criteria in InterQual/MCG/a portal and
                      publishes none. Correct answer = say no public criteria
                      exist and give the route to demand them. Naming any
                      specific governing document is a failure.

Stratum C's gold answer is an ABSTENTION plus a route, not a URL, so the
scorer needs a different rule for it -- see score.py.

Writes:
  study/cases.json     what the tools see. Letters only, no answers.
  study/gold.json      what the grader sees.
"""
from __future__ import annotations
import csv, datetime, hashlib, json, random, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "data" / "policy_platform" / "app_option_policy_directory.csv"
OUT = ROOT / "study"

SEED = 20260830
STUDY_DATE = datetime.date(2026, 8, 30)
WANT = {"in_library": 30, "vendor_held": 15, "no_policy": 15}

# Statuses that mean "this payer publishes no public criteria for this code."
NO_POLICY_STATUS = {"NO PUBLIC CRITERIA (vendor)", "GATED"}
IN_LIB_STATUS = {"VERIFIED", "VERIFIED (procedure criteria)"}
# The middle case the first pilot had no name for: the payer's policy is public
# and names the code, but the criteria themselves are vendor-held. Correct
# behavior is both halves -- cite the document, route for the criteria.
VENDOR_HELD_STATUS = {"DOCUMENT PUBLIC, CRITERIA VENDOR-HELD"}

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
FIRST = ["Jordan","Casey","Morgan","Riley","Avery","Quinn","Taylor","Cameron",
         "Reese","Rowan","Skyler","Emerson","Harper","Sawyer"]
LAST = ["Alvarez","Brooks","Carter","Delgado","Ellison","Foster","Grant",
        "Hayes","Iverson","Jennings","Kimura","Lawson","Mercado","Novak"]


def _vendor_from_note(note: str) -> str:
    for v in ("InterQual","MCG","eviCore","Carelon","Evolent","TurningPoint",
              "Cohere","HealthHelp","Podiatry Network Solutions"):
        if v.lower() in (note or "").lower():
            return v
    return ""


def _letter(rng, row, reason_text, denial_date, deadline, ref):
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    member = f"{rng.randint(100,999)}{rng.randint(100000,999999)}"
    return (
        "NOTICE OF ADVERSE BENEFIT DETERMINATION\n\n"
        f"Date of notice: {denial_date.isoformat()}\n"
        f"Member: {name}\nMember ID: W{member}\n"
        f"Plan: {row['insurance_company']} ({row['plan_type']}), "
        f"state of {row['state']}\n\n"
        f"Dear {name.split()[0]},\n\n"
        "We reviewed the prior authorization request submitted by your provider "
        "for the following service:\n\n"
        f"    Requested service: {row['surgery']}\n"
        f"    Procedure code (CPT): {row['cpt']}\n\n"
        f"After review, this request is DENIED. Reason for determination: "
        f"{reason_text}.\n\n"
        "This determination was made under the plan's applicable medical policy "
        "and clinical review criteria. You have the right to appeal this "
        "decision. Your appeal must be received within 180 days of the date of "
        f"this notice (by {deadline.isoformat()}).\n\n"
        f"Reference number: {ref}\n")


def _pick(pool, want, rng, cap_per_payer):
    rng.shuffle(pool)
    out, seen, per = [], set(), {}
    for relax in (False, True):
        for r in pool:
            k = (r["state"], r["insurance_company"], r["cpt"])
            if k in seen:
                continue
            if not relax and per.get(r["insurance_company"], 0) >= cap_per_payer:
                continue
            seen.add(k)
            per[r["insurance_company"]] = per.get(r["insurance_company"], 0) + 1
            out.append(r)
            if len(out) == want:
                return out
        if len(out) == want:
            break
    return out


def refresh_gold() -> None:
    """Re-derive gold.json for the EXISTING cases from the directory as it
    stands, without re-sampling.

    The fixes step promotes rows -- a page that turns out to name the code and
    state criteria moves from no_policy to vendor_held -- and when that happens
    to a sampled row, the correct behavior for that case changes. Re-sampling
    would throw away the paid ChatGPT retrieval runs; the letters are the same
    letters, so only the answer key needs to move. A case whose stratum changes
    keeps its original under `stratum_sampled`, so the shift is visible."""
    doc = json.loads((OUT / "cases.json").read_text())
    gold_old = {g["case_id"]: g for g in json.loads((OUT / "gold.json").read_text())["entries"]}
    with DIRECTORY.open(encoding="utf-8", newline="") as fh:
        rows = {(r["state"], r["insurance_company"], r["cpt"]): r for r in csv.DictReader(fh)}
    entries, moved = [], []
    for c in doc["cases"]:
        r = rows[(c["state"], c["payer"], c["cpt"])]
        st = r["status"]
        if st in IN_LIB_STATUS and r["policy_url"].strip():
            stratum, beh = "in_library", "cite_document"
        elif st in VENDOR_HELD_STATUS and r["policy_url"].strip():
            stratum, beh = "vendor_held", "cite_and_route"
        elif st in NO_POLICY_STATUS:
            stratum, beh = "no_policy", "abstain_and_route"
        else:
            stratum, beh = c["stratum"], gold_old[c["case_id"]]["correct_behavior"]
        g = {"case_id": c["case_id"], "stratum": stratum, "state": r["state"],
             "payer": r["insurance_company"], "cpt": r["cpt"],
             "directory_status": st, "directory_note": r["note"],
             "correct_behavior": beh, "vendor": _vendor_from_note(r["note"]),
             "policy_title": r["policy_title"] if beh != "abstain_and_route" else "",
             "policy_url": r["policy_url"] if beh != "abstain_and_route" else "",
             "effective_date": r["effective_date"] if beh != "abstain_and_route" else ""}
        if stratum != c["stratum"]:
            moved.append((c["case_id"], c["stratum"], stratum))
            c.setdefault("stratum_sampled", c["stratum"])
            c["stratum"] = stratum
        entries.append(g)
    (OUT / "gold.json").write_text(json.dumps(
        {"version": "poc-1", "seed": SEED, "refreshed": datetime.date.today().isoformat(),
         "entries": entries}, indent=1), encoding="utf-8")
    (OUT / "cases.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"gold refreshed for {len(entries)} cases; {len(moved)} changed stratum")
    for cid, a, b in moved:
        print(f"  {cid}: {a} -> {b}")


def main() -> None:
    if "--refresh-gold" in sys.argv:
        refresh_gold()
        return
    rng = random.Random(SEED)
    with DIRECTORY.open(encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh)
                if r["insurance_company"] not in ("Medicare", "Medicaid")]

    in_lib = [r for r in rows if r["status"] in IN_LIB_STATUS and r["policy_url"].strip()]
    no_pol = [r for r in rows if r["status"] in NO_POLICY_STATUS and r["note"].strip()]
    vend = [r for r in rows if r["status"] in VENDOR_HELD_STATUS and r["policy_url"].strip()]
    for p in (in_lib, no_pol, vend):
        p.sort(key=lambda r: (r["state"], r["insurance_company"], r["cpt"]))

    picked = {
        "in_library":  _pick(in_lib, WANT["in_library"],  rng, 6),
        "vendor_held": _pick(vend,   WANT["vendor_held"], rng, 4),
        "no_policy":   _pick(no_pol, WANT["no_policy"],   rng, 4),
    }
    for k, v in picked.items():
        if len(v) < WANT[k]:
            raise SystemExit(f"{k}: only {len(v)} candidates for {WANT[k]}")

    cases, gold = [], []
    for stratum in ("in_library", "vendor_held", "no_policy"):
        for i, r in enumerate(picked[stratum]):
            seed_str = "|".join([str(SEED), stratum, str(i), r["state"],
                                 r["insurance_company"], r["cpt"]])
            cid = "poc-" + hashlib.sha256(seed_str.encode()).hexdigest()[:10]
            reason_key, reason_text = DENIAL_REASONS[len(cases) % 4]
            dd = STUDY_DATE - datetime.timedelta(days=rng.randint(5, 30))
            dl = dd + datetime.timedelta(days=180)
            ref = f"{cid.upper()}-{rng.randint(10000,99999)}"
            cases.append({
                "case_id": cid, "stratum": stratum,
                "state": r["state"], "payer": r["insurance_company"],
                "plan_type": r["plan_type"], "surgery": r["surgery"],
                "cpt": r["cpt"], "denial_reason": reason_key,
                "denial_date": dd.isoformat(),
                "appeal_deadline": dl.isoformat(),
                "letter_text": _letter(rng, r, reason_text, dd, dl, ref),
            })
            g = {"case_id": cid, "stratum": stratum, "state": r["state"],
                 "payer": r["insurance_company"], "cpt": r["cpt"],
                 "directory_status": r["status"], "directory_note": r["note"]}
            if stratum == "in_library":
                g.update({"correct_behavior": "cite_document",
                          "policy_title": r["policy_title"],
                          "policy_url": r["policy_url"],
                          "effective_date": r["effective_date"]})
            elif stratum == "vendor_held":
                g.update({"correct_behavior": "cite_and_route",
                          "vendor": _vendor_from_note(r["note"]),
                          "policy_title": r["policy_title"],
                          "policy_url": r["policy_url"],
                          "effective_date": r["effective_date"],
                          "why_criteria_withheld": r["note"][:400]})
            else:
                g.update({"correct_behavior": "abstain_and_route",
                          "vendor": _vendor_from_note(r["note"]),
                          "policy_url": "", "policy_title": "",
                          "why_no_public_policy": r["note"][:400]})
            gold.append(g)

    OUT.mkdir(exist_ok=True)
    (OUT / "cases.json").write_text(json.dumps(
        {"version": "poc-1", "seed": SEED, "study_date": STUDY_DATE.isoformat(),
         "strata": WANT, "cases": cases}, indent=1), encoding="utf-8")
    (OUT / "gold.json").write_text(json.dumps(
        {"version": "poc-1", "seed": SEED, "entries": gold}, indent=1),
        encoding="utf-8")

    import collections
    print(f"{len(cases)} cases -> study/cases.json")
    print(" strata:", dict(collections.Counter(c["stratum"] for c in cases)))
    print(" payers:", collections.Counter(c["payer"] for c in cases).most_common(6))
    print(" vendors in stratum C:",
          dict(collections.Counter(g.get("vendor","?") for g in gold
                                   if g["stratum"]=="no_policy")))
    print(" vendors in stratum D:",
          dict(collections.Counter(g.get("vendor","") for g in gold
                                   if g["stratum"]=="vendor_held")))


if __name__ == "__main__":
    main()
