#!/usr/bin/env python3
"""Policies that are public but cannot be fetched by a script.

Cohere publishes Avera Health Plan's commercial guidelines on a public help
page, but each guideline is a PDF behind a signed, expiring link: a browser
gets it, a script gets 403. The study's answer for two Avera cases was that
index page, which contains titles and no criteria -- so nothing could be
quoted from it and no quotation could be checked against it.

Download the PDFs by hand into data/policy_platform/manual_docs/ (any file
name containing the words below), then run this. Each PDF's text is cached
under the index URL plus a #fragment naming the guideline: citing the index
page still matches (fragments are ignored when URLs are compared), and the
text behind that address is the guideline itself.

  python3 scripts/policy_platform/load_manual_docs.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from synthetic_harness.policy_text import _key, CACHE  # noqa: E402

DOCS = ROOT / "data" / "policy_platform" / "manual_docs"
AVERA = "https://help.coherehealth.com/payer-info/en/articles/13602157-avera-health-plan-commercial-guidelines"
MANIFEST = [
    # (words that must all be in the file name, fragment, title, payer, state, cpts)
    (("great", "toe"), "great-toe-surgical-treatments-v3",
     "Cohere Medical Policy - Great Toe Surgical Treatments (Version 3), Avera Health Plans",
     "Avera Health Plans", "South Dakota", {"28296"}),
    (("shoulder", "arthroscopy"), "shoulder-arthroscopy-v5",
     "Cohere Medical Policy - Shoulder Arthroscopy (Version 5), Avera Health Plans",
     "Avera Health Plans", "South Dakota", {"29827", "29806"}),
]


def pdf_text(p: Path) -> str:
    from pypdf import PdfReader
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)


def main() -> int:
    files = [p for p in DOCS.glob("*.pdf")]
    gold_path = ROOT / "study" / "gold.json"
    gold = json.loads(gold_path.read_text())
    dpath = ROOT / "data" / "policy_platform" / "app_option_policy_directory.csv"
    with dpath.open(newline="") as f:
        rd = csv.DictReader(f)
        fields, rows = rd.fieldnames, list(rd)
    missing = 0
    for words, frag, title, payer, state, cpts in MANIFEST:
        hit = [p for p in files if all(w in p.name.lower() for w in words)]
        if not hit:
            print(f"  MISSING: no PDF with {' + '.join(words)} in its name in {DOCS.relative_to(ROOT)}")
            missing += 1
            continue
        text = pdf_text(hit[0])
        if len(text) < 2000:
            print(f"  {hit[0].name}: only {len(text)} characters extracted -- is it the guideline?")
            missing += 1
            continue
        url = f"{AVERA}#{frag}"
        CACHE.mkdir(parents=True, exist_ok=True)
        _key(url).write_text(json.dumps({"url": url, "final_url": url, "status": 200,
                                         "content_type": "application/pdf", "text": text,
                                         "truncated": False, "error": "",
                                         "source_file": hit[0].name}))
        for g in gold["entries"]:
            if g["payer"] == payer and g["state"] == state and g["cpt"] in cpts \
                    and g.get("policy_url") != url:
                g.setdefault("policy_url_before_2026_09_21", g.get("policy_url"))
                g.update(policy_url=url, policy_title=title)
                print(f"  gold {g['case_id']} {payer} {g['cpt']} -> {title}")
        for r in rows:
            if r["insurance_company"] == payer and r["state"] == state and r["cpt"] in cpts \
                    and r["policy_url"] != url:
                r.update(policy_url=url, policy_title=title,
                         note="2026-09-21: criteria are in this guideline PDF, linked from the index "
                              "page; text loaded from a hand download. " + r["note"])
        print(f"  {hit[0].name}: {len(text):,} characters -> {url}")
    gold_path.write_text(json.dumps(gold, indent=1))
    with dpath.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
