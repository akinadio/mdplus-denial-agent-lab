#!/usr/bin/env python3
"""Fail if any data file under data/policy_platform is silently ignored.

Line 19 of .gitignore ignores data/policy_platform wholesale and allows files
back one at a time. On 2026-08-30 that quietly ate the imaging directory, the
criteria-access directory, three sweeps of research and the 40 researched
appeal routes -- `git add -A` skipped them without a word and they were gone
when the container was recycled. Today it nearly took two more.

  python3 scripts/study/check_gitignore.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WATCH = ROOT / "data" / "policy_platform"
# Derived artefacts, rebuildable from what is committed.
OK_TO_IGNORE = ("policy_text_cache", ".pre-vendor-held-fix", "__pycache__")


def main() -> int:
    files = [p for p in WATCH.rglob("*")
             if p.is_file() and not any(k in str(p) for k in OK_TO_IGNORE)]
    if not files:
        print("nothing to check")
        return 0
    r = subprocess.run(["git", "check-ignore", "--stdin"], cwd=ROOT, text=True,
                       input="\n".join(str(p.relative_to(ROOT)) for p in files),
                       capture_output=True)
    ignored = [l for l in r.stdout.splitlines() if l.strip()]
    print(f"{len(files)} data files, {len(ignored)} ignored")
    if ignored:
        print("\nThese would be dropped by `git add -A` and lost on the next reset:")
        for f in ignored:
            print(f"  {f}")
        print("\nAdd an allow line for each in .gitignore, e.g.  !" + ignored[0])
        return 1
    print("every data file is trackable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
