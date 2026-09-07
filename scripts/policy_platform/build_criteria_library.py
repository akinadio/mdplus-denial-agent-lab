#!/usr/bin/env python3
"""Read every policy we hold a link to, and keep its criteria verbatim.

Until now the directory was a link list: 2,000+ rows carrying a title and a URL
and not one word of the payer's language. criteria_extractions.json was an
empty file. So when the app drafted a letter and was told to quote the plan, it
had nothing to quote, and on 47% of in-library cases it invented something that
reads like criteria. An invented quote is worse than no quote: a reviewer
checks the quoted criterion first, finds it is not in the policy, and stops
believing the rest of the letter.

This fetches each distinct policy URL once, keeps the extracted text, and pulls
out the sentences that state a coverage rule -- verbatim, never paraphrased, so
every one can be checked against the document character for character.

Runs anywhere with real network access (payer sites are not reachable from the
Claude sandboxes, so: your Mac).

  python3 scripts/policy_platform/build_criteria_library.py            # all
  python3 scripts/policy_platform/build_criteria_library.py --limit 20 # a taste
  python3 scripts/policy_platform/build_criteria_library.py --refresh  # re-read
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
OUT = ROOT / "data" / "policy_platform" / "criteria_extractions.json"
# Every status that puts a document in front of a patient. A vendor-held policy
# is included: its scope and its "criteria live in InterQual" sentence are both
# quotable, and both belong in an appeal.
DOCUMENT_STATUSES = ("VERIFIED", "DOCUMENT PUBLIC, CRITERIA VENDOR-HELD", "CODE ONLY")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refresh", action="store_true", help="re-fetch even if cached")
    ap.add_argument("--sleep", type=float, default=0.7, help="seconds between fetches")
    a = ap.parse_args()

    # Reading a PDF needs pypdf. Without it every PDF comes back as 200 with
    # no text, which looked like "no criteria" on 32 of the first 44 documents.
    try:
        import pypdf  # noqa: F401
    except ImportError:
        print("pypdf is not installed; PDFs cannot be read.\n"
              "  python3 -m pip install -U pypdf\nthen re-run.")
        return 1

    rows = list(csv.DictReader(DIRECTORY.open(encoding="utf-8", newline="")))
    # One fetch per document, not per row: the same PDF serves dozens of cells.
    byurl: dict[str, dict] = {}
    for r in rows:
        u = (r["policy_url"] or "").strip()
        if not u or not r["status"].startswith(DOCUMENT_STATUSES):
            continue
        e = byurl.setdefault(u, {"policy_url": u, "policy_title": r["policy_title"],
                                 "cpts": set(), "payers": set()})
        e["cpts"].add(r["cpt"])
        e["payers"].add(r["insurance_company"])

    urls = sorted(byurl)
    if a.limit:
        urls = urls[:a.limit]
    print(f"{len(rows)} rows -> {len(byurl)} distinct policy documents"
          f"{f' (doing {len(urls)})' if a.limit else ''}\n")

    prior = {}
    if OUT.exists() and not a.refresh:
        try:
            raw = json.loads(OUT.read_text())
            for e in (raw.get("policies", raw) if isinstance(raw, dict) else raw):
                if isinstance(e, dict) and e.get("policy_url"):
                    prior[e["policy_url"]] = e
        except Exception:  # noqa: BLE001
            pass

    out, tally = [], collections.Counter()
    for i, u in enumerate(urls, 1):
        meta = byurl[u]
        # Extraction is cheap and the text is cached; re-extract every time so
        # a better find_criteria reaches every document without a re-fetch.
        # Only the FETCH is skipped when the cache already has the text.
        doc = policy_text(u, refresh=a.refresh)
        text = doc.get("text") or ""
        quotes = find_criteria(text, sorted(meta["cpts"])[0] if meta["cpts"] else "")
        if not text:
            tally[f"unreadable: {(doc.get('error') or 'no text')[:40]}"] += 1
        elif not quotes:
            tally["read, but no criteria sentences found"] += 1
        else:
            tally["criteria extracted"] += 1
        out.append({
            "policy_url": u,
            "policy_title": meta["policy_title"],
            "cpts": sorted(meta["cpts"]),
            "payers": sorted(meta["payers"])[:8],
            "status": doc.get("status"),
            "chars": len(text),
            "quotes": quotes,
            "error": doc.get("error") or "",
        })
        mark = f"{len(quotes)} criteria" if quotes else (doc.get("error") or "no criteria")[:44]
        print(f"  [{i:4d}/{len(urls)}] {mark:46s} {meta['policy_title'][:44]}")
        OUT.write_text(json.dumps({"built": time.strftime("%Y-%m-%d"),
                                   "policies": out}, indent=1))
        if a.sleep:
            time.sleep(a.sleep)

    print("\nresult:")
    for k, n in tally.most_common():
        print(f"  {n:5d}  {k}")
    got = sum(1 for e in out if e["quotes"])
    print(f"\n{got}/{len(out)} documents now have quotable criteria -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
