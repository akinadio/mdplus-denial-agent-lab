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

    # A library hit must still verify: the library keeps quotes, the cache keeps
    # the text, and without the text every library hit read as unreadable.
    lib_path = PT.LIBRARY
    lib_backup = lib_path.read_text() if lib_path.exists() else None
    try:
        lib_path.write_text(json.dumps({"policies": [
            {"policy_url": fake_url, "policy_title": "dry", "quotes": found}]}))
        PT._LIB = None
        got = PT.criteria_for(fake_url, "27447", allow_fetch=False)
        check(got["source"] == "library" and bool(got["text"]),
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
    from draft_letters import _notice_fields
    nf = _notice_fields(c["letter_text"])
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
    check(set(parsed) >= {"completeness", "unsupported_attribution", "uses_records"},
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
    check(spend.cost("gpt-5.6-luna", {"input_tokens": 1_000_000, "output_tokens": 0}) == 1.0,
          "cost is computed from tokens")
    os.environ["STUDY_BUDGET_USD"] = "0.0000001"
    try:
        spend.check_budget(); check(spend.total() == 0, "an empty ledger is under any budget")
    except spend.OutOfFunds:
        check(True, "a spent budget raises before the next paid call")
    finally:
        os.environ.pop("STUDY_BUDGET_USD", None)
    # resume must retry failures, in all three paid scripts
    src = (ROOT / "scripts/study/grade_letters.py").read_text()
    check("max_tokens=4000" in src, "grade_letters.py: the grader has room to finish its JSON")
    check('"grader_incomplete"' in src and "REQUIRED" in src,
          "grade_letters.py: a grade with missing fields is not counted as a grade")
    for f, marker in (("retrieve.py", 'if not ("error" in prior or "skipped" in prior)'),
                      ("draft_letters.py", 'if not prior.get("error")'),
                      ("grade_letters.py", 'in ("graded", "no_letter")')):
        check(marker in (ROOT / "scripts/study" / f).read_text(),
              f"{f}: --resume retries a failed item instead of skipping it")


def stage_gitignore():
    print("\n[0] nothing is being silently ignored")
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "scripts/study/check_gitignore.py")],
                       capture_output=True, text=True, cwd=ROOT)
    check(r.returncode == 0, "every data file under data/policy_platform is trackable",
          r.stdout.strip()[-400:])


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
