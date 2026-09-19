#!/usr/bin/env python3
"""Re-fetch cached policy documents that are empty or were cut short.

Two ways a cached document lies, both silent until 2026-09-19:

  EMPTY   a fetch failed once and the empty result was cached. find_criteria
          then returns nothing, the letter argues from no criteria, and the
          arm is scored as if the policy said nothing.
  CUT     an older build capped extraction at 120,000 characters. The 2026
          Evolent Musculoskeletal guideline sits at exactly that length with
          its KNEE ARTHROPLASTY section past the cut -- so criteria come from
          whatever section survived, and quote_check calls a real quotation
          fabricated because the page it came from is not in our copy.

This must run somewhere that can actually reach payer hosts. The Cowork
workspace cannot resolve them; a normal terminal on the study machine can.
policy_text() now refuses to overwrite a good document with a failed fetch, so
running this when the network is down costs nothing but time.

  python3 scripts/policy_platform/refetch_policies.py            # report
  python3 scripts/policy_platform/refetch_policies.py --apply
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from synthetic_harness.policy_text import _key, policy_text  # noqa: E402

CUT_AT = 120000   # the old cap, recognisable by being exact


def suspect(url: str):
    p = _key(url)
    if not p.exists():
        return "missing"
    try:
        d = json.loads(p.read_text())
    except ValueError:
        return "unreadable"
    t = d.get("text") or ""
    if not t.strip():
        return "empty"
    if d.get("truncated") or len(t) == CUT_AT:
        return "cut"
    return None


def main() -> int:
    apply = "--apply" in sys.argv
    gold = json.loads((ROOT / "study" / "gold.json").read_text())["entries"]
    urls = sorted({(g.get("policy_url") or "").strip()
                   for g in gold if (g.get("policy_url") or "").strip()})
    todo = [(u, s) for u in urls if (s := suspect(u))]
    if not todo:
        print("every cached policy document is present and complete")
        return 0
    print(f"{len(todo)} of {len(urls)} cached documents need re-fetching:\n")
    fixed = still = 0
    for u, why in todo:
        before = len(json.loads(_key(u).read_text()).get("text") or "") if _key(u).exists() else 0
        if not apply:
            print(f"  {why:10s} {before:>7,} chars  {u[:90]}")
            continue
        d = policy_text(u, refresh=True)
        after = len(d.get("text") or "")
        ok = after > before or (after and why == "empty")
        fixed += bool(ok)
        still += (not ok)
        print(f"  {why:10s} {before:>7,} -> {after:>7,}  {'FIXED' if ok else 'still bad'}  "
              f"{str(d.get('error') or d.get('last_refresh_error') or '')[:40]}  {u[:60]}")
    if apply:
        print(f"\n{fixed} recovered, {still} still bad.")
        if still:
            print("A document that will not come back may have moved. Check the URL "
                  "in data/policy_platform/app_option_policy_directory.csv -- if it "
                  "has moved, OrthoAppeals is handing patients a dead link too.")
        print("Then: python3 scripts/study/verify_gold.py --workers 4")
    else:
        print("\nRe-run with --apply. Nothing is overwritten by a failed fetch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
