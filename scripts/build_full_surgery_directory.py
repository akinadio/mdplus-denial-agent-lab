#!/usr/bin/env python3
"""Assemble the FULL payer x plan x line-of-business x state x surgery policy
directory, anchoring every row to a real governing-source URL.

Layers, all from data already in the repo / the knee benchmark footprint:
  - Commercial / ACA  -> carrier national medical policy (build_policy_directory.DATA)
  - Medicaid          -> state Medicaid manual entry point (medicaid_coverage_by_state.json)
  - Medicare Advantage-> CMS coverage entry per CPT (DATA['Medicare (CMS)']); refine
                          to per-state LCD as a follow-up (knee already per-state).

Target footprint = the payer/plan/LOB/state rows the knee benchmark defines
(consol benchmark), so we build the other 11 surgeries at the SAME depth as knee.

    python3 scripts/build_full_surgery_directory.py
        -> data/policy_platform/full_surgery_policy_directory.csv
"""
from __future__ import annotations
import importlib.util, json, csv, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATADIR = ROOT / "data" / "policy_platform"

def _load_bpd():
    spec = importlib.util.spec_from_file_location("bpd", ROOT / "scripts" / "build_policy_directory.py")
    m = importlib.util.module_from_spec(spec)
    try: spec.loader.exec_module(m)
    except SystemExit: pass
    return m

PMAP = {k: k for k in [
    "UnitedHealthcare", "Aetna (CVS Health)", "Cigna", "Elevance / Anthem BCBS",
    "Humana", "Centene (Ambetter/WellCare)", "HCSC (BCBS IL/TX/NM/OK/MT)",
    "Molina Healthcare", "Florida Blue / GuideWell"]}

def build(targets: list[tuple]):
    m = _load_bpd(); DATA = m.DATA; PROCS = m.PROCS
    med = json.loads((DATADIR / "medicaid_coverage_by_state.json").read_text())["states"]

    def anchor(payer, lob, state, cpt):
        if lob == "Medicaid":
            s = med.get(state)
            if s and s.get("coverage_policy_url"):
                return (s["coverage_policy_url"], s.get("program_name", "State Medicaid"), False,
                        "anchored", "State Medicaid manual/coverage entry point; per-surgery criteria within.")
            return ("", "", False, "needed", "State Medicaid manual URL not on file.")
        if lob == "Medicare Advantage":
            cms = DATA.get("Medicare (CMS)", {}).get(cpt)
            if cms and cms[1]:
                return (cms[1], cms[0], cms[3], "anchored",
                        "MA follows CMS NCD/LCD; national CMS entry — refine to per-state LCD + check version freshness.")
            return ("", "", False, "needed", "CMS coverage URL not on file for this CPT.")
        key = PMAP.get(payer)
        if key:
            v = DATA.get(key, {}).get(cpt)
            if v and v[1]:
                note = "National carrier medical policy." + ("" if lob == "Commercial" else " (ACA plans typically use the same policy.)")
                return (v[1], v[0], v[3], "anchored", note)
        return ("", "", False, "needed", "No carrier policy on file — regional/other payer to research.")

    rows = []
    for (payer, plan, lob, state) in targets:
        for label, cpt in PROCS:
            url, title, ver, status, note = anchor(payer, lob, state, cpt)
            rows.append(dict(payer=payer, plan=plan, line_of_business=lob, state=state,
                             surgery=label, cpt=cpt, policy_url=url, policy_title=title,
                             cpt_verified=ver, status=status, source_note=note))
    return rows

def targets_from_benchmark(path):
    b4 = json.loads(pathlib.Path(path).read_text())["benchmark"] if str(path).endswith(".json") else path
    out = []
    for x in b4:
        payer = (x.get("company") or "").strip()
        if not payer or payer.startswith("Sum") or payer == "SUMMARY" or "CAVEAT" in payer or "Kaiser" in payer:
            continue
        lob = (x.get("line_of_business") or "").strip(); plan = (x.get("plan") or "").strip()
        states = [s.strip() for s in (x.get("states_covered") or "").split(",") if s.strip()]
        locs = states if (lob in ("Medicare Advantage", "Medicaid") and states) else ["National"]
        for st in locs:
            out.append((payer, plan, lob, st))
    return out

if __name__ == "__main__":
    T = targets_from_benchmark("/tmp/consol.json")
    rows = build(T)
    cols = ["payer","plan","line_of_business","state","surgery","cpt","policy_url","policy_title","cpt_verified","status","source_note"]
    out = DATADIR / "full_surgery_policy_directory.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)
    anc = sum(1 for r in rows if r["status"] == "anchored")
    print(f"{out}: {len(rows)} rows, {anc} anchored ({round(100*anc/len(rows))}%), {len(rows)-anc} needed")
