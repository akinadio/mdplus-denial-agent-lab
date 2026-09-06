#!/usr/bin/env python3
"""Rebuild appeal_submission_routes.json out of the generated submit.js.

The routes file was one of the casualties of the .gitignore that ignored
data/policy_platform wholesale: 40 insurers' appeal addresses, researched from
each payer's own site, never committed and lost when the container was
recycled. Its build product, mockups/assets/submit.js, was committed and
survived -- and the build is nearly lossless, so the source can be recovered
from it.

Only two things do not survive: `match` (several tokens collapse onto one
entry, so they are regrouped by identity here) and the distinction between a
field the researcher left blank and the generic the build filled in. Blanks are
restored where the value is exactly the known generic, so a rebuild of
submit.js from this file reproduces it.

  python3 scripts/policy_platform/recover_submit_routes.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "mockups" / "assets" / "submit.js"
OUT = ROOT / "data" / "policy_platform" / "appeal_submission_routes.json"

GENERIC_PHONE = "The number on the back of your insurance card"
GENERIC_MAIL = "The appeal address printed on your denial letter"
GENERIC_WINDOW = "Check your denial letter — it states your exact deadline"


def main() -> int:
    js = JS.read_text()
    body = js[js.index("{"): js.rindex("}") + 1]
    ext = json.loads(body)

    grouped: dict[str, dict] = {}
    for token, e in ext.items():
        key = json.dumps(e, sort_keys=True)
        grouped.setdefault(key, {"entry": e, "match": []})["match"].append(token)

    routes = []
    for g in grouped.values():
        e = g["entry"]
        routes.append({
            "insurer": e.get("insurer", ""),
            "match": sorted(g["match"]),
            "portal": e.get("portal") or "",
            "phone": "" if e.get("phone") == GENERIC_PHONE else (e.get("phone") or ""),
            "fax": e.get("fax") or "",
            "mail": "" if e.get("mail") == GENERIC_MAIL else (e.get("mail") or ""),
            "how": e.get("how", ""),
            "window": "" if e.get("window") == GENERIC_WINDOW else (e.get("window") or ""),
            "source_url": e.get("source", ""),
            "confidence": e.get("confidence", "low"),
            **({"ma_note": e["ma_note"]} if e.get("ma_note") else {}),
        })
    routes.sort(key=lambda r: r["insurer"].lower())
    OUT.write_text(json.dumps({
        "recovered": "2026-09-05 from mockups/assets/submit.js, the surviving build "
                     "product of the routes lost to the data/policy_platform gitignore",
        "routes": routes}, indent=1))
    conf = {}
    for r in routes:
        conf[r["confidence"]] = conf.get(r["confidence"], 0) + 1
    print(f"recovered {len(routes)} insurers, {len(ext)} match tokens -> {OUT}")
    print("  confidence:", conf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
