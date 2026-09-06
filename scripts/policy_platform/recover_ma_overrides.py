#!/usr/bin/env python3
"""Rebuild ma_plan_overrides.json from the last coverage.js that carried it.

The Medicare Advantage layer -- the answer a UHC MA member gets instead of the
commercial InterQual answer, with the 42 CFR 422.101(b) argument attached --
was another file the data/policy_platform gitignore swallowed. Its build
product survived in coverage.js at commit d0c2861 (12 entries), and
build_coverage_js.py is lossless for everything but the title, which it
truncates to 60 characters. Full titles are restored from the directory backup
where the same document appears.

This is also where UHC's MMP052.13 / MMP089.18 belong. The 2026-08-26 sweep
had put them on 368 COMMERCIAL rows, which fix_vendor_held_docs.py repointed;
the MA member is answered from this layer, by plan kind, as intended.

  python3 scripts/policy_platform/recover_ma_overrides.py
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "policy_platform" / "ma_plan_overrides.json"
BACKUP = ROOT / "data" / "policy_platform" / "app_option_policy_directory.csv.pre-vendor-held-fix"
COMMIT = "d0c2861"


def main() -> int:
    js = subprocess.run(["git", "show", f"{COMMIT}:mockups/assets/coverage.js"],
                        cwd=ROOT, capture_output=True, text=True, check=True).stdout
    d = json.loads(js[js.index("{"):js.rindex("}") + 1])
    urls, ma = d["urls"], d["ma"]

    titles: dict[str, str] = {}
    if BACKUP.exists():
        for r in csv.DictReader(BACKUP.open(encoding="utf-8", newline="")):
            if r["policy_url"] and len(r["policy_title"]) > 60:
                titles.setdefault(r["policy_url"], r["policy_title"])

    grouped: dict[tuple, dict] = {}
    for key, (code, uix, title, why) in ma.items():
        insurer, cpt = key.split("|", 1)
        url = urls[uix] if uix >= 0 else ""
        full = titles.get(url, title)
        g = grouped.setdefault((insurer, code, url, why), {
            "insurer": insurer, "cpts": [], "code": code, "policy_url": url,
            "policy_title": full, "why": why})
        g["cpts"].append(cpt)
        # The original carried a verbatim `evidence` quote the build did not
        # keep. The `why` text quotes the document in places; where it does,
        # that quote is the evidence. Where it does not, say so rather than
        # invent one.
        # A quote opens after a space or colon and closes before punctuation --
        # not at the apostrophe in "UHC's".
        m = re.search(r"(?:^|[\s:])'([A-Z][^']{25,}?)'(?=[\s.,;-]|$)", why)
        g["evidence"] = (m.group(1) if m else
                         f"verbatim quote lost with the original file; the document at "
                         f"{url} is the evidence, re-read it before relying on this row")
    overrides = sorted(grouped.values(), key=lambda o: (o["insurer"], o["policy_title"]))
    for o in overrides:
        o["cpts"].sort()
        # The sweep had glued a research note onto the title.
        o["policy_title"] = re.split(r"\s+-\s+commercial criteria", o["policy_title"])[0].strip()
    OUT.write_text(json.dumps({
        "recovered": f"2026-09-05 from mockups/assets/coverage.js at {COMMIT}",
        "rule": ("Since 2024 (CMS-4201-F), 42 CFR 422.101(b) requires a Medicare "
                 "Advantage plan to follow Medicare's own coverage criteria, and any "
                 "internal criteria it applies where Medicare has none must be publicly "
                 "accessible. These overrides answer an MA member from the plan's own "
                 "published MA policy, by plan kind."),
        "overrides": overrides}, indent=1))
    print(f"recovered {len(overrides)} overrides covering {len(ma)} insurer|cpt cells -> {OUT}")
    for o in overrides:
        print(f"  {o['insurer']:18s} {o['code']}  {len(o['cpts'])} cpts  {o['policy_title'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
