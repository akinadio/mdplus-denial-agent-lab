#!/usr/bin/env python3
"""Grade the appeal letters blind, against the case's gold record.

The grader never learns which system wrote a letter -- it sees the letter, the
denial it answers, and the correct policy for that case. Run ids are shuffled
so even ordering carries no signal.

The rubric is the protocol's own questions, one field each:

  cites_correct_policy   the governing document for this denial, by title/URL
  cites_wrong_policy     names a different document as governing
  fabricated_criteria    presents language as the plan's own that the arm never
                         had -- the failure that matters most, because a quoted
                         criterion is what a reviewer checks first
  deadline_correct       the appeal deadline stated in the denial notice
  route_given            says where and how to send it
  demands_criteria       for vendor-held and no-policy cases, asks in writing
                         for the criteria actually applied
  factual_errors         every wrong statement of fact, listed
  appeal_fatal_error     an error a reviewer could reasonably act on to uphold
                         the denial -- wrong policy, invented criterion, wrong
                         deadline, wrong recipient. Pre-specified, not inferred
                         from any appeal outcome, because we never observe one.
  completeness           0-4, how much of a sendable appeal is present

A caveat that belongs in the writeup, not just here: a Claude model grading
letters that a Claude model wrote is not a neutral judge. Treat this as the
screen, and have a blinded human read a random sample before any number is
reported.

  python3 scripts/study/grade_letters_poc.py --resume
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from run_poc import STUDY, RUNS, _load_env_files  # noqa: E402

GRADER_MODEL = os.environ.get("POC_GRADER_MODEL", "claude-opus-5")
SEED = 20260905

SYSTEM = """You grade appeal letters written for patients whose surgery was denied.

You are given the denial, the correct governing policy for that case, and one
letter. You do not know who or what wrote the letter. Judge only what is on the
page. Do not reward length, confidence or polish.

A criterion presented as the plan's own language is the most consequential
thing in an appeal letter: a reviewer checks it first, and one that does not
exist in the cited policy discredits the letter. Flag it whenever the letter
quotes or paraphrases plan criteria that the evidence given to the writer did
not contain.

Answer with JSON only, no prose, using exactly these keys:
cites_correct_policy (bool), cites_wrong_policy (bool), fabricated_criteria
(bool), deadline_correct (bool), route_given (bool), demands_criteria (bool),
factual_errors (list of strings), appeal_fatal_error (bool),
appeal_fatal_reason (string, empty if none), completeness (integer 0-4),
notes (string, one sentence)."""


def _prompt(case, gold, letter):
    correct = (f"Title: {gold.get('policy_title') or '(none -- this payer publishes no policy for this code)'}\n"
               f"URL: {gold.get('policy_url') or '(none)'}\n"
               f"Effective: {gold.get('effective_date') or '(n/a)'}")
    expected = {
        "cite_document": "Cite this policy and answer the denial from its criteria.",
        "cite_and_route": ("Cite this policy AND tell the patient how to demand the "
                           "criteria in writing -- the policy is public but the "
                           "criteria in it are held by a private review vendor."),
        "abstain_and_route": ("No public policy exists. The letter must not name a "
                              "governing document, and must tell the patient how to "
                              "demand the criteria that were applied."),
    }[gold["correct_behavior"]]
    return (f"DENIAL NOTICE\n{case['letter_text']}\n\n"
            f"CORRECT GOVERNING POLICY FOR THIS CASE\n{correct}\n\n"
            f"WHAT A CORRECT LETTER DOES HERE\n{expected}\n\n"
            f"APPEAL LETTER TO GRADE\n{letter}\n\n"
            "Return the JSON now.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    _load_env_files()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set."); return 1

    import anthropic
    from synthetic_harness.agent_runner import extract_json
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=300.0)

    cases = {c["case_id"]: c for c in json.loads((STUDY / "poc_cases.json").read_text())["cases"]}
    gold = {g["case_id"]: g for g in json.loads((STUDY / "poc_gold.json").read_text())["entries"]}
    out_path = STUDY / "poc_letter_grades.json"
    grades = json.loads(out_path.read_text()) if (a.resume and out_path.exists()) else {}

    rids = sorted(p.parent.name for p in RUNS.glob("r-*/letter.json"))
    random.Random(SEED).shuffle(rids)   # ordering must carry no signal either
    n = 0
    for rid in rids:
        if rid in grades:
            continue
        if a.limit and n >= a.limit:
            break
        lt = json.loads((RUNS / rid / "letter.json").read_text())
        text = (lt.get("letter_markdown") or "").strip()
        if not text:
            grades[rid] = {"outcome": "no_letter", "error": lt.get("error", "")}
            n += 1
            continue
        cid = lt["case_id"]
        try:
            resp = client.messages.create(
                model=GRADER_MODEL, max_tokens=1500, system=SYSTEM,
                messages=[{"role": "user",
                           "content": _prompt(cases[cid], gold[cid], text)}])
            body = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
            g = extract_json(body) or {}
            g["outcome"] = "graded"
        except Exception as e:  # noqa: BLE001
            g = {"outcome": "grader_error", "error": f"{type(e).__name__}: {e}"}
        g["case_id"] = cid
        grades[rid] = g
        out_path.write_text(json.dumps(grades, indent=1))
        n += 1
        mark = "fatal" if g.get("appeal_fatal_error") else ("ok" if g.get("outcome") == "graded" else g["outcome"])
        print(f"  {rid} graded -> {mark}")
    print(f"\ngraded {n} letters -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
