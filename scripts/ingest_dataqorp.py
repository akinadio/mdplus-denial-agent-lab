#!/usr/bin/env python3
"""Ingest a DataQorp export as research LEADS -- never as answers.

DataQorp (dataqorp.theopagent.ai, OpAgent.ai) is a proprietary policy
intelligence database: PA workflows per payer family per CPT, with source
documents and effective dates. Access is licensed; this script runs only on
an export the team has permission to use.

The precision rule does not bend for a good source. A DataQorp row tells us
WHERE a payer's policy probably lives; it does not tell us the criteria are
real, current, in scope for our CPT, or publicly reachable -- the four things
this project has been burned on by every aggregator and by payers' own index
pages. So every ingested row lands in a verification queue with status
LEAD, and only a fetch-and-read pass (the same one every research sweep
uses) can promote it into app_option_policy_directory.csv. Nothing in this
script writes to the directory.

Licensing note: their compilation is proprietary. We use it to locate
primary sources; the app cites only the payer's own public documents, which
is both our accuracy rule and the clean line legally.

Input: CSV or JSON, schema unknown until we see a real export, so column
mapping is by alias table below -- extend it when the real file arrives.

Usage:
  python3 scripts/ingest_dataqorp.py path/to/export.csv
  python3 scripts/ingest_dataqorp.py path/to/export.json --report-only
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "data" / "policy_platform" / "app_option_policy_directory.csv"
IMAGING = ROOT / "data" / "policy_platform" / "app_option_imaging_directory.csv"
OUT = ROOT / "data" / "policy_platform" / "dataqorp_leads.json"

# Our 18 tracked codes; anything else in the export is recorded but parked.
TRACKED = {"27447", "27446", "29888", "29881", "27130", "29914", "29827",
           "23472", "29806", "27702", "28296", "22612", "22551", "63030",
           "73721", "73221", "72148", "72141"}

ALIASES = {
    "payer": {"payer", "payor", "payer_name", "payor_name", "payer_family",
              "payor_family", "plan", "insurer", "carrier"},
    "cpt": {"cpt", "cpt_code", "code", "procedure_code", "hcpcs"},
    "state": {"state", "states", "region", "jurisdiction"},
    "policy_title": {"policy_title", "policy", "policy_name", "document",
                     "document_title", "source_document", "guideline"},
    "policy_url": {"policy_url", "url", "source_url", "link", "document_url",
                   "source", "href"},
    "effective_date": {"effective_date", "effective", "date", "eff_date",
                       "last_updated", "revision_date"},
    "layer": {"layer", "policy_layer", "type", "policy_type", "category"},
    "criteria": {"criteria", "clinical_criteria", "requirements",
                 "documentation_requirements", "medical_necessity"},
}


def _map_columns(fieldnames: list[str]) -> dict[str, str]:
    mapping = {}
    lowered = {f.lower().strip().replace(" ", "_"): f for f in fieldnames}
    for ours, theirs in ALIASES.items():
        for cand in theirs:
            if cand in lowered:
                mapping[ours] = lowered[cand]
                break
    return mapping


def _rows(path: Path) -> tuple[list[dict], dict[str, str]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in ("rows", "data", "workflows", "records", "results"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list) or not data:
            raise SystemExit("JSON export: no list of records found")
        return data, _map_columns(list(data[0].keys()))
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader), _map_columns(reader.fieldnames or [])


def _gap_cells() -> set[tuple[str, str]]:
    """(payer_lower, cpt) pairs where the directory holds no verified doc."""
    gaps = set()
    for p in (DIRECTORY, IMAGING):
        if not p.exists():
            continue
        with p.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if not r["status"].startswith(("VERIFIED", "NO PRIOR AUTH")):
                    gaps.add((r["insurance_company"].lower(), r["cpt"]))
    return gaps


_GENERIC = {"bcbs", "blue", "cross", "shield", "blueshield", "health",
            "plan", "plans", "of", "the", "and", "inc", "care"}


def _brand_match(payer: str, cpt: str, gaps: set[tuple[str, str]]) -> bool:
    tokens = [t for t in payer.lower().replace("/", " ").split()
              if len(t) > 3 and t not in _GENERIC]
    if not tokens:
        return False
    return any(gc == cpt and any(t in gp for t in tokens) for gp, gc in gaps)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("export", type=Path)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    rows, mapping = _rows(args.export)
    missing = {"payer", "cpt"} - set(mapping)
    if missing:
        raise SystemExit(
            f"could not find columns for {sorted(missing)} in the export "
            f"(saw: {sorted(mapping.values()) or 'nothing recognizable'}). "
            "Add the export's actual column names to ALIASES.")

    gaps = _gap_cells()
    leads, parked, fills_gap = [], 0, 0
    for r in rows:
        get = lambda k: (r.get(mapping[k]) or "").strip() if k in mapping else ""
        cpt = "".join(ch for ch in get("cpt") if ch.isdigit())
        if cpt not in TRACKED:
            parked += 1
            continue
        payer = get("payer")
        lead = {
            "source": "dataqorp",
            "status": "LEAD — unverified, do not cite",
            "payer": payer, "cpt": cpt, "state": get("state"),
            "policy_title": get("policy_title"),
            "policy_url": get("policy_url"),
            "effective_date": get("effective_date"),
            "layer": get("layer"),
            "their_criteria_summary": get("criteria"),
            # Brand-token match, not whole-string: their "Regence BCBS" must
            # find our "Regence BlueShield of Idaho". Generic tokens are
            # excluded so "Blue Cross" alone cannot match every Blues plan.
            "fills_current_gap": _brand_match(payer, cpt, gaps),
        }
        if lead["fills_current_gap"]:
            fills_gap += 1
        leads.append(lead)

    print(f"export rows: {len(rows)} | on our 18 codes: {len(leads)} | "
          f"parked (other codes): {parked}")
    print(f"leads that would fill a current gap cell: {fills_gap}")
    print(f"column mapping used: {mapping}")
    if not args.report_only:
        OUT.write_text(json.dumps({
            "source": "DataQorp export (licensed; leads only, never cited)",
            "ingested_from": args.export.name,
            "leads": leads}, indent=1), encoding="utf-8")
        print(f"wrote {len(leads)} leads -> {OUT.relative_to(ROOT)}")
        print("next: run the verification pass over leads with URLs — every "
              "one gets fetched and read before it can touch the directory")


if __name__ == "__main__":
    main()
