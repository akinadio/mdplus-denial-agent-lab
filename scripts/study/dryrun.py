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

  python3 scripts/study/dryrun.py

Exit 0 means the pipeline is sound and a paid run is worth starting.
"""
from __future__ import annotations

import os
import json
import subprocess
import time
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
    from retrieve import STUDY
    import csv

    cases = json.loads((STUDY / "cases.json").read_text())["cases"]
    gold = {g["case_id"]: g for g in json.loads((STUDY / "gold.json").read_text())["entries"]}
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
    from retrieve import run_ortho, SYSTEMS, _guarded, SearchBackendDown

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

    # A browse entry point is not the governing document.
    import csv as _csv
    idx = None
    with (ROOT / "data/policy_platform/app_option_policy_directory.csv").open(newline="") as fh:
        for r in _csv.DictReader(fh):
            if r["status"].startswith("VERIFIED (criteria public, no stable link"):
                idx = r
                break
    if idx:
        fake = {"state": idx["state"], "payer": idx["insurance_company"],
                "cpt": idx["cpt"], "plan_type": idx["plan_type"],
                "surgery": idx["surgery"], "appeal_deadline": "2027-01-01",
                "denial_reason": "conservative_care"}
        r2 = run_ortho(fake, "dry-run")
        check(r2["source"] == "policy_index_entry",
              "an index page is answered as a browse entry point, not the document",
              r2.get("source", ""))
        check("click through" in (r2["answer"].get("how_to_obtain_criteria") or ""),
              "and the patient is told how to reach the real document")

    # Route was a placeholder string for the whole first pilot, so every letter
    # told the patient nothing about where to send the appeal.
    from synthetic_harness.policy_text import submission_route
    for payer, want in (("Cigna", "cigna.com"), ("Aetna", "aetna"),
                        ("UnitedHealthcare", "uhc.com"),
                        ("Blue Cross Blue Shield of Michigan", "bcbsm")):
        got = submission_route(payer).lower()
        check(want in got, f"real appeal route for {payer}", got[:90])
    hcsc = submission_route("Blue Cross and Blue Shield of Texas").lower()
    other = submission_route("Premera Blue Cross").lower()
    check("bcbstx" in hcsc or "blue access" in hcsc, "an HCSC state gets the HCSC route")
    check("bcbstx" not in other, "a non-HCSC Blue never gets the HCSC portals", other[:90])
    check("printed on your denial letter" in submission_route("A Plan That Does Not Exist"),
          "an unknown payer falls back to the denial letter, never a guessed address")

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
    sp = importlib.import_module("score") if "scripts/study" in sys.path[0] else None
    sys.path.insert(0, str(ROOT / "scripts" / "study"))
    import score  # noqa: E402

    g_in = next(g for g in gold.values() if g["correct_behavior"] == "cite_document")
    g_vh = next(g for g in gold.values() if g["correct_behavior"] == "cite_and_route")
    g_np = next(g for g in gold.values() if g["correct_behavior"] == "abstain_and_route")

    right = {"policy_url": g_in["policy_url"], "policy_found": True}
    check(score.score(right, g_in)["outcome"] == "correct", "in_library: right document scores correct")
    # Seed a readable but unrelated document, so "wrong" is a real verdict and
    # not just "we could not fetch it".
    from synthetic_harness import policy_text as _PT
    wrong_url = "https://example.invalid/dryrun-unrelated.pdf"
    _PT.CACHE.mkdir(parents=True, exist_ok=True)
    _PT._key(wrong_url).write_text(json.dumps({
        "url": wrong_url, "status": 200,
        "text": "Dental Services Policy. Routine cleanings are covered twice per year."}))
    check(score.score({"policy_url": wrong_url, "policy_found": True}, g_in)["outcome"]
          == "wrong_document", "in_library: wrong document scores wrong")
    check(score.score({"policy_url": "https://example.invalid/never-fetched.pdf",
                           "policy_found": True}, g_in)["outcome"] == "cited_unreadable",
          "a document we cannot read is not silently scored as wrong")
    check(score.score({}, g_in)["outcome"] == "no_answer", "in_library: silence scores no_answer")

    vh_ok = {"policy_url": g_vh["policy_url"], "policy_found": True,
             "how_to_obtain_criteria": "Ask the plan in writing for the criteria."}
    check(score.score(vh_ok, g_vh)["outcome"] == "correct", "vendor_held: document + route scores correct")
    check(score.score({"policy_url": g_vh["policy_url"], "policy_found": True}, g_vh)["outcome"]
          == "cited_no_route", "vendor_held: document alone is not correct")
    check(score.score({"policy_found": False, "how_to_obtain_criteria": "ask them"}, g_vh)["outcome"]
          == "no_answer", "vendor_held: route alone is not correct")

    # Exact-string matching was the first pilot's worst measurement error.
    from equivalence import compare
    ev_old = "https://www.evicore.com/sites/default/files/clinical-guidelines/2025-11/Cigna_CMM-314%20Hip.pdf"
    ev_new = "https://www.evicore.com/sites/default/files/clinical-guidelines/2026-04/Cigna_CMM-314%20Hip.pdf"
    check(compare(ev_new, ev_old, "29914", "Cigna CMM-314")["verdict"] == "equivalent",
          "a newer edition of the same guideline counts as an equivalent edition")
    amb_il = "https://www.ambetterhealth.com/content/dam/centene/ambetteril/clinical-policies/CP.MP.114.pdf"
    amb_nc = "https://www.ambetterhealth.com/content/dam/centene/ambetternc/policies/clinical-policies/CP.MP.114.pdf"
    check(compare(amb_nc, amb_il, "63030", "CP.MP.114")["verdict"] == "equivalent",
          "another state's copy of the same policy counts")
    check(compare("https://example.com/unrelated.pdf", ev_old, "29914",
                  allow_fetch=False)["verdict"] == "different_document",
          "an unrelated document still counts as wrong")

    np_ok = {"policy_found": False, "how_to_obtain_criteria": "Ask the plan in writing.",
             "notes": "no public criteria"}
    check(score.score(np_ok, g_np)["outcome"] == "correct", "no_policy: abstain + route scores correct")
    check(score.score({"policy_url": "https://example.com/made-up.pdf", "policy_found": True}, g_np)["outcome"]
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
    from draft_letters import _ortho_result, LETTER_ASK
    from synthetic_harness.appeal_letter import generate_appeal_letter
    from retrieve import run_ortho

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
    from draft_letters import _ask
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
    shaped_np["criteria_request"] = res_np["answer"].get("how_to_obtain_criteria", "")
    stub3 = _StubAnthropic("letter")
    generate_appeal_letter(shaped_np, client=stub3, sender="patient")
    check("CRITERIA REQUEST" in stub3.seen_prompt,
          "a withheld-criteria case tells the letter to demand them")

    # The grader must be blind, and must be able to parse its own output.
    import grade_letters as G
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
    pk = G._prompt(c, gold[c["case_id"]], "a letter", packet="Governing policy given to the writer: X")
    check("EVIDENCE THE WRITER WAS GIVEN" in pk, "grader is told what evidence the writer had")
    scope = next((x for x in cases if x["cpt"] in ("29881", "29888", "29914")), None)
    if scope:
        check("grade 4" not in scope["chart_summary"] and "1 mm" not in scope["chart_summary"],
              "an arthroscopy case does not carry an end-stage-arthritis chart")

    # The letter must quote the document, and an invented quote must be caught
    # without a judge. Seed the cache so this costs no network.
    from synthetic_harness import policy_text as PT
    from synthetic_harness.quote_check import check as quote_check, quoted_passages
    fake_url = "https://example.invalid/dryrun-policy.pdf"
    real = ("Coverage Criteria. Partial knee arthroplasty 27447 is considered "
            "medically necessary when there is documented failure of at least 12 "
            "weeks of conservative therapy including supervised physical therapy.")
    PT.CACHE.mkdir(parents=True, exist_ok=True)
    PT._key(fake_url).write_text(json.dumps({"url": fake_url, "text": real, "status": 200}))

    check(PT.policy_text(fake_url)["text"] == real, "policy text is cached and read back")
    two_section = ("Table of Contents Hip Arthroplasty Knee Arthroplasty. "
                   "Carelon reviews all of its Guidelines at least annually. "
                   "Hip Arthroplasty Description and Scope. Total hip arthroplasty is "
                   "considered medically necessary for ANY of the following: "
                   "Advanced joint disease demonstrated by radiographic findings. "
                   "Failure of conservative management documented for at least 12 weeks. "
                   "Codes 27130. Knee Arthroplasty Clinical Indications. Total knee "
                   "arthroplasty is considered medically necessary when all of the "
                   "following are met: documented failure of at least 12 weeks of therapy.")
    hip = PT.find_criteria(two_section, "27130")
    check(any("hip arthroplasty is considered" in q.lower() for q in hip) and
          not any("annually" in q for q in hip),
          "criteria come from the procedure's own section, not the preamble", str(hip[:2]))
    check(any("Advanced joint disease" in q for q in hip),
          "the indications listed after a lead-in are kept")
    found = PT.find_criteria(real, "27447")
    check(bool(found) and found[0] in real, "criteria are lifted verbatim from the document",
          str(found[:1]))

    honest = f'The policy states:\n\n> {found[0]}\n'
    invented = ('The policy states:\n\n> The member must complete six months of '
                'supervised physical therapy and two injections before surgery.\n')
    check(len(quoted_passages(honest)) == 1, "a block quote is detected")
    check(quote_check(honest, fake_url)["not_in_policy"] == 0,
          "a real quote passes the check")
    check(quote_check(invented, fake_url)["not_in_policy"] == 1,
          "an invented quote is caught")
    check(quote_check(invented, "")["checked"] is False,
          "with no document, a quote is unverifiable rather than counted as invented")

    # The production generator must ground its own citations: real text when the
    # document reads, and an explicit "do not quote" when it does not.
    shaped_g = json.loads(json.dumps(shaped))
    shaped_g["retrieval"]["selected_source"]["url"] = fake_url
    # The fixture document is a knee policy. The case must be a knee case:
    # since 2026-09-21 a knee rule offered to, say, a lumbar case is dropped as
    # another operation's rule, which is the behaviour this file now wants.
    shaped_g.setdefault("case_identification", {})["cpt"] = "27447"
    shaped_g["retrieval"]["citations"] = [
        {"claim": "plan criteria", "reference": "x",
         "excerpt": "SOMETHING WE MADE UP THAT IS NOT IN THE DOCUMENT AT ALL"}]
    stub_g = _StubAnthropic("letter")
    generate_appeal_letter(shaped_g, client=stub_g, sender="patient")
    check(found[0][:60] in stub_g.seen_prompt,
          "grounding puts the document's own words into the prompt")
    check("SOMETHING WE MADE UP" not in stub_g.seen_prompt,
          "grounding drops citations that did not come from the document")

    shaped_n = json.loads(json.dumps(shaped_g))
    shaped_n["retrieval"]["selected_source"]["url"] = "https://example.invalid/missing.pdf"
    stub_n = _StubAnthropic("letter")
    generate_appeal_letter(shaped_n, client=stub_n, sender="patient")
    check("Do not quote the plan" in stub_n.seen_prompt,
          "with no readable document, the prompt forbids quoting the plan")
    check("UNVERIFIED" in stub_n.seen_prompt and "SOMETHING WE MADE UP" in stub_n.seen_prompt,
          "...but keeps the caller's evidence as unverified rather than discarding it")

    # The per-operation criteria map. The model picks sentences; code decides
    # whether they may be used. Stub the model with one real sentence, one
    # paraphrase, and one real sentence about ANOTHER operation.
    from policy_platform import build_section_criteria as _bsc
    _doc = ("Capsulorrhaphy is considered medically necessary when ALL the following criteria "
            "are met: History of a shoulder dislocation or recurrent subluxation. "
            "Total knee arthroplasty is considered medically necessary when there is "
            "advanced knee arthritis on weight-bearing radiographs.")
    _u = "https://example.invalid/dryrun-multi.pdf"
    PT._key(_u).write_text(json.dumps({"url": _u, "text": _doc, "status": 200}))

    class _U:  # usage
        input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens = 1, 1, 0, 0

    class _B:
        type = "text"
        text = json.dumps({"covered": True, "section_heading":
                           "Capsulorrhaphy is considered medically necessary when ALL the following criteria are met:",
                           "criteria": [
            {"text": "History of a shoulder dislocation or recurrent subluxation.", "topic": "clinical"},
            {"text": "The patient must have had shoulder instability for six months.", "topic": "clinical"},
            {"text": "Total knee arthroplasty is considered medically necessary when there is advanced knee arthritis", "topic": "imaging"}]})

    class _R:
        content, usage, stop_reason = [_B()], _U(), "end_turn"

    class _C:
        class messages:
            @staticmethod
            def create(**kw):
                return _R()

    _got = _bsc.extract(_C(), _u, "29806")
    check([i["text"] for i in _got["criteria"]] ==
          ["History of a shoulder dislocation or recurrent subluxation."],
          "section map keeps only verbatim sentences about THIS operation", str(_got["criteria"]))
    check(len(_got["dropped_not_in_document"]) == 1 and len(_got["dropped_other_operation"]) == 1,
          "a paraphrase and another operation's rule are both dropped and counted")
    _keep_map = PT._SECTIONS
    try:
        PT._SECTIONS = {f"{_u}||29806": {"covered": False, "criteria": [], "why_not": "x"}}
        _nc = PT.criteria_for(_u, "29806", allow_fetch=False)
        check(_nc["quotes"] == [] and _nc["source"] == "section_map_not_covered",
              "a document with no criteria for the operation yields nothing to quote")
        PT._SECTIONS = {f"{_u}||29806": {"covered": True, "criteria": [
            {"text": "History of a shoulder dislocation or recurrent subluxation.", "topic": "clinical"},
            {"text": "Capsulorrhaphy is considered medically necessary when ALL the following criteria are met:",
             "topic": "imaging"}]}}
        _ok = PT.criteria_for(_u, "29806", allow_fetch=False, reason="imaging")
        check(_ok["source"] == "section_map" and _ok["quotes"][0].startswith("Capsulorrhaphy"),
              "the section map is used first, answering the denial reason first")
    finally:
        PT._SECTIONS = _keep_map

    # A library hit must still verify: the library keeps quotes, the cache keeps
    # the text, and without the text every library hit read as unreadable.
    lib_path = PT.LIBRARY
    lib_backup = lib_path.read_text() if lib_path.exists() else None
    try:
        lib_path.write_text(json.dumps({"policies": [
            {"policy_url": fake_url, "policy_title": "dry", "quotes": found}]}))
        PT._LIB = None
        got = PT.criteria_for(fake_url, "27447", allow_fetch=False)
        check(got["source"] in ("library", "cache") and bool(got["text"]),
              "a library hit carries the document text, so its quotes verify")
        stub_l = _StubAnthropic("letter")
        generate_appeal_letter(shaped_g, client=stub_l, sender="patient")
        check("Do not quote the plan" not in stub_l.seen_prompt and found[0][:60] in stub_l.seen_prompt,
              "a library-backed policy is quotable in the letter prompt")
    finally:
        if lib_backup is None:
            lib_path.unlink(missing_ok=True)
        else:
            lib_path.write_text(lib_backup)
        PT._LIB = None

    # The denial notice reaches the letter, so names and IDs are not placeholders.
    from synthetic_harness.letter_inputs import notice_fields
    nf = notice_fields(c["letter_text"])
    check(nf.get("member_name") and nf.get("member_id") and nf.get("reference_number"),
          "member, ID and reference number are read off the denial notice", str(nf))
    shaped_n2 = dict(shaped, denial_notice_text=c["letter_text"])
    shaped_n2["case_identification"] = dict(shaped["case_identification"], **nf)
    stub_dn = _StubAnthropic("letter")
    generate_appeal_letter(shaped_n2, client=stub_dn, sender="patient")
    check(nf["member_id"] in stub_dn.seen_prompt and "THE DENIAL NOTICE" in stub_dn.seen_prompt,
          "the denial notice and the member's identifiers reach the letter prompt")
    check("Do not state a policy number" in stub_dn.seen_prompt,
          "the letter is told not to invent policy numbers or dates")

    # The quote checker ignores markdown and multi-line captures.
    check(quoted_passages('x "\n**Member:** [Name]\n**ID:** [x]" y') == [],
          "a stray quote mark around markdown is not a quotation")

    from synthetic_harness.agent_runner import extract_json
    sample = json.dumps({
        "cites_correct_policy": True, "cites_wrong_policy": False,
        "unsupported_attribution": False, "deadline_correct": True, "route_given": True,
        "demands_criteria": True, "factual_errors": [], "appeal_fatal_error": False,
        "appeal_fatal_reason": "", "completeness": 4, "notes": "fine"})
    parsed = extract_json(sample) or {}
    sample = json.loads(sample)
    sample.update({"uses_records": True, "wrong_policy_cited": False,
                   "wrong_recipient": False, "wrong_deadline": False,
                   "invented_identifier": False, "unfinished": False,
                   "worst_defect": ""})
    parsed = extract_json(json.dumps(sample)) or {}
    check(set(parsed) >= {"unsupported_attribution", "uses_records"},
          "a well-formed grade parses")

    # The quoting rule has to actually reach both arms.
    rule = "verbatim"
    check(rule in stub.seen_prompt.lower() or "quotation marks" in stub.seen_prompt.lower(),
          "ortho letter prompt carries the quoting rule")
    from draft_letters import LETTER_ASK
    check("quoting rule" in LETTER_ASK.lower(), "chatgpt ask carries the quoting rule")


# --------------------------------------------------------------------------
# 5. keys and budget, before anything is spent
# --------------------------------------------------------------------------
def stage_money():
    print("\n[7] money: nothing is lost when funding runs out")
    import spend, os
    check(spend.is_funding_error("Error code: 400 - Your credit balance is too low to access"),
          "an out-of-credit error is recognised as a funding stop")
    check(spend.is_funding_error("Error code: 429 - insufficient_quota"),
          "an OpenAI quota error is recognised as a funding stop")
    check(not spend.is_funding_error("Unknown parameter: 'input[2].status'"),
          "an ordinary error is not mistaken for one")
    check(spend.cost("gpt-5.6-luna", {"input_tokens": 1_000_000, "output_tokens": 0})
          == spend.price("gpt-5.6-luna")[0],
          "cost is computed from tokens at the model's own verified rate")
    os.environ["STUDY_BUDGET_USD"] = "0.0000001"
    try:
        spend.check_budget(); check(spend.total() == 0, "an empty ledger is under any budget")
    except spend.OutOfFunds:
        check(True, "a spent budget raises before the next paid call")
    finally:
        os.environ.pop("STUDY_BUDGET_USD", None)
    # resume must retry failures, in all three paid scripts
    src = (ROOT / "scripts/study/grade_letters.py").read_text()
    import re as _re
    _mt = [int(x) for x in _re.findall(r"max_tokens=(\d+)", src)]
    check(bool(_mt) and min(_mt) >= 4000, "grade_letters.py: the grader has room to finish its JSON")
    check('"grader_incomplete"' in src and "REQUIRED" in src,
          "grade_letters.py: a grade with missing fields is not counted as a grade")
    # A provider's SDK objects must not kill a run we already paid for.
    from retrieve import _jsonable
    class _Fake:                       # stands in for types.Content
        def model_dump(self): return {"role": "user", "parts": [{"text": "hi"}]}
    import json as _json
    out = _jsonable({"transcript": [_Fake()], "n": 1, "t": ("a", "b")})
    _json.dumps(out)                   # must not raise
    check(out["transcript"][0]["role"] == "user",
          "an SDK object in the transcript is written as a dict, not lost")
    check(_json.dumps(_jsonable({"x": object()})),
          "an object with no dump method degrades to text instead of crashing")

    # --limit must mean "do N more", or batching a long run silently stalls.
    # Exercised, not grepped: the string check passed right up until the day
    # the loop was rewritten, and a check that only knows one spelling of the
    # right answer is not checking anything.
    import tempfile as _tf, shutil as _sh
    import retrieve as _ret
    _cases = [{"case_id": f"c{i}"} for i in range(5)]
    _tmp = Path(_tf.mkdtemp())
    try:
        def _finish(cid, sys_, payload):
            d = _tmp / _ret._rid(cid, sys_, "t")
            d.mkdir(parents=True, exist_ok=True)
            (d / "result.json").write_text(_json.dumps(payload))

        for i in range(3):                       # first three already clean
            _finish(f"c{i}", "x", {"answer": {}})
        _finish("c3", "x", {"error": "boom"})    # one failed

        got = _ret.plan(_cases, ["x"], "t", resume=True, limit=2, runs=_tmp)
        check([c["case_id"] for c, _ in got] == ["c3", "c4"],
              "retrieve.py: --limit skips finished cases and advances past them")
        check(len(_ret.plan(_cases, ["x"], "t", resume=True, runs=_tmp)) == 2,
              "retrieve.py: --resume retries a failed item instead of skipping it")
        check(len(_ret.plan(_cases, ["x"], "t", resume=False, runs=_tmp)) == 5,
              "retrieve.py: without --resume every case is run again")
        check([s_ for _, s_ in _ret.plan(_cases[:1], ["a", "b"], "t", runs=_tmp)] == ["a", "b"],
              "retrieve.py: a batch splits evenly across the arms named")
    finally:
        _sh.rmtree(_tmp, ignore_errors=True)

    # Running cases in parallel breaks two things that were safe when the loop
    # was serial. Both are checked here because both fail SILENTLY: the ledger
    # just reads low, and a rate-limit blip just looks like a dead backend.
    import threading as _th
    import spend as _sp
    _led = _sp.LEDGER
    _tmp2 = Path(_tf.mkdtemp())
    try:
        _sp.LEDGER = _tmp2 / "spend.json"
        def _hammer():
            for _ in range(20):
                _sp.record("t", "claude-sonnet-5", {"input_tokens": 1000, "output_tokens": 100})
        _ts = [_th.Thread(target=_hammer) for _ in range(6)]
        [t.start() for t in _ts]; [t.join() for t in _ts]
        check(len(_json.loads(_sp.LEDGER.read_text())) == 120,
              "spend ledger keeps every call when workers write at once")
    finally:
        _sp.LEDGER = _led
        _sh.rmtree(_tmp2, ignore_errors=True)

    # A provider saying "slow down" must not be read as a provider saying
    # "you are out of money". Google says both in the same sentence, and on
    # 2026-09-21 reading it the wrong way dropped the whole Gemini arm three
    # seconds before it could have carried on -- after its searches were paid
    # for. The real error text is kept here verbatim as the fixture.
    from synthetic_harness import providers as _pv
    _TPM = ("ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
            "'You exceeded your current quota, please check your plan and billing "
            "details. ... Quota exceeded for metric: generativelanguage.googleapis.com/"
            "generate_content_paid_tier_2_input_token_count, limit: 3000000, model: "
            "gemini-3.5-flash. Please retry in 3.52663797s.', 'status': "
            "'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/"
            "google.rpc.QuotaFailure', 'violations': [{'quotaId': "
            "'GenerateContentPaidTierInputTokensPerModelPerMinute-PaidTier2'}]}]}}")
    _BROKE = ("Error code: 400 - {'type': 'error', 'error': {'type': "
              "'invalid_request_error', 'message': 'Your credit balance is too low "
              "to access the Anthropic API'}}")
    _DAY = ("429 RESOURCE_EXHAUSTED quota exceeded, check your plan and billing "
            "details. quotaId: GenerateRequestsPerDayPerProjectPerModel, limit: 200")
    check(_pv.is_transient_rate_limit(_TPM) and not _sp.is_funding_error(_TPM),
          "a per-minute rate limit is waited out, not read as an empty balance")
    check(_sp.is_funding_error(_BROKE) and not _pv.is_transient_rate_limit(_BROKE),
          "an empty balance still drops the arm instead of retrying forever")
    check(_sp.is_funding_error(_DAY), "a per-DAY quota still drops the arm")
    check(3.0 < _pv.retry_after(_TPM, 0) < 6.0,
          "the wait comes from the provider's own retry delay")

    _tries = []

    def _rate_limited_twice(**kw):
        _tries.append(1)
        if len(_tries) < 3:
            raise RuntimeError(_TPM)
        return "answer"

    _sleep, time.sleep = time.sleep, lambda _s: None
    try:
        check(_pv.call_with_backoff(_rate_limited_twice, model="m") == "answer"
              and len(_tries) == 3,
              "a model call rate-limited mid-run is retried, not lost")
        _broke_hits = []

        def _no_money(**kw):
            _broke_hits.append(1)
            raise RuntimeError(_BROKE)

        try:
            _pv.call_with_backoff(_no_money, model="m")
        except RuntimeError:
            pass
        check(len(_broke_hits) == 1, "an out-of-funds call is not retried at all")
    finally:
        time.sleep = _sleep

    # Every paid model call goes through the wrapper. A new call site added
    # without it silently reintroduces the bug, and only a grep catches that.
    _src = "\n".join((ROOT / f).read_text() for f in (
        "synthetic_harness/providers.py", "synthetic_harness/appeal_letter.py",
        "synthetic_harness/extract.py", "scripts/study/grade_letters.py"))
    _bare = [ln.strip() for ln in _src.splitlines()
             if ("messages.create(" in ln
                 or "client.models.generate_content(" in ln
                 or "client.responses.create(" in ln
                 or "client.chat.completions.create(" in ln)
             and "call_with_backoff" not in ln
             and not ln.strip().startswith(("#", "call_with_backoff"))]
    check(not _bare, "every provider call is wrapped in the rate-limit retry",
          "; ".join(_bare))

    import policy_eval.webtools as _wt
    check(_wt.SEARCH_MIN_INTERVAL > 0 and _wt.SEARCH_MAX_RETRIES >= 1,
          "web_search is paced and retries, so --workers cannot burst the backend")

    class _Resp:
        def __init__(self, code): self.status_code, self.headers, self.text = code, {}, ""
        def json(self): return {"web": {"results": []}}

    _seen = []

    def _flaky(url, params=None, headers=None, timeout=None):
        _seen.append(1)
        return _Resp(429 if len(_seen) < 3 else 200)

    _get, _iv = _wt.requests.get, _wt.SEARCH_MIN_INTERVAL
    _key = os.environ.get("WEB_SEARCH_API_KEY")
    try:
        _wt.requests.get, _wt.SEARCH_MIN_INTERVAL = _flaky, 0.0
        os.environ["WEB_SEARCH_API_KEY"] = "test"
        _out = _wt.search("anything", 3)
        check(len(_seen) == 3 and not _out.get("error"),
              "a rate-limited search is retried, not read as a dead backend")
    finally:
        _wt.requests.get, _wt.SEARCH_MIN_INTERVAL = _get, _iv
        if _key is None:
            os.environ.pop("WEB_SEARCH_API_KEY", None)
        else:
            os.environ["WEB_SEARCH_API_KEY"] = _key

    # The worker pool itself, end to end, with a stub model: every case gets
    # exactly one result file and none is lost or written twice. Every new code
    # path in this harness has shipped with a bug in it (the Responses API, the
    # Google provider, the Anthropic arm), so the pool does not get to be the
    # exception.
    _tmp3 = Path(_tf.mkdtemp())
    _keep = (_ret.RUNS, _ret.STUDY, _ret.SYSTEMS, _ret.run_llm, sys.argv, _sp.LEDGER)
    try:
        _ret.RUNS, _ret.STUDY = _tmp3 / "runs", _tmp3
        _sp.LEDGER = _tmp3 / "spend.json"
        (_tmp3 / "cases.json").write_text(_json.dumps(
            {"cases": [{"case_id": f"p{i}", "letter_text": "x"} for i in range(9)]}))
        _ret.SYSTEMS = {"stub": ("anthropic", "claude-sonnet-5")}
        _hits = []
        _hl = _th.Lock()

        def _stub(system, case, out_dir):
            with _hl:
                _hits.append(case["case_id"])
            time.sleep(0.02)
            return {"answer": {"policy_found": True}, "usage": {}, "model": "stub"}

        _ret.run_llm = _stub
        sys.argv = ["retrieve.py", "--systems", "stub", "--workers", "4"]
        try:
            _ret.main()
        except SystemExit:
            pass
        _files = sorted(f.parent.name for f in (_tmp3 / "runs").glob("*/result.json"))
        check(len(_hits) == 9 and len(set(_hits)) == 9,
              "--workers runs each case exactly once, none dropped or doubled")
        check(len(_files) == 9,
              "--workers writes a result file for every case it ran")
        check(len(_json.loads((_tmp3 / "unblinding.json").read_text())) == 9,
              "--workers still writes a complete unblinding key")
    finally:
        _ret.RUNS, _ret.STUDY, _ret.SYSTEMS, _ret.run_llm, sys.argv, _sp.LEDGER = _keep
        _sh.rmtree(_tmp3, ignore_errors=True)

    # Prompt caching. It is billing-only -- the model sees the same bytes and
    # answers the same -- but it changes what a run costs by several times, so
    # both halves are checked: that the breakpoints go out, and that the ledger
    # prices what comes back.
    # Priced against the table itself, not against numbers written here: a test
    # that hardcodes a rate has to be edited every time a vendor moves, and the
    # edit is exactly where a wrong number gets in.
    for _m in _sp._DEFAULT:
        _pin, _pout, _pw, _pr = _sp.price(_m)
        check(_sp.cost(_m, {"input_tokens": 1_000_000}) == round(_pin, 4),
              f"{_m}: uncached input prices at the verified input rate")
        check(_sp.cost(_m, {"cache_read_input_tokens": 1_000_000}) == round(_pr, 4),
              f"{_m}: a cache READ prices at the verified cache rate, not free")
        check(_sp.cost(_m, {"cache_creation_input_tokens": 1_000_000}) == round(_pw, 4),
              f"{_m}: a cache WRITE prices at the verified write rate")
        check(0 < _pr < _pin <= _pw and _pout > _pin,
              f"{_m}: the four rates are ordered sanely (read < input <= write; output > input)")

    # Prices must be verified, and an unverified one must stop the run rather
    # than guess. All four entries in this table were wrong on 2026-09-19 while
    # a comment claimed they had been checked.
    check(len(_sp.VERIFIED) == 10 and set(_sp.SOURCES) == {"openai", "anthropic", "google"},
          "the price table records the date it was verified and the pages it came from")
    try:
        _sp.price("some-model-nobody-priced")
        check(False, "an unpriced model raises instead of falling back to a guess")
    except _sp.UnknownPrice:
        check(True, "an unpriced model raises instead of falling back to a guess")
    import grade_letters as _gl
    _models = [m for _, m in _ret.SYSTEMS.values()] + [_gl.GRADER_MODEL]
    for _m in _models:
        try:
            _sp.price(_m)
            check(True, f"{_m} has a verified price before its arm can run")
        except _sp.UnknownPrice:
            check(False, f"{_m} has a verified price before its arm can run")
    _sp.banner("x", 1, "claude-sonnet-5 / gpt-5.6-luna", 10, 10)
    check(True, "a banner naming two models prices without crashing")

    from synthetic_harness.providers import AnthropicProvider as _AP

    class _Blk:  # stands in for an SDK content object: not a dict, must be left alone
        type = "text"

    _msgs = [{"role": "user", "content": [{"type": "text", "text": "a"}]},
             {"role": "assistant", "content": [_Blk()]},
             {"role": "user", "content": [{"type": "tool_result", "content": "b"}]},
             {"role": "assistant", "content": [_Blk()]},
             {"role": "user", "content": [{"type": "tool_result", "content": "c"}]}]
    _AP._mark(_msgs)
    _bp = [i for i, m in enumerate(_msgs)
           if isinstance(m["content"], list)
           and any(isinstance(b, dict) and "cache_control" in b for b in m["content"])]
    check(_bp == [2, 4],
          "cache breakpoints sit on the two most recent user turns")
    _AP._mark(_msgs + [{"role": "assistant", "content": [_Blk()]},
                       {"role": "user", "content": [{"type": "tool_result", "content": "d"}]}])
    _n = sum(1 for m in _msgs for b in (m["content"] if isinstance(m["content"], list) else [])
             if isinstance(b, dict) and "cache_control" in b)
    check(_n <= 4, "old breakpoints are cleared, so a long loop never exceeds the API limit of 4")

    # The loop really sends them, and the usage really comes back accumulated.
    class _Usage:
        input_tokens, output_tokens = 10, 5
        cache_creation_input_tokens, cache_read_input_tokens = 100, 900

    class _Resp2:
        stop_reason, usage = "end_turn", _Usage()
        content = [type("T", (), {"type": "text", "text": '{"policy_found": false}'})()]

    _sent = {}

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                _sent.update(kw)
                return _Resp2()

    _u = {"input_tokens": 0, "output_tokens": 0}
    _AP().run(client=_Client(), model="claude-sonnet-5", system="s" * 40, prompt="p",
              tool_call=lambda n, a: {}, deadline=time.time() + 60, usage=_u,
              max_iters=3, max_tokens=100)
    check(isinstance(_sent.get("system"), list)
          and _sent["system"][0].get("cache_control"),
          "the system prompt is sent as a cacheable block")
    check(any("cache_control" in b for m in _sent["messages"]
              for b in m["content"] if isinstance(b, dict)),
          "the request carries a cache breakpoint on the conversation")
    check(_u.get("cache_read_input_tokens") == 900 and _u.get("cache_creation_input_tokens") == 100,
          "cached tokens are accumulated, not dropped on the floor")
    check(_sp.cost("claude-sonnet-5", _u) > _sp.cost("claude-sonnet-5",
          {k: v for k, v in _u.items() if not k.startswith("cache")}),
          "a run's cost includes its cached tokens")

    # A run WE cut short must never reach the scorer as a model failure. This
    # is the check that was missing on 2026-09-19, when three Gemini runs ended
    # at exactly the tool ceiling with no answer, carried no error, and were one
    # score.py away from being published as Gemini finding no policy.
    from synthetic_harness import api_runner as _ar
    check(_ar.MAX_TOOL_CALLS >= 100 and _ar.MAX_TOOL_ITERATIONS > _ar.MAX_TOOL_CALLS,
          "the tool budget binds before the iteration ceiling does")
    check("tool_use" not in _ret.NATURAL_STOPS and "max_iterations" not in _ret.NATURAL_STOPS
          and {"end_turn", "stop", "completed"} <= _ret.NATURAL_STOPS,
          "a run still asking for tools is not counted as a natural finish")

    _tmp5 = Path(_tf.mkdtemp())
    _keep5 = (_ret.run_llm, _sp.LEDGER)
    try:
        _sp.LEDGER = _tmp5 / "spend.json"

        class _Runner:
            _calls = 40

        def _fake(stop, text):
            import synthetic_harness.agent_runner as _agr
            _u = {"input_tokens": 1, "output_tokens": 1}
            # mimic run_llm's tail without calling a provider
            out = {"answer": _agr.extract_json(text) or {}, "raw_text": text,
                   "stop_reason": stop, "usage": _u, "tool_calls": 40}
            if stop not in _ret.NATURAL_STOPS:
                out["error"] = f"cut short by the harness: stop_reason={stop!r}"
            elif not (text or "").strip():
                out["error"] = "empty answer"
            return out

        check("error" in _fake("tool_use", ""),
              "a run that stopped while still asking for tools is marked an error")
        check("error" in _fake("max_iterations", '{"policy_found": true}'),
              "an exhausted loop is an error even when some JSON came back")
        check("error" in _fake("end_turn", "   "),
              "a natural stop with an empty answer is still an error")
        check("error" not in _fake("end_turn", '{"policy_found": false}'),
              "a model that finished and said it found nothing is a real answer, not an error")
    finally:
        _ret.run_llm, _sp.LEDGER = _keep5
        _sh.rmtree(_tmp5, ignore_errors=True)

    # And the tool budget itself: warn at the cap, raise past the grace.
    import synthetic_harness.api_runner as _ar2

    class _R(_ar2._ToolRunner):
        def __init__(self):
            import threading as _t2
            self._lock, self._i, self._calls = _t2.Lock(), 0, 0
            self._trace_path = Path(_tf.mkdtemp()) / "t.jsonl"
            self._row_id = "x"
            self._search = lambda q, c: {"results": [], "result_count": 0}
            self._fetch = lambda u, **k: {"text": ""}
            self._search_unavailable = RuntimeError

    _r = _R()
    _r._calls = _ar2.MAX_TOOL_CALLS
    _warn = _r.call("web_search", {"query": "q"})
    check("budget" in str(_warn.get("error", "")).lower(),
          "at the tool budget the model is told to answer with what it has")
    _r._calls = _ar2.MAX_TOOL_CALLS + _ar2.TOOL_CALL_GRACE
    try:
        _r.call("web_search", {"query": "q"})
        check(False, "past the grace the run is cut, not allowed to keep going")
    except _ar2.ToolBudgetExhausted:
        check(True, "past the grace the run is cut, not allowed to keep going")

    # ...and the other half of that: a not_run must be excluded from the
    # ACCURACY DENOMINATOR, not counted as a miss. Marking the run is worthless
    # if the analysis then reads the mark as a zero.
    _score_src = (ROOT / "scripts/study/score.py").read_text()
    check('"outcome": "not_run"' in _score_src and '"correct"' not in
          _score_src.split('"outcome": "not_run"')[1].split("continue")[0],
          "score.py records a not_run with no correct/incorrect verdict at all")
    _an_src = (ROOT / "scripts/study/analyze.py").read_text()
    check('"correct" not in s' in _an_src,
          "analyze.py drops any row with no verdict instead of scoring it 0")
    for _f in ("equivalence.py", "analyze_letters.py"):
        _src = (ROOT / "scripts/study" / _f).read_text()
        check('"correct" not in' in _src or "get(\"correct\")" not in _src
              or "not_run" in _src,
              f"{_f}: a run with no verdict cannot land in a denominator")

    # Google reports cached tokens INSIDE prompt_token_count; Anthropic reports
    # them separately. If that difference is not handled, Gemini is billed at
    # the full input rate for tokens Google discounted by 90%.
    from synthetic_harness.providers import GoogleProvider as _GP

    class _GU:
        prompt_token_count, candidates_token_count, cached_content_token_count = 1000, 50, 800

    _gu = {"input_tokens": 0, "output_tokens": 0}
    _GP._acc(_gu, type("R", (), {"usage_metadata": _GU()})())
    check(_gu["input_tokens"] == 200 and _gu["cache_read_input_tokens"] == 800,
          "Google's cached tokens are split out of prompt_token_count, not double-billed")

    # A retried case must not inherit the trace of the attempt we threw away.
    _tmp6 = Path(_tf.mkdtemp())
    try:
        _tp = _tmp6 / "tools.jsonl"
        _tp.write_text('{"i": 1, "action": "stale"}\n')
    except Exception:
        pass
    try:
        _r2 = _ar._ToolRunner(_tp, "row")
        check(_tp.read_text() == "",
              "a fresh run starts with an empty tool trace, not the last attempt's")
        check(getattr(_r2, "_calls", None) == 0,
              "the tool-call counter starts at zero for each attempt")
    finally:
        _sh.rmtree(_tmp6, ignore_errors=True)

    # A quotation is only right when it is the RIGHT sentence for this patient.
    # Every example below was quoted, verbatim and accurately, in a real letter
    # this pipeline produced, and the old presence-only check passed all of them.
    from synthetic_harness.quote_relevance import assess, classify, on_point
    for _q, _want in (
        ("Coverage Rationale Surgery of the hip and surgical treatment for "
         "Femoroacetabular Impingement (FAI) Syndrome is proven and medically "
         "necessary in certain circumstances.", "heading"),
        ("Arthroscopy, Diagnostic, +/- Synovial Biopsy, Hip Arthroscopy, "
         "Surgical, Hip Arthroscopy, Surgical, Hip (Pediatric) Arthrotomy, Hip",
         "code_table"),
        ("Surgery may be an option for individuals whose pain cannot be "
         "controlled by more conservative methods (National Institute of "
         "Arthritis and Musculoskeletal and Skin Diseases, 2021).", "background"),
        ("Medical records documentation may be required to assess whether the "
         "member meets the clinical criteria for coverage but does not "
         "guarantee coverage.", "administrative"),
        ("Surgical treatment for Femoroacetabular Impingement Syndrome is "
         "unproven and not medically necessary in the presence of advanced "
         "osteoarthritis (Tonnis Grade 3).", "exclusion"),
        ("Nonsteroidal anti-inflammatory drug (NSAID) or acetaminophen for at "
         "least three weeks unless contraindicated or not tolerated;", "rule"),
    ):
        check(classify(_q) == _want,
              f"a {_want} is recognised as a {_want}, not as a criterion")

    _nsaid = ("Nonsteroidal anti-inflammatory drug (NSAID) or acetaminophen for "
              "at least three weeks unless contraindicated or not tolerated;")
    _xray = ("Weight-bearing radiographs demonstrate only unicompartmental "
             "disease with Kellgren-Lawrence grade 3 or 4 changes.")
    check(on_point(_nsaid, "conservative_care") and not on_point(_nsaid, "imaging"),
          "a rule counts only against the denial reason it actually answers")
    check(on_point(_xray, "imaging"),
          "an imaging rule answers an imaging denial")
    check(not assess([], "conservative_care")["grounded"],
          "a letter that quotes NOTHING is not grounded -- silence is a failure")
    check(not assess([_nsaid], "imaging")["grounded"],
          "a letter quoting the wrong requirement is not grounded either")
    # A denial that names no specific deficiency is answered by the criteria
    # themselves. Harvard Pilgrim / 29881 was denied for "incomplete
    # documentation" and our letter quoted the non-operative-treatment
    # requirement -- the right move, and it was being scored off point because
    # the sentence contains no documentation vocabulary.
    check(assess([_nsaid], "incomplete_documentation")["grounded"],
          "a generic denial is answered by quoting the criteria themselves")
    check(assess([_nsaid], "not_medically_necessary")["grounded"],
          "'does not meet criteria' is answered by quoting the criteria")
    check(not assess(["Coverage Rationale Surgery of the knee is proven and "
                      "medically necessary in certain circumstances."],
                     "not_medically_necessary")["grounded"],
          "a heading still does not ground a letter, whatever the denial said")
    check(assess([_nsaid], "conservative_care")["grounded"],
          "a letter quoting the requirement the denial turned on IS grounded")

    # ...and the extractor must never hand one of these to a letter.
    import synthetic_harness.policy_text as _PT
    _doc = ("KNEE ARTHROPLASTY Coverage Rationale Surgery of the knee is proven "
            "and medically necessary in certain circumstances. " + _nsaid +
            " Total knee arthroplasty is unproven and not medically necessary in "
            "the presence of active infection. Medical records documentation may "
            "be required but does not guarantee coverage.")
    _got = _PT.find_criteria(_doc, "27447", reason="conservative_care")
    check(all(classify(c) == "rule" for c in _got),
          "find_criteria returns only rules -- no headings, boilerplate or exclusions")
    check(not any("unproven" in c for c in _got),
          "find_criteria never hands a letter the exclusion that denies the claim")

    # The letter must answer the plan, not repeat the insurer.
    from synthetic_harness.quote_relevance import reason_from_notice as _rfn
    for _t, _want in (
        ("the clinical records submitted do not document an adequate trial of "
         "conservative treatment prior to the requested surgery", "conservative_care"),
        ("the imaging findings submitted do not support the medical necessity "
         "of the requested procedure", "imaging"),
        ("the documentation submitted was incomplete and does not allow a "
         "determination of medical necessity", "incomplete_documentation"),
        ("the requested procedure does not meet the plan's criteria for "
         "medical necessity", "not_medically_necessary"),
    ):
        check(_rfn(_t) == _want,
              f"a notice denying for {_want} is read as {_want}")

    _al = (ROOT / "synthetic_harness/appeal_letter.py").read_text()
    check('classify(c["excerpt"]) == "rule"' in _al,
          "a caller excerpt is kept only if it is a rule, not just verbatim")
    check("Quote the PLAN, never the denial" in _al,
          "the prompt forbids quoting the denial notice back as if it were the plan")
    check("criteria_for(url, cpt, reason=reason)" in _al,
          "the letter writer is told which denial reason the criteria must answer")
    _gl = (ROOT / "scripts/study/grade_letters.py").read_text()
    check("quoted_the_denial_back" in _gl and "in_text(x, _notice)" in _gl,
          "grading counts only what the letter quoted from the POLICY")

    # Sendability and invented identifiers -- and, because both were biased
    # toward our own arm on first writing, the checks that catch that bias.
    from synthetic_harness.letter_checks import sendability, invented_identifiers
    _notice = ("Member: Jordan Alvarez\nMember ID: W884213907\n"
               "Date of notice: 2026-08-07\nReference number: POC-XYZ-41822\n")
    _full = ("I am Jordan Alvarez, Member ID W884213907, reference POC-XYZ-41822, "
             "appealing the denial dated 2026-08-07.")
    check(sendability(_full, _notice)["complete"],
          "a letter carrying every identifier from the notice is sendable")
    check(not sendability("Please reconsider my surgery.", _notice)["complete"],
          "a letter with none of them is not sendable")
    # The bias: our own letters get the notice's exact string, a chatbot writes
    # the same date in words. ChatGPT scored 2% sendable until this was fixed.
    _worded = _full.replace("2026-08-07", "August 7, 2026")
    check(sendability(_worded, _notice)["complete"],
          "the same date written in words still counts -- no format bias between arms")

    _doc = "Clinical Policy: Disc Decompression CP.MP.114 Date of Last Revision: 04/25"
    check(not invented_identifiers("per CP.MP.114, effective 04/25", _doc)["any_invented"],
          "an identifier that is in the policy is not called invented")
    check(invented_identifiers("per CP.MP.999", _doc)["any_invented"],
          "a policy number in no source is called invented")
    # Aetna bulletin numbers live in the URL, not the body text.
    check(not invented_identifiers(
              "per CPB 0660", "body text with no number in it", [],
              "https://www.aetna.com/cpb/medical/data/600_699/0660.html")["any_invented"],
          "a number carried in the policy URL is not called invented")

    # A transcript saved to disk has to be feedable back to the SDK that made
    # it. Google's was not: model_dump() writes every unset field as null and
    # the SDK refuses its own output, "1405 validation errors" for one letter.
    from synthetic_harness.providers import GoogleProvider as _GP2
    _t = [{"role": "user", "parts": [{"text": "hello", "inline_data": None,
                                      "function_call": None, "video_metadata": None}]},
          {"role": "model", "parts": [{"text": None,
                                       "function_call": {"name": "web_search",
                                                         "args": {"query": "q"}}}]}]
    _p = [_GP2._prunable(x) for x in _t]
    check(_json.dumps(_p).count(": null") == 0,
          "a saved transcript is pruned of the null fields the SDK rejects")
    # The one that actually broke every Gemini letter: thought_signature is a
    # BYTES field, and a plain model_dump() writes the repr of the bytes object
    # rather than base64, so the SDK refuses the whole transcript over one key.
    _bad = _GP2._prunable({"parts": [{"text": "x",
                                      "thought_signature": "b'\\x12\\xcc\\x05'"}]})
    check("thought_signature" not in _bad["parts"][0] and _bad["parts"][0]["text"] == "x",
          "a bytes field written as a Python repr is dropped, not fed back")
    _good = _GP2._prunable({"parts": [{"thought_signature": "aGVsbG8="}]})
    check(_good["parts"][0]["thought_signature"] == "aGVsbG8=",
          "a properly base64 bytes field is kept")
    check('"mode": "json"' in (ROOT / "scripts/study/retrieve.py").read_text(),
          "phase 1 saves transcripts in JSON mode, so bytes are base64 from the start")
    check(len(_p) == 2 and _p[0]["parts"][0]["text"] == "hello"
          and _p[1]["parts"][0]["function_call"]["name"] == "web_search",
          "pruning keeps every turn, its text and its tool calls")
    check('"exclude_none": True' in (ROOT / "scripts/study/retrieve.py").read_text(),
          "phase 1 saves transcripts without the null fields in the first place")

    # UNDEFINED NAMES. grade_letters.py shipped a worker pool with no import
    # for ThreadPoolExecutor: the module imported fine, the dry run passed, and
    # it died at the moment of use -- after the letters were already paid for.
    # A syntax check does not catch that; pyflakes does, in a second, for free.
    try:
        from pyflakes.api import check as _pf_check
        from pyflakes.reporter import Reporter as _PfReporter
        import io as _io

        _bad = []
        for _f in sorted((ROOT / "scripts" / "study").glob("*.py")) + \
                 sorted((ROOT / "synthetic_harness").glob("*.py")) + \
                 sorted((ROOT / "scripts" / "policy_eval").glob("*.py")):
            _out, _err = _io.StringIO(), _io.StringIO()
            _pf_check(_f.read_text(), str(_f), _PfReporter(_out, _err))
            for _line in _out.getvalue().splitlines():
                if "undefined name" in _line:
                    _bad.append(_line.replace(str(ROOT) + "/", ""))
        check(not _bad, "no script uses a name it never imported or defined",
              "; ".join(_bad[:3]))
    except ImportError:
        check(False, "pyflakes is installed, so undefined names are caught here "
                     "rather than mid-run (pip install pyflakes)")

    # Search is billed per request and never goes through cost(). Leaving it
    # off the ledger understated the study by $41 across 8,281 requests.
    _tmp7 = Path(_tf.mkdtemp())
    _keep7 = _sp.LEDGER
    try:
        _sp.LEDGER = _tmp7 / "spend.json"
        _sp.record_search(200, "r-test")
        _rows = _json.loads(_sp.LEDGER.read_text())
        check(len(_rows) == 1 and _rows[0]["step"] == "search"
              and _rows[0]["searches"] == 200,
              "a batch of searches is one ledger row carrying its request count")
        check(abs(_sp.total() - 200 * _sp.SEARCH_PRICE_PER_1000 / 1000) < 1e-6,
              "search cost is inside total(), so the budget guard sees it")
        _sp.record("retrieve", "claude-sonnet-5", {"input_tokens": 1_000_000})
        _sp.report()   # must not raise: a search row has no model price
        check(True, "report() prices a ledger holding both search and model rows")
    finally:
        _sp.LEDGER = _keep7
        _sh.rmtree(_tmp7, ignore_errors=True)
    _wt_src = (ROOT / "scripts/policy_eval/webtools.py").read_text()
    check("spend.record_search(1)" in _wt_src,
          "every search records itself, so no code path can search unbilled")

    # One provider's empty balance must not stop the others.
    for f in ("retrieve.py", "draft_letters.py"):
        src = (ROOT / "scripts/study" / f).read_text()
        check("broke.add(" in src and "continue" in src,
              f"{f}: an out-of-funds provider drops only that arm")
    check('in ("graded", "no_letter")' in (ROOT / "scripts/study/grade_letters.py").read_text(),
          "grade_letters.py: --resume retries a failed item instead of skipping it")

    # draft_letters' resume rule, exercised rather than grepped.
    import draft_letters as _dl
    _tmp4 = Path(_tf.mkdtemp())
    _keep4 = _dl.RUNS
    try:
        _dl.RUNS = _tmp4
        _key = {f"r-{i}": {"case_id": f"c{i}", "system": "x"} for i in range(4)}
        for i, letter in enumerate([{"letter_markdown": "ok"}, {"error": "boom"}, None, None]):
            d = _tmp4 / f"r-{i}"; d.mkdir(parents=True)
            (d / "result.json").write_text("{}")
            if letter is not None:
                (d / "letter.json").write_text(_json.dumps(letter))
        # r-3 has no result.json at all -> nothing to draft from
        _sh.rmtree(_tmp4 / "r-3")
        got = _dl._pending(_key, ["x"], resume=True)
        check(got == ["r-1", "r-2"],
              "draft_letters.py: --resume retries a failed item instead of skipping it")
        check(_dl._pending(_key, ["x"], resume=False) == ["r-0", "r-1", "r-2"],
              "draft_letters.py: a run with no retrieval result is never drafted")
    finally:
        _dl.RUNS = _keep4
        _sh.rmtree(_tmp4, ignore_errors=True)


def stage_gitignore():
    print("\n[0] nothing is being silently ignored")
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "scripts/study/check_gitignore.py")],
                       capture_output=True, text=True, cwd=ROOT)
    check(r.returncode == 0, "every data file under data/policy_platform is trackable",
          r.stdout.strip()[-400:])


def stage_live_path(cases):
    """The study's harness was filling in deadline, route, member and the
    criteria demand itself; the live server passed none of them. Now both go
    through synthetic_harness.letter_inputs.enrich, and the server calls it."""
    print("\n[8] the live server feeds the letter what the study feeds it")
    from synthetic_harness.letter_inputs import enrich
    src = (ROOT / "synthetic_harness/server.py").read_text()
    check("enrich_for_letter(result, submission_text)" in src,
          "server.py enriches the result before drafting")
    c = next(x for x in cases if x["stratum"] == "vendor_held")
    bare = {"case_identification": {"payer": c["payer"], "product_type": c["plan_type"]},
            "retrieval": {"selected_source": {"url": "https://x.invalid/p.pdf"}, "citations": []}}
    r = enrich(bare, c["letter_text"], directory_note="criteria are InterQual")
    check(r.get("appeal_deadline") == c["appeal_deadline"], "deadline is read off the notice")
    check(bool(r.get("submission_route")), "a submission route is supplied")
    check(bool(r["case_identification"].get("member_id")), "member identifiers are read off the notice")
    check(bool(r.get("denial_notice_text")), "the notice itself reaches the letter")
    check(bool(r.get("criteria_request")), "a vendor-held case gets the criteria demand")


def stage_dist():
    """dist/orthoappeal-demo.html inlines coverage.js, submit.js and data.js.
    Nothing rebuilt it, so the shipped app was serving the pre-2026-09-04 data:
    no D codes, none of the 896 promoted rows, none of the UHC repoint. A stale
    build is the one bug a user actually experiences."""
    print("\n[6] the shipped build matches the sources")
    dist = (ROOT / "dist" / "orthoappeal-demo.html")
    if not dist.exists():
        check(False, "dist build exists")
        return
    html = dist.read_text()
    cov = (ROOT / "mockups" / "assets" / "coverage.js").read_text()
    payload = cov[cov.index("{"):cov.rindex("}") + 1]
    check(payload in html, "dist carries the current coverage data",
          "run scripts/build_demo.py")
    sub = (ROOT / "mockups" / "assets" / "submit.js").read_text()
    check(sub[sub.index("{"):sub.rindex("}") + 1] in html,
          "dist carries the current submission routes", "run scripts/build_demo.py")
    check("cov.code === 'D'" in html, "dist knows the vendor-held status")


def stage_preflight():
    print("\n[5] keys and budget (nothing is called)")
    import os
    from retrieve import _load_env_files, _key_status
    _load_env_files()
    ks = _key_status()
    check(ks.get("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY looks like a real key")
    check(ks.get("OPENAI_API_KEY"), "OPENAI_API_KEY looks like a real key")
    check(bool(os.environ.get("WEB_SEARCH_API_KEY")), "WEB_SEARCH_API_KEY is set")
    print("      (balances are not checked here -- STUDY.command retrieve preflights search,\n"
          "       and the Anthropic balance shows up as a 400 on the first grade)")


def main() -> int:
    print("DRY RUN -- no API calls, no spend")
    stage_gitignore()
    cases, gold = stage_cases()
    stage_retrieval(cases, gold)
    stage_scoring(cases, gold)
    stage_letters(cases, gold)
    stage_live_path(cases)
    stage_dist()
    stage_money()
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
