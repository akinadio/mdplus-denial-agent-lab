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
retrieval result as letter.json, so grade_letters_poc.py can read them blind.

  python3 scripts/study/run_letters_poc.py --systems all --resume
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

from run_poc import (SYSTEMS, STUDY, RUNS, _load_env_files,  # noqa: E402
                     _directory_row, _load_access, _access_route)

LETTER_ASK = (
    "Now write the appeal letter the patient should send, using what you just "
    "found. Quote the plan's own criteria and answer the stated denial reason, "
    "mapping each criterion to the records below. Use square-bracket "
    "placeholders only for details the records do not contain. Return the "
    "letter only."
)


def _ask(case):
    """Both arms get the identical chart. Anything less is not a comparison."""
    chart = (case.get("chart_summary") or "").strip()
    return LETTER_ASK + (f"\n\n{chart}" if chart else "")


def _ortho_result(case, ans):
    """Shape a phase-1 directory answer into what the production letter
    generator expects. Nothing is added that the arm did not find."""
    return {
        "case_identification": {
            "payer": case["payer"], "plan_name": case["payer"],
            "product_type": case["plan_type"], "state": case["state"],
            "procedure": case["surgery"], "cpt": case["cpt"],
            "denial_language": case["denial_reason"],
        },
        "policy_analysis": {
            "denial_category": case["denial_reason"],
            "apparent_reason": case["denial_reason"],
            "criteria_at_issue": ans.get("criteria_quotes") or [],
        },
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
                for q in (ans.get("criteria_quotes") or []) if q
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
    cases = {c["case_id"]: c for c in json.loads((STUDY / "poc_cases.json").read_text())["cases"]}
    key = json.loads((STUDY / "poc_unblinding.json").read_text())

    done = skipped = 0
    for rid, info in key.items():
        if info["system"] not in systems:
            continue
        d = RUNS / rid
        if not (d / "result.json").exists():
            continue
        if a.resume and (d / "letter.json").exists():
            continue
        if a.limit and done + skipped >= a.limit:
            break
        case, res = cases[info["case_id"]], json.loads((d / "result.json").read_text())
        model = SYSTEMS[info["system"]][1]
        try:
            out = (letter_ortho(case, res, model) if info["system"].startswith("ortho")
                   else letter_chatgpt(case, res, model))
        except Exception as e:  # noqa: BLE001
            out = {"error": f"{type(e).__name__}: {e}"}
        out["run_id"], out["case_id"] = rid, info["case_id"]
        (d / "letter.json").write_text(json.dumps(out, indent=1))
        if out.get("error"):
            skipped += 1
            print(f"  {rid} {info['system']:13s} ERR {out['error'][:90]}")
        else:
            done += 1
            n = len(out.get("letter_markdown", ""))
            print(f"  {rid} {info['system']:13s} ok ({n} chars)")
    print(f"\n{done} letters drafted, {skipped} errored -> {RUNS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
