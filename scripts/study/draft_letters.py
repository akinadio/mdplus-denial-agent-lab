#!/usr/bin/env python3
"""Phase 2: every arm drafts the appeal letter.

Phase 1 asked only which policy document governs the denial. That is half the
study. The letter is what the patient actually sends, and a study that stops at
retrieval cannot answer the protocol's questions about completeness or about
errors that could cost the appeal.

Both arms draft from their OWN phase-1 answer, which is the honest comparison:
OrthoAppeals through the production generator in synthetic_harness/
appeal_letter.py, ChatGPT by being asked for the letter the way a patient would
ask -- same chat, same evidence it just found, right or wrong.

One model throughout (Sonnet for OrthoAppeals). Letters land beside the
retrieval result as letter.json, so grade_letters.py can read them blind.

  python3 scripts/study/draft_letters.py --systems all --resume
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from retrieve import (SYSTEMS, STUDY, RUNS, _load_env_files,  # noqa: E402
                     _directory_row, _load_access, _access_route)
from synthetic_harness.policy_text import criteria_for  # noqa: E402
import spend  # noqa: E402

LETTER_ASK = (
    "Now write the appeal letter the patient should send, using what you just "
    "found. Answer the stated denial reason and map it to the records below.\n\n"
    "QUOTING RULE, and it is absolute: the only text you may put in quotation "
    "marks or attribute to the plan is text you actually retrieved from the "
    "policy document. If you did not retrieve the policy text, write the "
    "argument in your own words and say plainly that the plan has not been "
    "quoted. Never reconstruct or invent policy language, a policy number, a "
    "section heading or an effective date.\n\n"
    "Use square-bracket placeholders only for details the records do not "
    "contain. Return the letter only."
)


def _ask(case):
    """Both arms get the identical chart. Anything less is not a comparison."""
    chart = (case.get("chart_summary") or "").strip()
    return LETTER_ASK + (f"\n\n{chart}" if chart else "")


def _notice_fields(text):
    """Member, ID, dates and reference number, read off the denial notice the
    same way a person would. Production gets these from extraction; the study's
    synthetic notices are regular enough to read directly."""
    import re
    out = {}
    for key, pat in (("member_name", r"Member:\s*(.+)"), ("member_id", r"Member ID:\s*(\S+)"),
                     ("denial_date", r"Date of notice:\s*(\S+)"),
                     ("reference_number", r"Reference number:\s*(\S+)")):
        m = re.search(pat, text)
        if m:
            out[key] = m.group(1).strip()
    return out


def _ortho_result(case, ans):
    """Shape a phase-1 directory answer into what the production letter
    generator expects, having first READ the policy.

    The excerpts handed to the letter are lifted verbatim out of the fetched
    document. Before 2026-09-05 this passed our own internal research note as
    "criteria", and the letter -- told to quote the plan -- invented language
    instead. Nothing goes in here that is not in the payer's document."""
    # Grounding happens inside the production generator now; the study asks for
    # the same thing here only so the shaped record shows what it will get.
    got = criteria_for((ans.get("policy_url") or "").strip(), case["cpt"])
    quotes = got["quotes"]
    return {
        "case_identification": {
            "payer": case["payer"], "plan_name": case["payer"],
            "product_type": case["plan_type"], "state": case["state"],
            "procedure": case["surgery"], "cpt": case["cpt"],
            "denial_language": case["denial_reason"],
            **_notice_fields(case.get("letter_text", "")),
        },
        "policy_analysis": {
            "denial_category": case["denial_reason"],
            "apparent_reason": case["denial_reason"],
            "criteria_at_issue": quotes,
        },
        "denial_notice_text": case.get("letter_text", ""),
        "criteria_request": ans.get("how_to_obtain_criteria") or "",
        "appeal_deadline": ans.get("appeal_deadline") or case["appeal_deadline"],
        "submission_route": ans.get("submission_route") or "",
        "retrieval": {
            "selected_source": {
                "title": ans.get("policy_title", ""),
                "url": ans.get("policy_url", ""),
                "effective_date": ans.get("effective_date", ""),
            },
            "citations": [
                {"claim": "plan criteria", "reference": ans.get("policy_title", ""),
                 "excerpt": q}
                for q in quotes
            ],
        },
    }


def letter_ortho(case, res, model):
    from synthetic_harness.appeal_letter import generate_appeal_letter
    ans = res.get("answer") or {}
    t0 = time.time()
    out = generate_appeal_letter(_ortho_result(case, ans), model=model, sender="patient",
                                 patient_submission=case.get("chart_summary"))
    out["elapsed_s"] = round(time.time() - t0, 1)
    # An arm that abstained still owes the patient a letter -- one that demands
    # the criteria. Withholding the letter here would flatter the arm by
    # keeping its weakest cases out of the graded set.
    if not ans.get("policy_url"):
        r = _access_route(case["payer"], (_directory_row(case) or {}).get("note", ""),
                          _load_access())
        out["abstained"] = True
        out["route_given"] = r.get("how", "")
    return out


def letter_chatgpt(case, res, model):
    """Ask the same chat for the letter, continuing from its own transcript."""
    from synthetic_harness.api_runner import _resolve, _make_client, MAX_OUTPUT_TOKENS
    prov, model = _resolve("openai", model)
    if not prov.available():
        return {"error": f"{prov.key_env} not set or SDK missing"}
    client = _make_client(prov, 900)
    transcript = res.get("transcript")
    usage = {"input_tokens": 0, "output_tokens": 0}
    t0 = time.time()
    if transcript:
        text = prov.continue_once(client=client, model=model, system="",
                                  transcript=transcript, ask=_ask(case),
                                  usage=usage, max_tokens=MAX_OUTPUT_TOKENS)
    else:
        # Phase 1 did not keep the transcript for this run; hand the model its
        # own answer back rather than dropping the case.
        from synthetic_harness.providers import OpenAIProvider
        prior = json.dumps(res.get("answer") or {}, indent=1)
        text = prov.continue_once(
            client=client, model=model, system="",
            transcript=[{"role": "user", "content": case["letter_text"]},
                        {"role": "assistant", "content": prior}],
            ask=_ask(case), usage=usage, max_tokens=MAX_OUTPUT_TOKENS)
    return {"letter_markdown": (text or "").strip(), "model": model,
            "usage": usage, "elapsed_s": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    _load_env_files()

    systems = list(SYSTEMS) if a.systems == "all" else [s.strip() for s in a.systems.split(",")]
    cases = {c["case_id"]: c for c in json.loads((STUDY / "cases.json").read_text())["cases"]}
    key = json.loads((STUDY / "unblinding.json").read_text())

    todo = [rid for rid, info in key.items() if info["system"] in systems
            and (RUNS / rid / "result.json").exists()
            and not (a.resume and (RUNS / rid / "letter.json").exists()
                     and not json.loads((RUNS / rid / "letter.json").read_text()).get("error"))]
    spend.banner("letters", len(todo), "claude-sonnet-5 / gpt-5.6-luna", 6000, 1500)
    done = skipped = 0
    for rid, info in key.items():
        if info["system"] not in systems:
            continue
        d = RUNS / rid
        if not (d / "result.json").exists():
            continue
        if a.resume and (d / "letter.json").exists():
            prior = json.loads((d / "letter.json").read_text())
            # A failed draft is not a finished one. Skipping it on resume is
            # how phase 1 re-reported an old error against fixed code.
            if not prior.get("error"):
                continue
        if a.limit and done + skipped >= a.limit:
            break
        case, res = cases[info["case_id"]], json.loads((d / "result.json").read_text())
        model = SYSTEMS[info["system"]][1]
        try:
            spend.check_budget()
            out = (letter_ortho(case, res, model) if info["system"].startswith("ortho")
                   else letter_chatgpt(case, res, model))
        except spend.OutOfFunds as e:
            print(f"\n  STOPPED: {e}\n  {done} letters drafted and saved.")
            return 2
        except Exception as e:  # noqa: BLE001
            out = {"error": f"{type(e).__name__}: {e}"}
        if spend.is_funding_error(out.get("error", "")):
            out["run_id"], out["case_id"] = rid, info["case_id"]
            (d / "letter.json").write_text(json.dumps(out, indent=1))
            print(f"\n  STOPPED, out of funds at the provider: {out['error'][:120]}\n"
                  f"  {done} letters drafted and saved; add credit and re-run with --resume.")
            return 2
        if not out.get("error") and len(out.get("letter_markdown") or "") < 800:
            # Two of 60 came back as a header with no body. That is a failed
            # draft, not a short letter; --resume will draft it again.
            out["error"] = f"letter too short ({len(out.get('letter_markdown') or '')} chars): no body"
        if out.get("usage"):
            out["usd"] = spend.cost(out.get("model", model), out["usage"])
            running = spend.record("letters", out.get("model", model), out["usage"], rid)
        out["run_id"], out["case_id"] = rid, info["case_id"]
        (d / "letter.json").write_text(json.dumps(out, indent=1))
        if out.get("error"):
            skipped += 1
            print(f"  {rid} {info['system']:13s} ERR {out['error'][:90]}")
        else:
            done += 1
            n = len(out.get("letter_markdown", ""))
            print(f"  {rid} {info['system']:13s} ok ({n} chars)  ${out.get('usd', 0):.3f}"
                  f"  running ${running:.2f}" if out.get("usage") else
                  f"  {rid} {info['system']:13s} ok ({n} chars)")
    print(f"\n{done} letters drafted, {skipped} errored -> {RUNS}")
    spend.report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
