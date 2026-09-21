#!/usr/bin/env python3
"""Criteria for ONE operation, read out of the policy by a model, checked by code.

Why this exists
---------------
The big guidelines -- Carelon Joint Surgery, Evolent Musculoskeletal Surgery,
eviCore -- cover a dozen operations in one document. Picking the right section
with text-matching rules failed in both directions on 2026-09-21: OrthoAppeals
handed a shoulder labral repair the criteria for shoulder REPLACEMENT, another
the cervical-fusion rule, and every rule that fixed one document broke
another. A reader has to understand the document to find the section.

So a model reads it, once per (document, operation), ahead of time -- and is
trusted with nothing but the choice of sentences:

  * every sentence it returns is checked, character for character (ignoring
    whitespace and case), against the document. A sentence that is not there
    is dropped and counted. Nothing paraphrased can reach a patient's letter.
  * a sentence that names a different operation or a different part of the
    body is dropped too (quote_relevance.other_procedure), as a second check
    on the model's choice.
  * "this document has no criteria for this operation" is a real answer and
    is recorded as one -- it is how a wrong document gets caught.

Output: data/policy_platform/section_criteria.json, keyed "<url>||<cpt>".
policy_text.criteria_for() reads it before anything else.

Usage
  python3 scripts/policy_platform/build_section_criteria.py            # study pairs
  python3 scripts/policy_platform/build_section_criteria.py --directory # every VERIFIED row
  ... --only-key "<url>||<cpt>"   --redo   --workers 4   --dry
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "study")]

from synthetic_harness import policy_text as PT                       # noqa: E402
from synthetic_harness.quote_relevance import other_procedure         # noqa: E402

OUT = ROOT / "data" / "policy_platform" / "section_criteria.json"
DIRECTORY = ROOT / "data" / "policy_platform" / "app_option_policy_directory.csv"
MODEL = "claude-opus-5"
MAX_DOC_CHARS = 450_000          # ~115k tokens; the largest study document is 400k

SURGERY_NAME = {
    "27130": "total hip replacement (total hip arthroplasty)",
    "27447": "total knee replacement (total knee arthroplasty)",
    "27446": "partial (unicompartmental) knee replacement",
    "29880": "knee arthroscopy with meniscectomy", "29881": "knee arthroscopy with meniscectomy",
    "29888": "anterior cruciate ligament (ACL) reconstruction",
    "29914": "hip arthroscopy for femoroacetabular impingement / labral pathology",
    "23472": "total shoulder replacement (total shoulder arthroplasty)",
    "29827": "arthroscopic rotator cuff repair",
    "29806": "arthroscopic shoulder capsulorrhaphy / labral repair for shoulder instability",
    "22551": "anterior cervical discectomy and fusion (ACDF)",
    "22612": "lumbar spinal fusion",
    "63030": "lumbar laminotomy / discectomy for a herniated disc (decompression)",
    "27702": "total ankle replacement (total ankle arthroplasty)",
    "28296": "bunion (hallux valgus) correction",
}

SYSTEM = """You read a health plan's medical policy and find the rules that decide \
whether ONE specific operation is covered.

Return ONLY a JSON object:
{
 "covered": true | false,          // does this document state medical-necessity criteria for THIS operation?
 "section_heading": "<the heading or lead-in sentence that opens this operation's criteria, copied exactly>",
 "criteria": [ {"text": "<copied exactly>", "topic": "conservative_care" | "imaging" | "clinical" | "documentation" | "other"} ],
 "why_not": "<if covered is false: one sentence, e.g. 'document covers knee procedures only'>"
}

Rules -- these are absolute:
1. COPY, never paraphrase. Every "text" must appear in the document exactly as \
written, word for word. Do not fix typos, join lines differently, or drop words. \
If a criterion is long, copy a contiguous piece of it (25 to 500 characters).
2. Only criteria for THE OPERATION NAMED. Not a neighbouring operation in the \
same document (a revision, a partial vs total replacement, a different joint, a \
different spinal level, a different arthroscopic procedure), not the \
exclusions or "not medically necessary" list, not background, evidence reviews, \
study results, definitions, coding tables or references.
3. Include the requirements a reviewer checks: symptoms and function, duration \
and type of conservative (non-surgical) treatment, imaging findings, exam \
findings, and documentation required. 6 to 16 items is typical.
4. If the document does not contain criteria for this operation, set \
"covered": false and return an empty list. Saying so is the correct answer; \
do not substitute a related operation's criteria.

The document follows.

<document>
{DOC}
</document>"""


def _load_env():
    from retrieve import _load_env_files
    _load_env_files()


def study_pairs():
    cases = json.loads((ROOT / "study" / "cases.json").read_text())["cases"]
    gold = {g["case_id"]: g for g in json.loads((ROOT / "study" / "gold.json").read_text())["entries"]}
    out = {}
    for c in cases:
        u = (gold.get(c["case_id"]) or {}).get("policy_url") or ""
        if u and c["stratum"] == "in_library":
            out[f"{u}||{c['cpt']}"] = (u, c["cpt"])
    return out


def directory_pairs():
    out = {}
    for r in csv.DictReader(DIRECTORY.open()):
        if r.get("status") == "VERIFIED" and r.get("policy_url") and r.get("cpt") in SURGERY_NAME:
            out[f"{r['policy_url']}||{r['cpt']}"] = (r["policy_url"], r["cpt"])
    return out


def doc_text(url):
    p = PT._key(url)
    if p.exists():
        try:
            t = json.loads(p.read_text()).get("text") or ""
            if t:
                return t
        except ValueError:
            pass
    return PT.policy_text(url).get("text") or ""


def extract(client, url, cpt):
    from synthetic_harness.providers import call_with_backoff
    from synthetic_harness.agent_runner import extract_json
    text = doc_text(url)
    if not text:
        return {"url": url, "cpt": cpt, "covered": None, "criteria": [],
                "error": "document text unavailable"}
    system = [{"type": "text", "text": SYSTEM.replace("{DOC}", text[:MAX_DOC_CHARS]),
               "cache_control": {"type": "ephemeral"}}]
    ask = (f"The operation: {SURGERY_NAME.get(cpt, 'CPT ' + cpt)} (CPT {cpt}). "
           f"Return the JSON object.")
    resp = call_with_backoff(client.messages.create, model=MODEL, max_tokens=16000,
                             system=system, messages=[{"role": "user", "content": ask}])
    body = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    got = extract_json(body) or {}
    u = resp.usage
    usage = {"input_tokens": u.input_tokens or 0, "output_tokens": u.output_tokens or 0,
             "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
             "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0}
    kept, unverified, wrong_op = [], [], []
    for item in got.get("criteria") or []:
        q = (item.get("text") if isinstance(item, dict) else str(item)) or ""
        topic = item.get("topic", "other") if isinstance(item, dict) else "other"
        if not PT.verify_quote(q, text):
            unverified.append(q[:200])
        elif other_procedure(q, cpt):
            wrong_op.append({"text": q.strip(), "topic": topic})
        else:
            kept.append({"text": q.strip(), "topic": topic})
    head = got.get("section_heading") or ""
    return {
        "url": url, "cpt": cpt, "covered": bool(got.get("covered")) if got else None,
        "section_heading": head, "heading_verified": PT.verify_quote(head, text) if head else False,
        "criteria": kept, "dropped_not_in_document": unverified,
        "dropped_other_operation": wrong_op, "why_not": got.get("why_not", ""),
        "doc_chars": len(text), "doc_truncated_for_model": len(text) > MAX_DOC_CHARS,
        "model": MODEL, "usage": usage, "extracted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stop_reason": getattr(resp, "stop_reason", ""),
        "error": "" if got else f"unparseable model output: {body[-300:]}",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--directory", action="store_true")
    ap.add_argument("--only-key", default="")
    ap.add_argument("--cases", default="", help="comma-separated study case_ids")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true", help="list the work and stop")
    ap.add_argument("--recheck", action="store_true",
                    help="re-apply the other-operation check to saved results; no model calls")
    a = ap.parse_args()

    if a.recheck:
        # The check can be wrong too (it once read "myelopathy" as cervical and
        # dropped a real lumbar criterion). Re-run it over what the model
        # returned instead of paying to extract again.
        done = json.loads(OUT.read_text()) if OUT.exists() else {}
        moved = 0
        for k, r in done.items():
            keep = []
            for d in r.get("dropped_other_operation") or []:
                item = d if isinstance(d, dict) else {"text": d, "topic": "other"}
                if other_procedure(item["text"], r.get("cpt", "")):
                    keep.append(item)
                else:
                    r.setdefault("criteria", []).append(item)
                    moved += 1
            r["dropped_other_operation"] = keep
        OUT.write_text(json.dumps(done, indent=1, ensure_ascii=False))
        print(f"rechecked {len(done)} entries, restored {moved} criteria")
        return 0

    pairs = directory_pairs() if a.directory else study_pairs()
    if a.cases:
        want = {c.strip() for c in a.cases.split(",") if c.strip()}
        cases = json.loads((ROOT / "study" / "cases.json").read_text())["cases"]
        gold = {g["case_id"]: g for g in json.loads((ROOT / "study" / "gold.json").read_text())["entries"]}
        pairs = {f"{gold[c['case_id']]['policy_url']}||{c['cpt']}":
                 (gold[c["case_id"]]["policy_url"], c["cpt"]) for c in cases if c["case_id"] in want}
    if a.only_key:
        pairs = {k: v for k, v in pairs.items() if k == a.only_key} or \
            {a.only_key: tuple(a.only_key.split("||"))}
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = [k for k in sorted(pairs) if a.redo or k not in done or done[k].get("error")]
    # Same document together, so its cache is warm for the next operation.
    todo.sort(key=lambda k: (pairs[k][0], pairs[k][1]))
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(pairs)} pairs, {len(todo)} to extract, {len({pairs[k][0] for k in todo})} documents")
    if a.dry or not todo:
        return 0

    _load_env()
    import anthropic
    import os
    import spend
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=600.0)
    lock = threading.Lock()

    # One worker per DOCUMENT, operations in series within it, so the cached
    # document is reused instead of written four times at once.
    by_doc = {}
    for k in todo:
        by_doc.setdefault(pairs[k][0], []).append(k)

    def run_doc(keys):
        lines = []
        for k in keys:
            url, cpt = pairs[k]
            try:
                r = extract(client, url, cpt)
            except Exception as e:  # noqa: BLE001
                r = {"url": url, "cpt": cpt, "covered": None, "criteria": [],
                     "error": f"{type(e).__name__}: {e}"[:400]}
            if r.get("usage"):
                r["usd"] = spend.cost(MODEL, r["usage"])
                spend.record("section_criteria", MODEL, r["usage"], k[:200])
            with lock:
                done[k] = r
                OUT.write_text(json.dumps(done, indent=1, ensure_ascii=False))
            flag = ("ERROR " + r["error"][:80]) if r.get("error") else \
                   ("NOT COVERED: " + (r.get("why_not") or "")[:80]) if r.get("covered") is False else \
                   f"{len(r['criteria'])} kept, {len(r['dropped_not_in_document'])} not verbatim, " \
                   f"{len(r['dropped_other_operation'])} other-op"
            lines.append(f"  {cpt} {url.split('/')[2][:30]:30s} {flag}")
        return "\n".join(lines)

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        for f in as_completed([pool.submit(run_doc, ks) for ks in by_doc.values()]):
            print(f.result(), flush=True)
    print(f"ledger total ${spend.total():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
