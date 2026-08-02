"""Feed the policy directory + verified cache into a retrieval run as leads.

The live retrieval agent is always primary: it searches and reads the payer's
current policy fresh. But we can hand it strong *leads* so it lands on the right
document faster and has a fallback when live search comes up empty:

- the procedure-policy directory (data/policy_platform/procedure_policy_directory
  .json) — the known governing policy URL per carrier x procedure, and
- verified, non-stale, reusable entries from the patient-contributed policy cache.

These are presented to the agent as anchors to CHECK FIRST and VERIFY, never as
the answer. A stale or unverifiable lead is filtered out here; the agent must
still confirm the document is current and actually governs the procedure.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import policy_cache

WORKSPACE = Path(__file__).resolve().parents[1]
_DIRECTORY = WORKSPACE / "data" / "policy_platform" / "procedure_policy_directory.json"

# payer-name substrings -> directory carrier key.
_CARRIER_MATCH = [
    (("unitedhealth", "uhc"), "UnitedHealthcare"),
    (("aetna",), "Aetna (CVS Health)"),
    (("cigna",), "Cigna"),
    (("anthem", "elevance"), "Elevance / Anthem BCBS"),
    (("humana",), "Humana"),
    (("ambetter", "centene", "wellcare"), "Centene (Ambetter/WellCare)"),
    (("molina",), "Molina Healthcare"),
    (("florida blue", "guidewell"), "Florida Blue / GuideWell"),
    (("medicare",), "Medicare"),
    # Any Blue Cross / Blue Shield plan -> HCSC's shared Blue policy set.
    (("hcsc", "blue cross", "bcbs", "blue shield"), "HCSC (BCBS IL/TX/NM/OK/MT)"),
]


@lru_cache(maxsize=1)
def _directory() -> dict[str, Any]:
    try:
        return json.loads(_DIRECTORY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"policies": {}}


def carrier_key(payer: str | None) -> str | None:
    n = (payer or "").lower()
    for needles, key in _CARRIER_MATCH:
        if any(x in n for x in needles):
            return key
    return None


def _cpt_matches(patient_cpt: str, entry_cpt: str) -> bool:
    """True when the patient's CPT is covered by the directory row's cpt field.

    Handles single codes, ranges ('29914-29916'), and slash lists
    ('73721/73221/72148').
    """
    p = (patient_cpt or "").strip()
    if not p:
        return False
    tokens = [t.strip() for t in (entry_cpt or "").replace("/", " ").replace(",", " ").split()]
    for tok in tokens:
        if tok == p:
            return True
        if "-" in tok:  # numeric range
            lo, _, hi = tok.partition("-")
            if lo.isdigit() and hi.isdigit() and p.isdigit() and int(lo) <= int(p) <= int(hi):
                return True
    return False


def anchors_for(payer: str | None, cpt: str | None) -> list[dict[str, Any]]:
    """Directory + verified cache leads for this carrier + CPT. May be empty."""
    anchors: list[dict[str, Any]] = []
    key = carrier_key(payer)
    if key:
        for row in _directory().get("policies", {}).get(key, []):
            if not row.get("url") or not row.get("doc_is_public"):
                continue
            if not _cpt_matches(cpt or "", row.get("cpt", "")):
                continue
            anchors.append({
                "source": "directory",
                "carrier": key,
                "title": row.get("policy_title") or "",
                "url": row["url"],
                "effective_date": row.get("effective_date") or None,
                "verified": bool(row.get("cpt_verified")),
                "note": row.get("notes") or "",
            })
    # Verified, non-stale, non-personal contributed docs for the same plan.
    for meta in policy_cache.reuse_candidates(payer or "", cpt or ""):
        anchors.append({
            "source": "contributed",
            "carrier": payer,
            "title": f"Patient-contributed policy ({meta.get('filename') or 'upload'})",
            "url": None,
            "entry_id": meta.get("entry_id"),
            "effective_date": meta.get("contributed_at", "")[:10] or None,
            "verified": True,
            "note": "Contributed by another patient on this plan; re-verify it is current.",
        })
    return anchors


def anchors_prompt_block(anchors: list[dict[str, Any]]) -> str:
    """Render anchors as a prompt section, or '' when there are none."""
    if not anchors:
        return ""
    lines = [
        "\nKNOWN POLICY LEADS (check these FIRST, but still verify — do not trust "
        "blindly). These are prior findings of the likely governing policy for "
        "this payer and procedure. Confirm each is the current, applicable policy "
        "and that the CPT is in it; prefer a fresher official source if the payer "
        "has updated it. If a lead is outdated or wrong, say so and retrieve anew.",
    ]
    for a in anchors:
        loc = a["url"] if a.get("url") else f"(contributed document {a.get('entry_id')})"
        eff = f", effective {a['effective_date']}" if a.get("effective_date") else ""
        lines.append(f"- [{a['source']}] {a['title']}{eff}: {loc}")
    return "\n".join(lines) + "\n"
