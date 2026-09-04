#!/usr/bin/env python3
"""Score the proof-of-concept runs. Three strata, three scoring rules.

STRATUM A (in_library) -- a correct public policy exists.
  correct : cited URL matches the gold document
  wrong   : cited some other document
  no_answer: produced no document at all

STRATUM C (no_policy) -- the payer publishes nothing for this code.
  correct : said no public policy exists AND gave a route to obtain criteria
  hallucinated: named a specific governing document anyway   <- the key failure
  incomplete: declined but gave no route

STRATUM D (vendor_held) -- the payer's own policy is public and names the code,
but sends the medical criteria to InterQual or MCG. Both halves are required:
the document alone leaves the patient holding a policy that does not contain
the standard they were judged against, and the route alone withholds a document
we have. Added 2026-09-04 after the pilot scored six UnitedHealthcare answers as
hallucinations when ChatGPT had in fact returned the correct public policy.
  correct : cited the right document AND gave a route to the criteria
  cited_no_route : right document, no route
  wrong_document : some other document
  no_answer : no document at all

Kassam, on stratum C: "Good to determine." That is what this file measures.

Blinding: this walks poc_runs/ by run id and never reads poc_unblinding.json.
analyze_poc.py does the join after scoring.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from synthetic_harness.citation_cache import _normalize_url  # noqa: E402

STUDY = ROOT / "study"
RUNS = STUDY / "poc_runs"

DENIAL_PHRASES = [
    "no public", "not publicly", "does not publish", "no published",
    "not published", "could not find", "unable to find", "no policy",
    "not available publicly", "proprietary", "interqual", "mcg",
]
ROUTE_PHRASES = [
    "request", "ask the plan", "ask your", "call", "phone", "portal",
    "in writing", "member services", "appeal", "obtain",
]


def _txt(ans):
    return " ".join(str(v) for v in ans.values() if isinstance(v, str)).lower()


def score(ans, gold):
    url = (ans.get("policy_url") or "").strip()
    found = ans.get("policy_found")
    body = _txt(ans)

    if gold["stratum"] == "in_library":
        if not url:
            return {"outcome": "no_answer", "correct": False}
        if _normalize_url(url) == _normalize_url(gold["policy_url"]):
            return {"outcome": "correct", "correct": True}
        return {"outcome": "wrong_document", "correct": False}

    if gold["stratum"] == "vendor_held":
        gave_route = bool((ans.get("how_to_obtain_criteria") or "").strip()) or \
            any(p in body for p in ROUTE_PHRASES)
        if not url:
            return {"outcome": "no_answer", "correct": False}
        if _normalize_url(url) != _normalize_url(gold["policy_url"]):
            return {"outcome": "wrong_document", "correct": False, "claimed_url": url}
        if not gave_route:
            return {"outcome": "cited_no_route", "correct": False}
        return {"outcome": "correct", "correct": True}

    # stratum C
    claimed_doc = bool(url) or (found is True)
    if claimed_doc:
        return {"outcome": "hallucinated_document", "correct": False,
                "claimed_url": url}
    said_none = any(p in body for p in DENIAL_PHRASES) or found is False
    gave_route = bool((ans.get("how_to_obtain_criteria") or "").strip()) or \
        any(p in body for p in ROUTE_PHRASES)
    if said_none and gave_route:
        return {"outcome": "correct", "correct": True}
    if said_none:
        return {"outcome": "declined_no_route", "correct": False}
    return {"outcome": "no_answer", "correct": False}


def main():
    gold = {g["case_id"]: g for g in json.loads((STUDY / "poc_gold.json").read_text())["entries"]}
    out = {}
    for p in sorted(RUNS.glob("r-*/result.json")):
        res = json.loads(p.read_text())
        rid, cid = res.get("run_id", p.parent.name), res.get("case_id")
        if not cid:
            out[rid] = {"outcome": "malformed"}
            continue
        if "skipped" in res or "error" in res:
            out[rid] = {"case_id": cid, "outcome": "not_run",
                        "detail": res.get("skipped") or res.get("error")}
            continue
        s = score(res.get("answer") or {}, gold[cid])
        s["case_id"] = cid
        s["stratum"] = gold[cid]["stratum"]
        out[rid] = s
    (STUDY / "poc_scores.json").write_text(json.dumps(out, indent=1))
    import collections
    c = collections.Counter(v.get("outcome") for v in out.values())
    print(f"scored {len(out)} runs -> study/poc_scores.json")
    for k, v in c.most_common():
        print(f"  {v:4d}  {k}")


if __name__ == "__main__":
    main()
