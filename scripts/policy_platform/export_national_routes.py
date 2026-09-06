#!/usr/bin/env python3
"""Pull the hand-written national appeal routes out of data.js into JSON.

The app's submitFor() has always had two tiers: ~40 researched regional plans
in assets/submit.js, then a hand-written set in data.js covering the nationals
-- UnitedHealthcare, Aetna, Cigna, Anthem, Humana, Centene's brands, Molina --
which is most of the country by membership. Only the first tier existed as
data; the second lived in a JavaScript object literal, reachable by the browser
and by nothing else. So the server-side letter generator, which is where the
appeal is actually written, could not see the routes for the biggest payers in
the directory.

This lifts them into data/policy_platform/national_submission_routes.json so
Python and the browser answer from the same source. The JS stays the source of
truth for now; re-run this after editing it.

  python3 scripts/policy_platform/export_national_routes.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "mockups" / "assets" / "data.js"
OUT = ROOT / "data" / "policy_platform" / "national_submission_routes.json"

# submitFor()'s own matching, kept in step with mockups/map/index.html.
MATCH = {
    "unitedhealthcare": ["unitedhealth", "uhc", "oxford"],
    "aetna": ["aetna"],
    "cigna": ["cigna"],
    "anthem": ["anthem", "elevance", "wellpoint"],
    "humana": ["humana"],
    "centene": ["ambetter", "centene", "wellcare", "buckeye", "sunflower",
                "superior", "magnolia", "peach state", "sunshine health",
                "louisiana healthcare connections", "western sky", "'ohana",
                "trillium", "iowa total care", "nebraska total care",
                "oklahoma complete", "arizona complete", "home state health",
                "managed health services", "carolina complete",
                "absolute total care", "meridian", "fidelis"],
    "molina": ["molina", "passport health plan"],
    "floridablue": ["florida blue", "guidewell"],
    "medicaid": ["medicaid"],
    "medicare": ["medicare"],
    # HCSC's entry names its five state portals. Serving it to a Premera or
    # BCBS-Michigan member would be a wrong answer dressed as a specific one,
    # so only the five HCSC plans match -- the rule submitFor() already
    # enforces, and the bug this repo fixed once before.
    "hcsc": ["__hcsc_states__"],
}
HCSC_STATES = ("illinois", "texas", "oklahoma", "new mexico", "montana")
HCSC_BLUE = ("blue cross", "bcbs")


def _obj(src: str, start: int) -> tuple[str, int]:
    depth, i = 0, start
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1], i + 1
        i += 1
    raise ValueError("unbalanced object")


def _fields(block: str) -> dict:
    out = {}
    for key in ("portal", "phone", "fax", "mail", "how", "window"):
        m = re.search(rf'\b{key}\s*:\s*(null|"((?:[^"\\]|\\.)*)")', block)
        if not m:
            continue
        # json.loads, not unicode_escape: the JS is UTF-8, and
        # "x".encode().decode("unicode_escape") turns every em-dash into mojibake.
        out[key] = None if m.group(1) == "null" else json.loads(m.group(1))
    return out


def main() -> int:
    src = JS.read_text()
    i = src.index("insurerSubmit")
    block, _ = _obj(src, src.index("{", i))
    routes, pos = {}, 0
    for m in re.finditer(r"\n\s{4}(\w+):\s*\{", block):
        name = m.group(1)
        body, pos = _obj(block, block.index("{", m.start(1)))
        routes[name] = {"key": name, "match": MATCH.get(name, [name]), **_fields(body)}
    if "hcsc" in routes:
        routes["hcsc"]["match"] = []
        routes["hcsc"]["match_all_of"] = [list(HCSC_STATES), list(HCSC_BLUE)]
    OUT.write_text(json.dumps({
        "exported_from": "mockups/assets/data.js insurerSubmit",
        "note": "The denial letter is always authoritative. Never guess an address.",
        "routes": list(routes.values())}, indent=1))
    print(f"exported {len(routes)} national routes -> {OUT}")
    for r in routes.values():
        print(f"  {r['key']:18s} portal={bool(r.get('portal'))} mail={bool(r.get('mail'))} "
              f"phone={bool(r.get('phone'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
