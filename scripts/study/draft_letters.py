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
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    from synthetic_harness.letter_inputs import enrich
    from retrieve import _directory_row
    row = _directory_row(case) or {}
    return enrich({
        "case_identification": {
            "payer": case["payer"], "plan_name": case["payer"],
            "product_type": case["plan_type"], "state": case["state"],
            "procedure": case["surgery"], "cpt": case["cpt"],
            "denial_language": case["denial_reason"],
        },
        "policy_analysis": {
            "denial_category": case["denial_reason"],
            "apparent_reason": case["denial_reason"],
            "criteria_at_issue": quotes,
        },
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
    }, case.get("letter_text", ""), payer=case["payer"], plan_type=case["plan_type"],
              directory_note=row.get("note", ""))


def letter_ortho(case, res, model):
    from synthetic_harness.appeal_letter import generate_appeal_letter
    ans = res.get("answer") or {}
    t0 = time.time()
    shaped = _ortho_result(case, ans)
    out = generate_appeal_letter(shaped, model=model, sender="patient",
                                 patient_submission=case.get("chart_summary"))
    # What the writer was actually handed, grounded exactly as the generator
    # grounds it. The grader reads this; reading the retrieval file instead
    # showed it a list from before the extractor was fixed, and it flagged
    # real, supplied excerpts as invented.
    from synthetic_harness.appeal_letter import _ground_citations
    gr = _ground_citations(shaped)
    out["evidence"] = {
        "policy_title": ans.get("policy_title", ""), "policy_url": ans.get("policy_url", ""),
        "quotes": [c["excerpt"] for c in (gr.get("retrieval") or {}).get("citations", []) if c.get("verified", True)],
        "unverified": [c["excerpt"] for c in (gr.get("retrieval") or {}).get("citations", []) if not c.get("verified", True)],
        "submission_route": shaped.get("submission_route", ""),
        "criteria_request": shaped.get("criteria_request", ""),
    }
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


# The letter's own cap, well above anything a letter needs. The shared 8,000
# was sized for a JSON answer, and it counts the model's THINKING as output:
# Claude Sonnet 5 thinks by default, spent most of 8,000 tokens doing so, and
# six of its pilot letters were cut off mid-sentence -- then graded as
# unfinished, a penalty the harness imposed on a competitor, not one it earned.
LETTER_MAX_TOKENS = int(os.environ.get("MDPLUS_LETTER_MAX_TOKENS", "32000"))
# How each provider says "stopped because it hit the cap".
_TRUNCATED = {"max_tokens", "length", "MAX_TOKENS", "max_output_tokens", "incomplete"}


def letter_chatbot(system, case, res, model):
    """Ask the same chat for the letter, continuing from its own transcript.

    The provider comes from SYSTEMS rather than being hardcoded, so this one
    path carries every chatbot arm."""
    from synthetic_harness.api_runner import _resolve, _make_client
    provider_name, _ = SYSTEMS[system]
    prov, model = _resolve(provider_name, model)
    if not prov.available():
        return {"error": f"{prov.key_env} not set or SDK missing"}
    client = _make_client(prov, 900)
    transcript = res.get("transcript")
    usage = {"input_tokens": 0, "output_tokens": 0}
    t0 = time.time()
    if transcript:
        text = prov.continue_once(client=client, model=model, system="",
                                  transcript=transcript, ask=_ask(case),
                                  usage=usage, max_tokens=LETTER_MAX_TOKENS)
    else:
        # Phase 1 did not keep the transcript for this run; hand the model its
        # own answer back rather than dropping the case.
        prior = json.dumps(res.get("answer") or {}, indent=1)
        text = prov.continue_once(
            client=client, model=model, system="",
            transcript=[{"role": "user", "content": case["letter_text"]},
                        {"role": "assistant", "content": prior}],
            ask=_ask(case), usage=usage, max_tokens=LETTER_MAX_TOKENS)
    return {"letter_markdown": (text or "").strip(), "model": model,
            "usage": usage, "elapsed_s": round(time.time() - t0, 1)}


def _pending(key, systems, resume):
    """Runs that still need a letter, in key order.

    A letter.json holding an error is NOT finished: skipping it on resume is
    how phase 1 re-reported an old error against fixed code.
    """
    out = []
    for rid, info in key.items():
        if info["system"] not in systems or not (RUNS / rid / "result.json").exists():
            continue
        f = RUNS / rid / "letter.json"
        if resume and f.exists():
            try:
                if not json.loads(f.read_text()).get("error"):
                    continue
            except ValueError:
                pass
        out.append(rid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cases", default="",
                    help="comma-separated case_ids: draft only these, every arm. "
                         "For a smoke test before the full batch -- --limit takes "
                         "the first N in key order, which can land on one arm.")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--workers", type=int, default=1,
                    help="letters to draft at once (default 1).")
    a = ap.parse_args()
    _load_env_files()

    systems = list(SYSTEMS) if a.systems == "all" else [s.strip() for s in a.systems.split(",")]
    cases = {c["case_id"]: c for c in json.loads((STUDY / "cases.json").read_text())["cases"]}
    key = json.loads((STUDY / "unblinding.json").read_text())

    todo = _pending(key, systems, a.resume)
    if a.cases:
        want = {c.strip() for c in a.cases.split(",") if c.strip()}
        unknown = want - set(cases)
        if unknown:
            print(f"unknown case_id(s): {sorted(unknown)}"); return 1
        todo = [r for r in todo if key[r]["case_id"] in want]
    if a.limit:
        todo = todo[:a.limit]
    spend.banner("letters", len(todo), "claude-sonnet-5 / gpt-5.6-luna", 6000, 1500)

    lock = threading.Lock()
    broke: set[str] = set()
    out_of_budget: list[str] = []
    done = skipped = 0

    def one(rid):
        nonlocal done, skipped
        info = key[rid]
        with lock:
            if info["system"] in broke or out_of_budget:
                return None
        d = RUNS / rid
        case, res = cases[info["case_id"]], json.loads((d / "result.json").read_text())
        model = SYSTEMS[info["system"]][1]
        try:
            spend.check_budget()
            out = (letter_ortho(case, res, model) if info["system"].startswith("ortho")
                   else letter_chatbot(info["system"], case, res, model))
        except spend.OutOfFunds as e:
            with lock:
                out_of_budget.append(str(e))
            return None
        except Exception as e:  # noqa: BLE001
            out = {"error": f"{type(e).__name__}: {e}"}
        if spend.is_funding_error(out.get("error", "")):
            # Per provider, not per run: one arm's empty balance must not stop
            # the others.
            out["run_id"], out["case_id"] = rid, info["case_id"]
            (d / "letter.json").write_text(json.dumps(out, indent=1))
            with lock:
                broke.add(info["system"])
            return (f"\n  {info['system']}: out of funds at the provider -- dropping this arm.\n"
                    f"    {out['error'][:110]}\n"
                    f"    Add credit and re-run with --resume to pick it up.\n")
        if not out.get("error") and (out.get("usage") or {}).get("stop_reason") in _TRUNCATED:
            # A letter cut off by our cap is a harness failure, not the
            # model's letter. Error it so --resume drafts it again instead of
            # sending a half-letter to the grader.
            out["error"] = (f"cut off at the {LETTER_MAX_TOKENS}-token cap "
                            f"({out['usage']['stop_reason']})")
        if not out.get("error") and len(out.get("letter_markdown") or "") < 800:
            # Two of 60 came back as a header with no body. That is a failed
            # draft, not a short letter; --resume will draft it again.
            out["error"] = f"letter too short ({len(out.get('letter_markdown') or '')} chars): no body"
        running = None
        if out.get("usage"):
            out["usd"] = spend.cost(out.get("model", model), out["usage"])
            running = spend.record("letters", out.get("model", model), out["usage"], rid)
        out["run_id"], out["case_id"] = rid, info["case_id"]
        (d / "letter.json").write_text(json.dumps(out, indent=1))
        with lock:
            if out.get("error"):
                skipped += 1
                return f"  {rid} {info['system']:13s} ERR {out['error'][:90]}"
            done += 1
        n = len(out.get("letter_markdown", ""))
        line = f"  {rid} {info['system']:13s} ok ({n} chars)"
        if running is not None:
            line += f"  ${out.get('usd', 0):.3f}  running ${running:.2f}"
        return line

    workers = max(1, a.workers)
    if workers == 1:
        for rid in todo:
            line = one(rid)
            if line:
                print(line, flush=True)
            if out_of_budget or set(systems) <= broke:
                break
    else:
        print(f"  {len(todo)} to draft, {workers} at a time")
        # as_completed, not map: map yields in SUBMISSION order, so one slow
        # case holds back every line behind it and the run looks hung. A Gemini
        # case can take ten minutes and 70 searches while three others finish.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(one, item) for item in todo]
            for fut in as_completed(futures):
                line = fut.result()
                if line:
                    print(line, flush=True)

    print(f"\n{done} letters drafted, {skipped} errored -> {RUNS}")
    spend.report()
    if out_of_budget:
        print(f"\n  STOPPED: {out_of_budget[0]}")
        return 2
    if set(systems) <= broke:
        print("  Every arm is out of funds.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
