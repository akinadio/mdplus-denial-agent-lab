#!/usr/bin/env python3
"""Score blinded study runs against the gold key.

Primary endpoint, four binary checks per the protocol -- ALL must pass for a
citation to count as valid:
  1. exists        the cited URL resolves to a real document
  2. right_payer   the document belongs to the case's payer (or its named
                   delegated vendor)
  3. right_code    the document covers the case's CPT
  4. current       the document was the current edition on the denial date

Two scoring modes:
  --mode offline   checks 2-4 against the gold key and verification ledger
                   only; check 1 is scored from the ledger when the URL is
                   known to us, else left as None ("needs fetch"). Runs with
                   no network and is fully reproducible.
  --mode live      additionally fetches unknown URLs to settle check 1.
                   (Requires network; used for the real scoring pass.)

The scorer walks study/runs/ by blinded run id and NEVER reads
study/unblinding_map.json -- analyze.py does the join after scoring closes.
A test enforces that this module does not even reference that filename.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from synthetic_harness.citation_cache import _normalize_url, verdict_for  # noqa: E402

STUDY = ROOT / "study"
GOLD = STUDY / "gold_key_v1.json"
CASES = STUDY / "cases_v1.json"
RUNS = STUDY / "runs"


def score_run(answer: dict, case: dict, gold: dict) -> dict:
    url = (answer.get("policy_url") or "").strip()
    checks: dict[str, bool | None] = {
        "exists": None, "right_payer": None, "right_code": None, "current": None}
    detail = []

    if not url:
        # No citation at all fails the endpoint outright.
        checks = {k: False for k in checks}
        detail.append("no URL cited")
        return {"checks": checks, "valid": False, "detail": detail,
                "matched_gold": False}

    matched_gold = _normalize_url(url) == _normalize_url(gold["policy_url"])
    if matched_gold:
        # The gold document was itself verified by fetch for this payer+code
        # and is the current edition on file -- all four checks pass.
        checks = {k: True for k in checks}
        detail.append("cited the gold document")
        return {"checks": checks, "valid": True, "detail": detail,
                "matched_gold": True}

    # Not the gold URL. It may still be a valid citation (a payer can have
    # more than one legitimate route to its criteria), so consult our own
    # verification record before condemning it.
    found = verdict_for(url, case["cpt"])
    if found:
        verdict, note = found
        detail.append(f"ledger verdict for this URL+CPT: {verdict}")
        if verdict == "verified":
            checks["exists"] = True
            checks["right_code"] = True
            # Payer match: the ledger row was recorded for a specific payer;
            # our per-(url,cpt) index does not carry payer, so leave for the
            # human pass unless it is the gold payer's own domain.
            checks["right_payer"] = None
            checks["current"] = None
            detail.append("verified for this CPT but not the gold URL -- "
                          "needs a human look at payer and edition")
        elif verdict in ("stale_superseded",):
            checks["exists"] = True
            checks["current"] = False
            detail.append("cites a superseded edition")
        elif verdict in ("rejected_code_only", "no_procedure_specific_criteria"):
            checks["exists"] = True
            checks["right_code"] = False
        elif verdict in ("not_found", "unreachable"):
            checks["exists"] = None
            detail.append("URL not in ledger as fetchable -- needs live fetch")
        else:
            checks["exists"] = True
            detail.append(f"ledger: {verdict}")
    else:
        detail.append("URL unknown to our verification record -- needs live "
                      "fetch (mode=live) and a human pass")

    definite_fail = any(v is False for v in checks.values())
    valid = all(v is True for v in checks.values())
    return {"checks": checks, "valid": valid if not definite_fail else False,
            "detail": detail, "matched_gold": False,
            "needs_human": any(v is None for v in checks.values())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["offline", "live"], default="offline")
    args = ap.parse_args()
    if args.mode == "live":
        raise SystemExit("live mode is intentionally not implemented yet: it "
                         "fetches third-party URLs and belongs to the real "
                         "scoring pass, run deliberately, not by default")

    gold = {g["case_id"]: g for g in json.loads(GOLD.read_text())["entries"]}
    cases = {c["case_id"]: c for c in json.loads(CASES.read_text())["cases"]}
    # Blinded: we know each run's case (the letter is in the run input) but
    # not its arm. case_id is recoverable from the result's own metadata.
    out = {}
    for result_path in sorted(RUNS.glob("run-*/result.json")):
        res = json.loads(result_path.read_text())
        rid = res.get("run_id") or result_path.parent.name
        case_id = res.get("case_id")
        if not case_id:
            out[rid] = {"status": "malformed result: no case_id"}
            continue
        if "skipped" in res or "error" in res:
            out[rid] = {"case_id": case_id, "status": res.get("skipped") or res.get("error")}
            continue
        s = score_run(res.get("answer") or {}, cases[case_id], gold[case_id])
        s["case_id"] = case_id
        out[rid] = s
    (STUDY / "scores_v1.json").write_text(json.dumps(out, indent=1))
    n = len(out)
    valid = sum(1 for s in out.values() if s.get("valid"))
    human = sum(1 for s in out.values() if s.get("needs_human"))
    print(f"scored {n} runs -> study/scores_v1.json | valid={valid} "
          f"needs_human={human}")


if __name__ == "__main__":
    main()
