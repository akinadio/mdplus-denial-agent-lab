#!/usr/bin/env python3
"""Build a single self-contained OrthoAppeals demo HTML.

Inlines base.css, data.js and demo.js into mockups/map/index.html and forces
DEMO mode on, so the file runs the full patient flow offline with zero backend.
Output: dist/orthoappeal-demo.html
"""
from __future__ import annotations

import base64
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAP = ROOT / "mockups" / "map"
ASSETS = ROOT / "mockups" / "assets"
OUT = ROOT / "dist" / "orthoappeal-demo.html"


def main() -> None:
    html = (MAP / "index.html").read_text(encoding="utf-8")
    base_css = (ASSETS / "base.css").read_text(encoding="utf-8")
    data_js = (ASSETS / "data.js").read_text(encoding="utf-8")
    demo_js = (MAP / "demo.js").read_text(encoding="utf-8")

    # 1) inline the stylesheet
    html = html.replace(
        '<link rel="stylesheet" href="../assets/base.css" />',
        "<style>\n" + base_css + "\n</style>",
    )

    # 2) inline every reference to the logo (favicon + brand <img>) as a data URL
    icon = MAP / "icons" / "icon-192.png"
    if icon.exists():
        b64 = base64.b64encode(icon.read_bytes()).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        html = html.replace('href="icons/icon-192.png"', f'href="{data_url}"')
        html = html.replace('src="icons/icon-192.png"', f'src="{data_url}"')

    # 3) inline data.js
    html = html.replace(
        '<script src="../assets/data.js"></script>',
        "<script>\n" + data_js + "\n</script>",
    )

    # 3b) inline coverage.js (generated per-option coverage map)
    coverage_js = (ASSETS / "coverage.js").read_text(encoding="utf-8")
    html = html.replace(
        '<script src="../assets/coverage.js"></script>',
        "<script>\n" + coverage_js + "\n</script>",
    )

    # 4) force DEMO on (replace the query-param sniff with a hard true)
    html = html.replace(
        "window.__ORTHO_DEMO__ = window.__ORTHO_DEMO__ ||\n"
        "      /[?&]demo=1\\b/.test(location.search);",
        "window.__ORTHO_DEMO__ = true; /* self-contained demo build */",
    )

    # 5) inline demo.js
    html = html.replace(
        '<script src="demo.js"></script>',
        "<script>\n" + demo_js + "\n</script>",
    )

    # Point the legal links at the sibling file we ship alongside the demo.
    html = html.replace('href="../legal.html"', 'href="legal.html"')

    # sanity: nothing should reference ../assets, demo.js, or icons/ anymore.
    # (legal.html is an intentional sibling, shipped next to the demo.)
    leftovers = re.findall(r'(?:src|href)="(?:\.\./assets|\.\./legal|demo\.js|icons/)[^"]*"', html)
    if leftovers:
        raise SystemExit(f"Un-inlined local refs remain: {leftovers}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")

    # ship the legal page next to the demo so its footer links resolve. In this
    # flat build the app is index.html at the same level, so the legal page's
    # "back" link must point there (not the source's ../map/index.html), or
    # clicking Back 404s.
    legal_src = ROOT / "mockups" / "legal.html"
    if legal_src.exists():
        legal_html = legal_src.read_text(encoding="utf-8")
        legal_html = legal_html.replace('href="map/index.html"', 'href="index.html"')
        (OUT.parent / "legal.html").write_text(legal_html, encoding="utf-8")

    kb = len(html.encode("utf-8")) / 1024
    print(f"Wrote {OUT} ({kb:.0f} KB)")
    print(f"Wrote {OUT.parent / 'legal.html'}")


if __name__ == "__main__":
    main()
