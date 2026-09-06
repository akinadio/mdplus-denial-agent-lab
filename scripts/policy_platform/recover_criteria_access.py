#!/usr/bin/env python3
"""Rebuild criteria_access_directory.json from its surviving build product.

How a patient reaches the ACTUAL criteria behind a denial, per insurer and per
vendor -- the InterQual transparency viewers, the "ask in writing" scripts,
the portals -- was researched page by page, generated into assets/access.js,
and then lost with the rest of data/policy_platform's uncommitted files. The
generated file is a plain JSON object under a window assignment, so the source
comes back intact.

Consumers: the page (accessFor), and the study's abstention route, which
without this file had been telling every no-policy patient the same generic
sentence.

  python3 scripts/policy_platform/recover_criteria_access.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "mockups" / "assets" / "access.js"
OUT = ROOT / "data" / "policy_platform" / "criteria_access_directory.json"


def main() -> int:
    js = JS.read_text()
    d = json.loads(js[js.index("{"):js.rindex("}") + 1])
    d["_recovered"] = "2026-09-05 from mockups/assets/access.js, the surviving build product"
    OUT.write_text(json.dumps(d, indent=1, ensure_ascii=False))
    vend = sorted(k for k in d if k.startswith("_") and k != "_recovered")
    print(f"recovered {len(d) - 1} entries -> {OUT}")
    print(f"  {len(d) - 1 - len(vend)} insurers, {len(vend)} vendor fallbacks: {vend}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
