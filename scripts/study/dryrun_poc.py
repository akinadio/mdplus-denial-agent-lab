#!/usr/bin/env python3
"""Run the whole study end to end with no API calls, no key, no money.

Every failure this study has had was findable for free: an arm that 400'd on
every case, a gold key built against a directory that had since changed, a
search backend that died mid-run and got scored anyway, an appeal deadline that
was never passed into the letter generator, a grader that ran out of credit
three quarters of the way through. Each cost a paid run to discover.

So this exercises all four stages -- build cases, retrieve, draft, grade -- with
scripted responses in place of the models, and asserts the things that were
actually wrong. It is not a test of whether the models are any good. It is a
test of whether the pipeline can carry an answer from one end to the other
without dropping a field.

  python3 scripts/study/dryrun_poc.py

Exit 0 means the pipeline is sound and a paid run is worth starting.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILURES: list[str] = []
CHECKS = 0


def check(ok: bool, what: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if ok:
        print(f"  ok    {what}")
    else:
        print(f"  FAIL  {what}" + (f"\n          {detail}" if detail else ""))
        FAILURES.append(what)


# --------------------------------------------------------------------------
# 1. cases and gold
# --------------------------------------------------------------------------
def stage_cases():
    print("\n[1] cases and gold key")
    from run_poc import STUDY
    import csv

    cases = json.loads((STUDY / "poc_cases.json").read_text())["cases"]
    gold = {g["case_id"]: g for g in json.loads((STUDY / "poc_gold.json").read_text())["entries"]}
    check(len(cases) == len(gold), f"every case has a gold entry ({len(cases)} cases, {len(gold)} gold)")

    strata = {c["stratum"] for c in cases}
    check(strata == {"in_library", "vendor_held", "no_policy"},
          f"all three strata present: {sorted(strata)}")

    # The bug that produced five phantom errors: gold built from one directory,
    # scored against another.
    rows = {}
    with (ROOT / "data/policy_platform/app_option_policy_directory.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            rows[(r["state"], r["insurance_company"], r["cpt"])] = r
    drift = []
    for g in gold.values():
        row = rows.get((g["state"], g["payer"], g["cpt"]))
        if row is None:
            drift.append(f"{g['case_id']} has no directory row at all")
        elif g.get("policy_url") and row["policy_url"] != g["policy_url"]:
            drift.append(f"{g['case_id']} gold url != directory url")
        elif row["status"] != g["directory_status"]:
            drift.append(f"{g['case_id']} status {row['status']} != gold {g['directory_status']}")
    check(not drift, "gold key matches the directory it will be scored against",
          "; ".join(drift[:3]) + (f" (+{len(drift)-3} more)" if len(drift) > 3 else ""))

    # Without a chart, both arms write [placeholder] letters and the grader
    # marks them unfinished -- measuring the study's missing inputs, not either
    # system. Six of the first eleven appeal-fatal letters were that artifact.
    charted = [c for c in cases if (c.get("chart_summary") or "").strip()]
    check(len(charted) == len(cases), f"every case carries a chart ({len(charted)}/{len(cases)})")
    if charted:
        ex = charted[0]["chart_summary"]
        for needed in ("Conservative care", "Imaging", "Function"):
            check(needed in ex, f"chart states {needed.lower()}")

    behaviors = {g["correct_behavior"] for g in gold.values()}
    check(behaviors == {"cite_document", "cite_and_route", "abstain_and_route"},
          f"all three gold behaviors present: {sorted(behaviors)}")
    return cases, gold


# --------------------------------------------------------------------------
# 2. retrieval, both arms
# --------------------------------------------------------------------------
def stage_retrieval(cases, gold):
    print("\n[2] retrieval")
    from run_poc import run_ortho, SYSTEMS, _guarded, SearchBackendDown

    by_stratum: dict[str, dict] = {}
    for c in cases:
        by_stratum.setdefault(c["stratum"], c)

    for stratum, c in sorted(by_stratum.items()):
        res = run_ortho(c, "dry-run")
        ans = res["answer"]
        g = gold[c["case_id"]]
        if g["correct_behavior"] in ("cite_document", "cite_and_route"):
            check(bool(ans.get("policy_url")), f"ortho returns a document for {stratum}")
            check(ans.get("policy_url") == g["policy_url"],
                  f"ortho returns the RIGHT document for {stratum}")
        else:
            check(not ans.get("policy_url"), f"ortho withholds a document for {stratum}")
        if g["correct_behavior"] in ("cite_and_route", "abstain_and_route"):
            check(bool((ans.get("how_to_obtain_criteria") or "").strip()),
                  f"ortho routes for criteria on {stratum}")
        # The letter cannot state what retrieval never returned.
        check(bool(ans.get("appeal_deadline")), f"ortho carries the deadline on {stratum}")
        check(bool(ans.get("submission_route")), f"ortho carries the route on {stratum}")

    # The failure that scored 60 blind answers as if they were real.
    class Down(Exception):
        pass

    def dead_search(name, args):
        return {"error": 'search backend returned HTTP 402: {"detail":"Usage limit exceeded."}',
                "result_count": 0}
    try:
        _guarded(dead_search)("web_search", {"query": "x"})
        check(False, "a dead search backend aborts the run", "no exception was raised")
    except SearchBackendDown:
        check(True, "a dead search backend aborts the run")
    except Exception as e:  # noqa: BLE001
        check(False, "a dead search backend aborts the run", f"wrong exception: {type(e).__name__}")


# --------------------------------------------------------------------------
# 3. scoring
# --------------------------------------------------------------------------
def stage_scoring(cases, gold):
    print("\n[3] scoring")
    import importlib
    sp = importlib.import_module("score_poc") if "scripts/study" in sys.path[0] else None
    sys.path.insert(0, str(ROOT / "scripts" / "study"))
    import score_poc  # noqa: E402

    g_in = next(g for g in gold.values() if g["correct_behavior"] == "cite_document")
    g_vh = next(g for g in gold.values() if g["correct_behavior"] == "cite_and_route")
    g_np = next(g for g in gold.values() if g["correct_behavior"] == "abstain_and_route")

    right = {"policy_url": g_in["policy_url"], "policy_found": True}
    check(score_poc.score(right, g_in)["outcome"] == "correct", "in_library: right document scores correct")
    check(score_poc.score({"policy_url": "https://example.com/x.pdf", "policy_found": True}, g_in)["outcome"]
          == "wrong_document", "in_library: wrong document scores wrong")
    check(score_poc.score({}, g_in)["outcome"] == "no_answer", "in_library: silence scores no_answer")

    vh_ok = {"policy_url": g_vh["policy_url"], "policy_found": True,
             "how_to_obtain_criteria": "Ask the plan in writing for the criteria."}
    check(score_poc.score(vh_ok, g_vh)["outcome"] == "correct", "vendor_held: document + route scores correct")
    check(score_poc.score({"policy_url": g_vh["policy_url"], "policy_found": True}, g_vh)["outcome"]
          == "cited_no_route", "vendor_held: document alone is not correct")
    check(score_poc.score({"policy_found": False, "how_to_obtain_criteria": "ask them"}, g_vh)["outcome"]
          == "no_answer", "vendor_held: route alone is not correct")

    np_ok = {"policy_found": False, "how_to_obtain_criteria": "Ask the plan in writing.",
             "notes": "no public criteria"}
    check(score_poc.score(np_ok, g_np)["outcome"] == "correct", "no_policy: abstain + route scores correct")
    check(score_poc.score({"policy_url": "https://example.com/made-up.pdf", "policy_found": True}, g_np)["outcome"]
          == "hallucinated_document", "no_policy: naming a document scores hallucinated")


# --------------------------------------------------------------------------
# 4. letters and grading, with the models stubbed out
# --------------------------------------------------------------------------
class _StubAnthropic:
    """Stands in for the Anthropic client. Records what it was asked."""
    def __init__(self, payload):
        self._payload = payload
        self.seen_prompt = ""
        self.messages = self

    def create(self, **kw):
        self.seen_prompt = "\n".join(
            str(m.get("content")) for m in kw.get("messages", []))
        block = type("B", (), {"type": "text", "text": self._payload})()
        usage = type("U", (), {"input_tokens": 10, "output_tokens": 20})()
        return type("R", (), {"content": [block], "usage": usage})()


def stage_letters(cases, gold):
    print("\n[4] letters and grading")
    from run_letters_poc import _ortho_result, LETTER_ASK
    from synthetic_harness.appeal_letter import generate_appeal_letter
    from run_poc import run_ortho

    c = next(x for x in cases if x["stratum"] == "in_library")
    res = run_ortho(c, "dry-run")
    shaped = _ortho_result(c, res["answer"])

    # The bug that scored our letters 0% on deadline and 0% on route: the
    # fields existed in retrieval and never reached the letter prompt.
    stub = _StubAnthropic("Dear Plan,\n\nThis is a letter.\n")
    out = generate_appeal_letter(shaped, client=stub, sender="patient")
    check(not out.get("error"), "letter generation returns a letter", str(out.get("error")))
    check(res["answer"]["appeal_deadline"] in stub.seen_prompt,
          "the appeal deadline reaches the letter prompt")
    check("Send it to:" in stub.seen_prompt or
          (res["answer"].get("submission_route") or "@@") in stub.seen_prompt,
          "the submission route reaches the letter prompt")
    check(shaped["retrieval"]["selected_source"]["url"] in stub.seen_prompt,
          "the governing policy url reaches the letter prompt")

    # Both arms must receive the identical chart, or it is not a comparison.
    from run_letters_poc import _ask
    stub_c = _StubAnthropic("letter")
    generate_appeal_letter(shaped, client=stub_c, sender="patient",
                           patient_submission=c.get("chart_summary"))
    marker = "Conservative care"
    check(marker in stub_c.seen_prompt, "ortho letter prompt carries the chart")
    check(marker in _ask(c), "chatgpt letter ask carries the chart")

    # An arm that abstained still owes the patient a letter; dropping those
    # would keep each arm's weakest cases out of the graded set.
    c_np = next(x for x in cases if x["stratum"] == "no_policy")
    res_np = run_ortho(c_np, "dry-run")
    shaped_np = _ortho_result(c_np, res_np["answer"])
    stub2 = _StubAnthropic("Dear Plan,\n\nPlease send me the criteria.\n")
    out_np = generate_appeal_letter(shaped_np, client=stub2, sender="patient")
    check(not out_np.get("error"), "an abstaining case still produces a letter")

    # The grader must be blind, and must be able to parse its own output.
    import grade_letters_poc as G
    check("who or what wrote" in G.SYSTEM, "grader prompt tells the model it is blind")
    prompt = G._prompt(c, gold[c["case_id"]], "a letter")
    # Match the system names, not any word that contains them -- a chart that
    # says "orthopedic surgery" is not a leak, and a check that thinks it is
    # will get switched off, which is worse than no check.
    import re as _re
    for leak in ("ortho-sonnet", "ortho-opus", "orthoappeals", "chatgpt",
                 "gpt-5", "openai", "anthropic", "claude"):
        hit = _re.search(r"(?<![a-z])" + _re.escape(leak) + r"(?![a-z])", prompt.lower())
        check(hit is None, f"grader prompt does not leak {leak!r}",
              prompt[max(0, hit.start()-60):hit.end()+60] if hit else "")
    check(gold[c["case_id"]]["policy_url"] in prompt, "grader is given the correct policy")
    check("Conservative care" in prompt, "grader is given the same chart the writer had")

    from synthetic_harness.agent_runner import extract_json
    sample = json.dumps({
        "cites_correct_policy": True, "cites_wrong_policy": False,
        "fabricated_criteria": False, "deadline_correct": True, "route_given": True,
        "demands_criteria": True, "factual_errors": [], "appeal_fatal_error": False,
        "appeal_fatal_reason": "", "completeness": 4, "notes": "fine"})
    parsed = extract_json(sample) or {}
    sample = json.loads(sample); sample["uses_records"] = True
    sample = json.dumps(sample); parsed = extract_json(sample) or {}
    check(set(parsed) >= {"appeal_fatal_error", "completeness", "fabricated_criteria",
                          "uses_records"},
          "a well-formed grade parses")


# --------------------------------------------------------------------------
# 5. keys and budget, before anything is spent
# --------------------------------------------------------------------------
def stage_preflight():
    print("\n[5] keys and budget (nothing is called)")
    import os
    from run_poc import _load_env_files, _key_status
    _load_env_files()
    ks = _key_status()
    check(ks.get("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY looks like a real key")
    check(ks.get("OPENAI_API_KEY"), "OPENAI_API_KEY looks like a real key")
    check(bool(os.environ.get("WEB_SEARCH_API_KEY")), "WEB_SEARCH_API_KEY is set")
    print("      (balances are not checked here -- RUN_CHATGPT.command preflights search,\n"
          "       and the Anthropic balance shows up as a 400 on the first grade)")


def main() -> int:
    print("DRY RUN -- no API calls, no spend")
    cases, gold = stage_cases()
    stage_retrieval(cases, gold)
    stage_scoring(cases, gold)
    stage_letters(cases, gold)
    stage_preflight()
    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    if FAILURES:
        print("\nDO NOT START A PAID RUN. Broken:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("\nPipeline is sound. A paid run is worth starting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
