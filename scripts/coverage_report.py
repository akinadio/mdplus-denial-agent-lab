#!/usr/bin/env python3
"""Generate the OrthoAppeals coverage tracker — the honest, running answer to
"which payer x procedure policies do we actually have grounded in truth?"

Two layers, both shown:
  Layer 1 — governing policy DOCUMENT: do we have the carrier's own official
            policy for this procedure, with the CPT verified in the document?
  Layer 2 — extracted CRITERIA: have we mined that policy into the exact
            requirements (imaging/MRI, failed conservative care, timelines)?

Reads data/policy_platform/procedure_policy_directory.json (+ the criteria
extractions) and writes a self-contained HTML dashboard. Re-run any time the
directory changes to refresh the picture — this is meant to be a living list.

    python3 scripts/coverage_report.py            # -> dist/coverage.html
"""
from __future__ import annotations

import json
import datetime
import html
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "policy_platform"
OUT = ROOT / "dist" / "coverage.html"


def cell_status(row: dict) -> str:
    if row.get("cpt_verified") and row.get("url"):
        return "verified"          # we have the doc AND confirmed the CPT is in it
    if row.get("url"):
        return "unverified"        # we have a doc but haven't confirmed the CPT
    return "missing"               # no policy document at all


def load():
    directory = json.loads((DATA / "procedure_policy_directory.json").read_text())
    try:
        crit = json.loads((DATA / "criteria_extractions.json").read_text())
    except Exception:
        crit = []
    return directory, crit


def criteria_index(crit) -> set:
    """(carrier, cpt) pairs for which we have extracted structured criteria."""
    idx = set()
    items = crit if isinstance(crit, list) else crit.get("extractions", [])
    for e in items or []:
        if isinstance(e, dict):
            idx.add((str(e.get("carrier", "")).strip(), str(e.get("cpt", "")).strip()))
    return idx


def build():
    directory, crit = load()
    procs = directory["meta"]["procedures"]
    proc_labels = [p["label"] for p in procs]
    proc_cpt = {p["label"]: p.get("cpt", "") for p in procs}
    policies = directory["policies"]
    carriers = list(policies.keys())
    crit_idx = criteria_index(crit)

    # index rows by (carrier, procedure)
    grid: dict[tuple, dict] = {}
    for c, rows in policies.items():
        for r in rows:
            grid[(c, r["procedure"])] = r

    total = len(carriers) * len(proc_labels)
    counts = {"verified": 0, "unverified": 0, "missing": 0}
    crit_have = 0
    for c in carriers:
        for p in proc_labels:
            r = grid.get((c, p))
            counts[cell_status(r) if r else "missing"] += 1
            if r and (c, str(proc_cpt.get(p, ""))) in crit_idx:
                crit_have += 1

    gen = datetime.date.today().isoformat()

    def pct(n):
        return f"{round(100 * n / total)}%" if total else "0%"

    # ---- build the matrix rows -------------------------------------------
    def th(label, cpt):
        return f'<th class="proc"><span>{html.escape(label)}</span><em>{html.escape(cpt)}</em></th>'

    head = "".join(th(p, proc_cpt.get(p, "")) for p in proc_labels)

    ICON = {"verified": "✓", "unverified": "~", "missing": "✗"}
    body_rows = []
    for c in carriers:
        cells = []
        for p in proc_labels:
            r = grid.get((c, p))
            s = cell_status(r) if r else "missing"
            title = ""
            if r:
                bits = [r.get("policy_title", ""), r.get("effective_date", ""), r.get("notes", "")]
                title = " — ".join(b for b in bits if b)
            has_crit = r is not None and (c, str(proc_cpt.get(p, ""))) in crit_idx
            crit_mark = '<b class="cx">criteria</b>' if has_crit else ''
            cells.append(
                f'<td class="c {s}" title="{html.escape(title)}">'
                f'<span class="ic">{ICON[s]}</span>{crit_mark}</td>'
            )
        body_rows.append(
            f'<tr><th class="carrier">{html.escape(c)}</th>{"".join(cells)}</tr>'
        )

    # ---- gaps list (missing + unverified), worst carriers first -----------
    gap_lines = []
    for c in carriers:
        holes = []
        for p in proc_labels:
            r = grid.get((c, p))
            s = cell_status(r) if r else "missing"
            if s != "verified":
                holes.append((p, s))
        if holes:
            items = "".join(
                f'<li class="{s}">{html.escape(p)} <em>{"no policy" if s=="missing" else "CPT unconfirmed"}</em></li>'
                for p, s in holes
            )
            gap_lines.append(
                f'<div class="gapcard"><h4>{html.escape(c)} '
                f'<span class="n">{len(holes)} gap{"s" if len(holes)!=1 else ""}</span></h4>'
                f'<ul>{items}</ul></div>'
            )

    html_doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OrthoAppeals — Policy Coverage Tracker</title>
<style>
  :root {{
    --ink:#12232e; --soft:#5c6f7a; --line:#dde5ea; --bg:#f6f8fa; --card:#fff;
    --ok:#1a7a4c; --okbg:#e3f4ea; --warn:#8a5a00; --warnbg:#fdf1d6; --bad:#a4262c; --badbg:#fbe4e4;
    --crit:#5b3fa8;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:var(--ink); background:var(--bg); }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:28px 22px 60px; }}
  h1 {{ font-size:24px; margin:0 0 4px; }}
  .sub {{ color:var(--soft); margin:0 0 22px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:0 0 26px; }}
  .kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px; }}
  .kpi .num {{ font-size:28px; font-weight:800; }}
  .kpi .lbl {{ color:var(--soft); font-size:13px; margin-top:2px; }}
  .kpi.good .num {{ color:var(--ok); }} .kpi.bad .num {{ color:var(--bad); }}
  .banner {{ background:#f3eefc; border:1px solid #ddd0f5; border-left:5px solid var(--crit); border-radius:12px; padding:16px 18px; margin:0 0 26px; }}
  .banner h3 {{ margin:0 0 4px; font-size:16px; color:var(--crit); }}
  .banner p {{ margin:0; color:#3f3560; }}
  h2 {{ font-size:17px; margin:26px 0 10px; }}
  .legend {{ display:flex; gap:16px; flex-wrap:wrap; font-size:13px; color:var(--soft); margin:0 0 12px; }}
  .legend span b {{ display:inline-block; width:16px; text-align:center; border-radius:4px; margin-right:5px; font-weight:700; }}
  .tblwrap {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:12px; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th.carrier {{ text-align:left; padding:10px 12px; position:sticky; left:0; background:var(--card); white-space:nowrap; border-right:1px solid var(--line); }}
  th.proc {{ padding:8px 6px; vertical-align:bottom; border-bottom:1px solid var(--line); min-width:64px; }}
  th.proc span {{ display:block; font-size:11px; font-weight:600; line-height:1.25; }}
  th.proc em {{ display:block; color:var(--soft); font-style:normal; font-size:10px; margin-top:2px; }}
  td.c {{ text-align:center; padding:8px 4px; border-bottom:1px solid var(--line); border-right:1px solid #eef2f5; position:relative; }}
  td.c .ic {{ font-weight:800; }}
  td.verified {{ background:var(--okbg); }} td.verified .ic {{ color:var(--ok); }}
  td.unverified {{ background:var(--warnbg); }} td.unverified .ic {{ color:var(--warn); }}
  td.missing {{ background:var(--badbg); }} td.missing .ic {{ color:var(--bad); }}
  td .cx {{ display:block; font-size:8px; color:var(--crit); font-weight:700; text-transform:uppercase; letter-spacing:.03em; }}
  tr:hover td.c {{ outline:1px solid rgba(0,0,0,.06); }}
  .gaps {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:14px; }}
  .gapcard {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
  .gapcard h4 {{ margin:0 0 8px; font-size:14px; display:flex; justify-content:space-between; align-items:center; }}
  .gapcard .n {{ font-size:11px; color:var(--bad); background:var(--badbg); padding:2px 8px; border-radius:20px; }}
  .gapcard ul {{ margin:0; padding:0; list-style:none; }}
  .gapcard li {{ font-size:12.5px; padding:4px 0; border-top:1px solid #f0f4f6; }}
  .gapcard li em {{ float:right; font-style:normal; font-size:11px; color:var(--soft); }}
  .gapcard li.missing em {{ color:var(--bad); }}
  .foot {{ color:var(--soft); font-size:12px; margin-top:30px; }}
</style></head><body><div class="wrap">
  <h1>OrthoAppeals — Policy Coverage Tracker</h1>
  <p class="sub">What we actually have grounded in each payer's real policy. Generated {gen} from the coverage directory. Re-run <code>scripts/coverage_report.py</code> to refresh.</p>

  <div class="kpis">
    <div class="kpi good"><div class="num">{pct(counts['verified'])}</div><div class="lbl">Policy verified ({counts['verified']} of {total})</div></div>
    <div class="kpi"><div class="num">{counts['unverified']}</div><div class="lbl">Have policy, CPT not confirmed</div></div>
    <div class="kpi bad"><div class="num">{counts['missing']}</div><div class="lbl">No policy on file</div></div>
    <div class="kpi bad"><div class="num">{crit_have} / {total}</div><div class="lbl">Exact criteria extracted</div></div>
  </div>

  <div class="banner">
    <h3>The real black box: Layer 2 — extracted criteria</h3>
    <p>Layer 1 below is "do we have the carrier's actual policy document." Layer 2 is "have we mined that policy into the exact requirements (MRI, failed conservative care, timelines)." Right now that is <b>{crit_have} of {total}</b>. The live agent reads the policy at run time, but we hold no verified, inspectable record of the criteria. Closing this is what turns grounding from a promise into something we can prove.</p>
  </div>

  <h2>Layer 1 — governing policy document (payer × procedure)</h2>
  <div class="legend">
    <span><b style="background:var(--okbg);color:var(--ok)">✓</b>verified — we have the doc and confirmed the CPT</span>
    <span><b style="background:var(--warnbg);color:var(--warn)">~</b>have policy, CPT not yet confirmed</span>
    <span><b style="background:var(--badbg);color:var(--bad)">✗</b>no policy on file</span>
    <span><b style="color:var(--crit)">criteria</b>Layer 2 extracted for this cell</span>
  </div>
  <div class="tblwrap"><table>
    <thead><tr><th class="carrier">Payer</th>{head}</tr></thead>
    <tbody>{''.join(body_rows)}</tbody>
  </table></div>

  <h2>Gaps to close, by payer</h2>
  <div class="gaps">{''.join(gap_lines)}</div>

  <p class="foot">Source: data/policy_platform/procedure_policy_directory.json · criteria_extractions.json. "Verified" means a human/checked pass confirmed the CPT appears in the named document. This tracker is generated, not hand-maintained — edit the directory data, not this file.</p>
</div></body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_doc, encoding="utf-8")

    # console summary
    print(f"Coverage tracker -> {OUT}")
    print(f"  Layer 1 verified : {counts['verified']}/{total} ({pct(counts['verified'])})")
    print(f"  have doc, unconf : {counts['unverified']}")
    print(f"  no policy on file: {counts['missing']}")
    print(f"  Layer 2 criteria : {crit_have}/{total}")
    return OUT


if __name__ == "__main__":
    build()
