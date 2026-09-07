#!/usr/bin/env python3
"""Grade the appeal letters blind, against the case's gold record.

The grader never learns which system wrote a letter -- it sees the letter, the
denial it answers, and the correct policy for that case. Run ids are shuffled
so even ordering carries no signal.

The rubric is the protocol's own questions, one field each:

  cites_correct_policy   the governing document for this denial, by title/URL
  cites_wrong_policy     names a different document as governing
  unsupported_attribution  states, without quotation marks, that the plan
                         "requires" or "says" something the writer had no
                         source for. Quoted text is NOT judged here -- that is
                         quote_check.py's job and it is mechanical.
  deadline_correct       the appeal deadline stated in the denial notice
  route_given            says where and how to send it
  demands_criteria       for vendor-held and no-policy cases, asks in writing
                         for the criteria actually applied
  factual_errors         every wrong statement of fact, listed
  completeness           0-4, how much of a sendable appeal is present

"Appeal-fatal error" is gone. It was one label covering an invented quotation,
a letter posted to the wrong insurer, and an unfinished template -- different
defects, different causes, different fixes. Each is counted on its own now:

  quote_not_in_policy    a quotation that is not in the cited document. Checked
                         mechanically against the fetched text by
                         quote_check.py, not judged, because it is a string
                         comparison and a judge would only add noise.
  wrong_policy_cited     names a document that does not govern this denial
  wrong_recipient        addressed to the wrong plan
  wrong_deadline         states a date the notice does not support
  invented_identifier    a policy number, section heading or effective date the
                         writer had no source for
  unfinished             placeholders where the records supplied the fact

A caveat that belongs in the writeup, not just here: a Claude model grading
letters that a Claude model wrote is not a neutral judge. Treat this as the
screen, and have a blinded human read a random sample before any number is
reported.

  python3 scripts/study/grade_letters.py --resume
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
from retrieve import STUDY, RUNS, _load_env_files  # noqa: E402
import spend  # noqa: E402

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

The writer was given the patient's clinical records. A square-bracket
placeholder is a defect only where the records supplied the fact -- judge
against the records, not against an ideal letter. A placeholder for something
the records genuinely do not contain is correct behavior, not an error.

Answer with JSON only, no prose, using exactly these keys:
cites_correct_policy (bool), cites_wrong_policy (bool), unsupported_attribution
(bool -- attributes a rule to the plan, outside quotation marks, with no source;
do NOT judge quoted text, it is checked separately), demands_criteria (bool),
factual_errors (list of at most 5 short strings), uses_records (bool -- maps the plan's
criteria to specific facts from the records), wrong_policy_cited (bool),
wrong_recipient (bool), wrong_deadline (bool), invented_identifier (bool),
unfinished (bool -- placeholders where the records supplied the fact),
worst_defect (string, one short phrase naming the most serious problem, or ""),
completeness (integer 0-4), notes (string, one sentence)."""


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
            f"CLINICAL RECORDS THE WRITER WAS GIVEN\n{case.get('chart_summary') or '(none)'}\n\n"
            f"APPEAL LETTER TO GRADE\n{letter}\n\n"
            "Return the JSON now.")


def mechanical(letter: str, case: dict, g: dict) -> dict:
    """The parts of a grade that are facts, not judgments.

    Deadline: the notice states one date; either the letter has it or not.
    Route: does the letter say where the appeal goes -- an address, fax,
    portal, or the honest fallback of the address on the denial notice.
    Quotes: checked against the policy, with the denial notice and the chart
    as legitimate other sources. A judge was getting all three wrong in both
    directions; a string comparison does not."""
    from synthetic_harness.quote_check import check as quote_check
    import re as _re
    L = letter or ""
    q = quote_check(L, g.get("policy_url", ""),
                    other_sources=[case.get("letter_text", ""), case.get("chart_summary", "")])
    route = bool(_re.search(
        r"(?i)\b(fax|p\.?o\.? box|portal|mail (it|this|the appeal|to)|by mail|"
        r"address (listed|printed|shown|on) (in|on)? ?(my|the|your) denial|"
        r"number on the back of|member services|appeals? department,)", L))
    # The deadline in any of the ways a letter writes a date.
    import datetime as _dt
    dl = case.get("appeal_deadline", "")
    forms = {dl}
    try:
        d = _dt.date.fromisoformat(dl)
        forms |= {d.strftime("%B %d, %Y"), d.strftime("%B %-d, %Y"), d.strftime("%b %-d, %Y"),
                  d.strftime("%-m/%-d/%Y"), d.strftime("%m/%d/%Y"), d.strftime("%d %B %Y")}
    except Exception:  # noqa: BLE001
        pass
    deadline = any(f and f in L for f in forms)
    # Naming the governing document is a fact: its URL, or most of its title.
    url = (g.get("policy_url") or "").strip()
    title = (g.get("policy_title") or "").strip()
    words = [w for w in _re.findall(r"[A-Za-z0-9]{3,}", title.lower()) if w not in ("the", "and", "for", "html", "pdf", "via")]
    hit_url = bool(url) and (url.rstrip("/") in L or url.split("://", 1)[-1].rstrip("/") in L)
    hit_title = bool(words) and sum(w in L.lower() for w in words) >= max(2, int(0.6 * len(words)))
    cites = hit_url or hit_title
    out = {"quotes": q, "quote_not_in_policy": bool(q["not_in_policy"]),
           "deadline_correct": deadline, "route_given": route}
    if g.get("correct_behavior") in ("cite_document", "cite_and_route"):
        out["cites_correct_policy"] = cites
    return out


def rescore() -> int:
    """Recompute the mechanical fields for every existing grade. No model, no
    cost -- for when the checker changes, so the judgments already paid for
    are kept and only the facts are recounted."""
    cases = {c["case_id"]: c for c in json.loads((STUDY / "cases.json").read_text())["cases"]}
    gold = {g["case_id"]: g for g in json.loads((STUDY / "gold.json").read_text())["entries"]}
    out_path = STUDY / "letter_grades.json"
    grades = json.loads(out_path.read_text())
    n = 0
    for rid, g in grades.items():
        if g.get("outcome") != "graded":
            continue
        lt = json.loads((RUNS / rid / "letter.json").read_text())
        g.update(mechanical(lt.get("letter_markdown") or "", cases[g["case_id"]], gold[g["case_id"]]))
        n += 1
    out_path.write_text(json.dumps(grades, indent=1))
    print(f"rescored the mechanical fields on {n} grades (no model calls)")
    return 0


def main() -> int:
    if "--rescore" in sys.argv:
        return rescore()
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

    cases = {c["case_id"]: c for c in json.loads((STUDY / "cases.json").read_text())["cases"]}
    gold = {g["case_id"]: g for g in json.loads((STUDY / "gold.json").read_text())["entries"]}
    out_path = STUDY / "letter_grades.json"
    grades = json.loads(out_path.read_text()) if (a.resume and out_path.exists()) else {}

    rids = sorted(p.parent.name for p in RUNS.glob("r-*/letter.json"))
    random.Random(SEED).shuffle(rids)   # ordering must carry no signal either
    n = 0
    todo = [r for r in rids if grades.get(r, {}).get("outcome") not in ("graded", "no_letter")]
    spend.banner("grading", len(todo), GRADER_MODEL, 5000, 600)
    for rid in rids:
        # A grader_error is not a grade. Retry it.
        if grades.get(rid, {}).get("outcome") in ("graded", "no_letter"):
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
            spend.check_budget()
            resp = client.messages.create(
                model=GRADER_MODEL, max_tokens=4000, system=SYSTEM,
                messages=[{"role": "user",
                           "content": _prompt(cases[cid], gold[cid], text)}])
            body = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
            g = extract_json(body) or {}
            # A grade with the judgment fields missing is not a grade. Every
            # missing field was being read as "no" -- a parse failure scored as
            # a bad letter, on 19 of 29 in-library letters on 2026-09-06.
            REQUIRED = ("uses_records", "completeness", "unsupported_attribution",
                        "wrong_policy_cited", "unfinished")
            if any(g.get(k) is None for k in REQUIRED):
                g = {"outcome": "grader_incomplete", "raw": body[-1500:],
                     "missing": [k for k in REQUIRED if g.get(k) is None]}
            else:
                g["outcome"] = "graded"
            u = getattr(resp, "usage", None)
            usage = {"input_tokens": getattr(u, "input_tokens", 0) or 0,
                     "output_tokens": getattr(u, "output_tokens", 0) or 0}
            g["usd"] = spend.cost(GRADER_MODEL, usage)
            spend.record("grading", GRADER_MODEL, usage, rid)
            if g["outcome"] == "graded":
                g.update(mechanical(text, cases[cid], gold[cid]))
        except spend.OutOfFunds as e:
            out_path.write_text(json.dumps(grades, indent=1))
            print(f"\n  STOPPED: {e}"); return 2
        except Exception as e:  # noqa: BLE001
            g = {"outcome": "grader_error", "error": f"{type(e).__name__}: {e}"}
            if spend.is_funding_error(e):
                g["case_id"] = cid; grades[rid] = g
                out_path.write_text(json.dumps(grades, indent=1))
                print(f"\n  STOPPED, out of funds at the provider: {str(e)[:120]}\n"
                      f"  {n} graded and saved; add credit and re-run with --resume.")
                return 2
        g["case_id"] = cid
        grades[rid] = g
        out_path.write_text(json.dumps(grades, indent=1))
        n += 1
        if g.get("outcome") != "graded":
            mark = g["outcome"]
        elif g.get("quote_not_in_policy"):
            mark = f"{g['quotes']['not_in_policy']} quote(s) NOT in the policy"
        else:
            mark = g.get("worst_defect") or "clean"
        print(f"  {rid} graded -> {mark}   running ${spend.total():.2f}")
    print(f"\ngraded {n} letters -> {out_path}")
    spend.report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
