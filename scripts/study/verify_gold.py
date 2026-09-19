#!/usr/bin/env python3
"""Check the answer key against the live documents, not against our own CSV.

WHY THIS EXISTS.

Until 2026-09-19 "correct" meant "matches data/policy_platform/
app_option_policy_directory.csv". Two things followed from that, and both were
invisible:

  1. run_ortho() returns row["policy_url"] from that CSV and refresh_gold()
     writes row["policy_url"] into the answer key -- the same field of the same
     row. The OrthoAppeals URL equalled the gold URL byte for byte in 60 of 60
     cases. That arm could not be scored wrong. Its 100% was a tautology.
  2. The 60 cases were SAMPLED from that CSV, and the strata are its own
     `status` column, so library coverage was 100% by design as well.

The chatbot arms did have to find the document from scratch, so their scores
are real measurements -- but only if the key is true. This script is what makes
it true: it fetches every document the key names and asks whether that document
actually exists and actually governs the denied code.

WHAT EACH VERDICT MEANS.

  verified          the document resolves, names this procedure, and states
                    criteria for it. A usable key entry.
  criteria_absent   resolves and names the procedure, but no criteria are in
                    it. This is WRONG for in_library and RIGHT for vendor_held
                    -- the whole point of that stratum is that InterQual or MCG
                    holds the criteria -- so it is reported per stratum.
  procedure_absent  resolves, but never mentions the code or the procedure.
                    The key entry is probably pointing at the wrong document.
  unreachable       404, blocked, or empty. Cannot be used as a key, and if
                    OrthoAppeals is citing it, the app is handing patients a
                    dead link.
  no_url            stratum C. Nothing to fetch: the claim is that the payer
                    publishes nothing, which cannot be confirmed by fetching a
                    document. This stratum's key still rests on our research
                    note, and the write-up has to say so.

  python3 scripts/study/verify_gold.py                 # all of them
  python3 scripts/study/verify_gold.py --workers 6     # faster
  python3 scripts/study/verify_gold.py --refresh       # ignore the cache
"""
from __future__ import annotations
import argparse
import json
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from synthetic_harness.policy_text import (  # noqa: E402
    PROCEDURE_TERMS, find_criteria, policy_text,
)

STUDY = ROOT / "study"
OUT = STUDY / "gold_verification.json"


def names_procedure(text: str, cpt: str) -> bool:
    low = (text or "").lower()
    if cpt and cpt in text:
        return True
    return any(t in low for t in PROCEDURE_TERMS.get(cpt, []))


def verify_one(entry: dict, refresh: bool) -> dict:
    url = (entry.get("policy_url") or "").strip()
    cpt = entry.get("cpt", "")
    base = {"case_id": entry["case_id"], "stratum": entry["stratum"],
            "payer": entry.get("payer", ""), "cpt": cpt, "policy_url": url}
    if not url:
        return {**base, "verdict": "no_url",
                "detail": "stratum C: the claim is that nothing is published, "
                          "which no fetch can confirm"}
    got = policy_text(url, refresh=refresh)
    text = got.get("text") or ""
    if not text.strip():
        return {**base, "verdict": "unreachable",
                "detail": f"status={got.get('status')} {str(got.get('error') or '')[:120]}"}
    if not names_procedure(text, cpt):
        # For vendor_held this is the EXPECTED shape, not a failure. Reading
        # the five flagged on 2026-09-19 settled it: UPMC's "Provider Manual
        # Chapter G - Utilization Management" and MedStar's "Utilization
        # Management Criteria" are the payer's general UM process documents.
        # They carry no CPT codes and never mention the procedure, because the
        # procedure-level criteria are exactly what InterQual or MCG holds.
        # That is the definition of the stratum, so it is recorded as such.
        if entry["stratum"] == "vendor_held":
            return {**base, "verdict": "vendor_shaped", "chars": len(text),
                    "detail": "generic UM document, no procedure-level criteria "
                              "-- which is what vendor-held means"}
        return {**base, "verdict": "procedure_absent", "chars": len(text),
                "detail": f"document never mentions CPT {cpt} or any of "
                          f"{PROCEDURE_TERMS.get(cpt, [])[:3]}"}
    quotes = find_criteria(text, cpt)
    if not quotes:
        return {**base, "verdict": "criteria_absent", "chars": len(text),
                "detail": "names the procedure, no criteria sentences extractable"}
    if entry["stratum"] == "vendor_held":
        # The opposite worry: a vendor_held document that DOES yield criteria is
        # either mis-stratified, or find_criteria is inventing criteria out of
        # headers. On 2026-09-19 it was the second -- all ten were UnitedHealthcare
        # policies whose "criteria" came back as "Coverage Rationale ... is proven
        # and medically necessary in certain circumstances", which states no rule
        # at all. Flagged for reading, never silently accepted.
        return {**base, "verdict": "vendor_but_criteria_found", "chars": len(text),
                "n_criteria": len(quotes), "first_criterion": quotes[0][:200],
                "detail": "vendor-held by the key, yet criteria were extracted -- "
                          "read them: is the stratum wrong, or is the extractor "
                          "picking up headers?"}
    return {**base, "verdict": "verified", "chars": len(text),
            "n_criteria": len(quotes), "first_criterion": quotes[0][:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()

    entries = json.loads((STUDY / "gold.json").read_text())["entries"]
    lock = threading.Lock()
    results = []

    def one(e):
        r = verify_one(e, a.refresh)
        with lock:
            results.append(r)
            print(f"  {r['case_id']} {r['stratum']:11s} {r['verdict']:16s} "
                  f"{r.get('payer','')[:28]:28s} {str(r.get('detail',''))[:60]}",
                  flush=True)
        return r

    if a.workers > 1:
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            list(pool.map(one, entries))
    else:
        for e in entries:
            one(e)

    results.sort(key=lambda r: r["case_id"])
    by = {}
    for r in results:
        by.setdefault(r["stratum"], Counter())[r["verdict"]] += 1
    OUT.write_text(json.dumps({"entries": results}, indent=1))

    print("\nBY STRATUM")
    for st in ("in_library", "vendor_held", "no_policy"):
        c = by.get(st, Counter())
        print(f"  {st:11s} " + "  ".join(f"{k}={v}" for k, v in c.most_common()))
    print("\nWHAT COUNTS AS A USABLE KEY ENTRY")
    il = by.get("in_library", Counter())
    vh = by.get("vendor_held", Counter())
    print(f"  in_library  {il['verified']}/30 verified: the document resolves, "
          f"names the procedure, and states criteria for it")
    print(f"  vendor_held {vh['vendor_shaped']}/15 are shaped like vendor-held "
          f"(generic UM document, no procedure criteria) -- the expected state")
    if vh["vendor_but_criteria_found"]:
        print(f"              {vh['vendor_but_criteria_found']} yielded criteria "
              f"anyway and NEED READING (stratum wrong, or extractor picking up "
              f"headers)")
    print(f"  no_policy   {by.get('no_policy', Counter())['no_url']}/15 cannot be "
          f"confirmed by fetching anything, by definition. This stratum's key "
          f"rests on our research note and the write-up must say so.")
    bad = [r for r in results
           if r["verdict"] in ("unreachable", "procedure_absent",
                               "vendor_but_criteria_found")]
    if bad:
        print(f"\n{len(bad)} KEY ENTRIES DO NOT HOLD UP -- these cases cannot "
              f"score any arm until they are fixed or dropped:")
        for r in bad:
            print(f"  {r['case_id']} {r['payer'][:30]:30s} {r['verdict']:16s} "
                  f"{r['policy_url'][:70]}")
        print("\nNote: OrthoAppeals cites these same URLs, so an 'unreachable' "
              "here is also a dead link the app would hand a patient.")
    print(f"\nwritten -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
