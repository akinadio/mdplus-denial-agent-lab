#!/usr/bin/env python3
"""Find the rows that are hiding a real policy behind an abstaining status.

The 2026-09-04 fix promoted 896 rows whose URL was a .pdf. It left 1,040 rows
whose URL points at an index, a portal or a plain HTML page still on the
abstain path, on the assumption that those are not documents. Some of them are:
plenty of payers publish criteria as an HTML page, and the pilot showed what it
costs when the app withholds a document it is holding -- ChatGPT handed the
patient the right policy while OrthoAppeals said no criteria exist.

So read them. A page is promoted only if the fetched text names the CPT AND
reads like coverage criteria; anything else stays where it is, and the reason
is recorded rather than guessed at.

Needs real network access, so run it on a machine that has it.

  python3 scripts/policy_platform/audit_hidden_documents.py --limit 40
  python3 scripts/policy_platform/audit_hidden_documents.py --apply
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from synthetic_harness.policy_text import policy_text, find_criteria  # noqa: E402

DIRECTORY = ROOT / "data" / "policy_platform" / "app_option_policy_directory.csv"
REPORT = ROOT / "data" / "policy_platform" / "hidden_document_audit.json"
CANDIDATE = {"NO PUBLIC CRITERIA (vendor)", "CODE ONLY", "PROCESS DOC ONLY (no procedure criteria)"}
PROMOTED = "DOCUMENT PUBLIC, CRITERIA VENDOR-HELD"


def audience(url: str) -> str | None:
    u = url.lower()
    if "medadv" in u or "medicare-advantage" in u:
        return "Medicare / Medicare Advantage"
    if "medicaid" in u:
        return "Medicaid"
    if "comm-medical-drug" in u or "/commercial" in u or "comm-plan" in u:
        return "Commercial/ACA"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true", help="write the promotions back")
    ap.add_argument("--sleep", type=float, default=0.7)
    a = ap.parse_args()

    rows = list(csv.DictReader(DIRECTORY.open(encoding="utf-8", newline="")))
    fields = list(rows[0])
    byurl: dict[str, list] = collections.defaultdict(list)
    for r in rows:
        u = (r["policy_url"] or "").strip()
        if not u or r["status"] not in CANDIDATE or u.lower().endswith(".pdf"):
            continue
        if audience(u) and audience(u) != r["plan_type"]:
            continue
        byurl[u].append(r)

    urls = sorted(byurl)
    if a.limit:
        urls = urls[:a.limit]
    print(f"{sum(len(v) for v in byurl.values())} rows behind {len(byurl)} distinct "
          f"non-PDF URLs{f' (reading {len(urls)})' if a.limit else ''}\n")

    verdicts, tally = {}, collections.Counter()
    for i, u in enumerate(urls, 1):
        group = byurl[u]
        cpts = {r["cpt"] for r in group}
        doc = policy_text(u)
        text = doc.get("text") or ""
        named = sorted(c for c in cpts if c in text)
        quotes = find_criteria(text, named[0] if named else "")
        if not text:
            v, why = "keep", f"unreadable: {(doc.get('error') or 'no text')[:50]}"
        elif not named:
            v, why = "keep", "page never names the CPT -- it is an index, not the policy"
        elif not quotes:
            v, why = "keep", "names the CPT but states no criteria"
        else:
            v, why = "promote", f"names {named} and states criteria ({len(quotes)} sentences)"
        tally[why.split(":")[0]] += 1
        verdicts[u] = {"verdict": v, "why": why, "rows": len(group),
                       "cpts_named": named, "quotes": quotes[:3],
                       "title": group[0]["policy_title"][:70]}
        print(f"  [{i:4d}/{len(urls)}] {v:8s} {why[:56]:56s} {group[0]['policy_title'][:34]}")
        REPORT.write_text(json.dumps(verdicts, indent=1))
        if a.sleep:
            time.sleep(a.sleep)

    print("\nverdicts:")
    for k, n in tally.most_common():
        print(f"  {n:5d}  {k}")
    promo = {u for u, v in verdicts.items() if v["verdict"] == "promote"}
    n_rows = sum(verdicts[u]["rows"] for u in promo)
    print(f"\n{len(promo)} documents / {n_rows} rows would be promoted to {PROMOTED!r}")

    if a.apply and promo:
        for r in rows:
            if (r["policy_url"] or "").strip() in promo and r["status"] in CANDIDATE:
                was = r["status"]
                r["status"] = PROMOTED
                r["note"] = (f"2026-09-05 hidden-document audit: read the page, it names "
                             f"this code and states criteria. Promoted from {was}. "
                             + r["note"])[:1200]
        with DIRECTORY.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"applied to {DIRECTORY}")
    elif promo:
        print("(dry run -- re-run with --apply to write them back)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
