"""A cache of policy citations already found by a previous run.

Why this exists
----------------
Live retrieval is not cheap: a single row that has to search and read its way
to a governing policy document can cost several dollars and take a minute or
more (see runs/proof-006 for a real example: two rows, $17.62, because each
one took 15-22 real search/fetch round trips). But most of that cost buys
nothing new the second time: if a patient with BCBS Michigan Medicare
Advantage and a knee replacement denial shows up today, and another patient
with the exact same payer/state/procedure showed up last week, the document
that governs the case has not changed. There is no reason to pay to
rediscover it.

This module is that memory. `data/policy_platform/known_citations.json` holds
citations already found by prior runs (currently seeded from a manually
reviewed export of the team's own past episodes). `lookup()` checks it before
a live run starts; a hit skips the paid search+fetch loop entirely.

What this is NOT
-----------------
This is a cache for the PRODUCT (real patients), not a hint bank. It must
never be wired into scripts/policy_eval/ (the accuracy benchmark) -- that
harness exists specifically to prove the model can find the right document
cold, with nothing handed to it. Feeding it this cache would be handing it
the answer and the benchmark would stop measuring anything real.

Trust posture
-------------
Every entry here has `human_reviewed: false` -- none of this has had a person
confirm it yet, only a model. Treat a cache hit as a strong, cheap starting
point that still gets shown to the patient with its original confidence and
source, not as ground truth to certify silently. A `note` field on some
entries flags real open questions (disagreeing runs, unresolved product
questions) that a human should look at before leaning on that entry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "policy_platform" / "known_citations.json"

# A handful of common full-state-name spellings seen in patient submissions
# and in this seed data, normalized to the two-letter code entries are keyed
# on. Not exhaustive; extend as real mismatches turn up.
_STATE_NAME_TO_CODE = {
    "california": "CA",
    "texas": "TX",
    "ohio": "OH",
    "florida": "FL",
    "alaska": "AK",
    "michigan": "MI",
    "north carolina": "NC",
}

# Words that mark a genuinely different product line under the same brand
# name -- "Aetna" and "Aetna Better Health" are different companies with
# different governing policies, not a naming variation of the same plan. If
# one of these appears on only one side of a comparison, the match is
# rejected even though the brand name is a substring match, so a Medicaid
# managed-care plan never silently inherits a commercial plan's citation (or
# the reverse).
_PRODUCT_LINE_QUALIFIERS = (
    "medicaid",
    "medicare advantage",
    "advantage",
    "better health",
    "promise",
    "chip",
    "dual",
    "snp",
    "community plan",
    "healthy blue",
)


def _qualifier_set(s: str) -> frozenset[str]:
    return frozenset(q for q in _PRODUCT_LINE_QUALIFIERS if q in s)

_cache: list[dict[str, Any]] | None = None


def _normalize_payer(raw: str) -> str:
    """Lowercase, strip punctuation/parentheticals, collapse whitespace.

    Real submissions and this seed data both sometimes carry a payer field
    that is a full sentence (e.g. "Medicare (payer entity as stated by
    patient; ... not yet confirmed)") rather than a clean name. Strip
    parenthetical asides and keep only the leading words, which is where the
    actual payer name lives in every example seen so far.
    """
    if not raw:
        return ""
    s = raw.strip().lower()
    s = re.sub(r"\([^)]*\)", "", s)  # drop parenthetical asides
    s = re.sub(r"[;,].*$", "", s)  # drop trailing clauses after ; or ,
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_state(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip().lower()
    if s in _STATE_NAME_TO_CODE:
        return _STATE_NAME_TO_CODE[s]
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[—–-].*$", "", s)
    s = s.strip()
    if len(s) == 2:
        return s.upper()
    return _STATE_NAME_TO_CODE.get(s, s.upper())


def _normalize_cpt(raw: str) -> str:
    if not raw:
        return ""
    # Submissions occasionally carry "27447" or "CPT 27447"; keep digits only.
    digits = re.sub(r"[^0-9]", "", raw)
    return digits


def _load() -> list[dict[str, Any]]:
    global _cache
    if _cache is None:
        if not _DATA_PATH.exists():
            _cache = []
        else:
            _cache = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return _cache


def reload() -> None:
    """Force the next lookup() to re-read the file. Mainly for tests."""
    global _cache
    _cache = None


def lookup(payer: str, state: str, cpt: str) -> dict[str, Any] | None:
    """Return a cached citation for (payer, state, cpt), or None.

    Matching is intentionally strict on state and cpt (exact, after
    normalization) and permissive on payer (substring match either
    direction), since payer names in the wild carry a lot of variation
    ("Aetna" vs "Aetna Choice POS II" vs a full descriptive sentence) but
    state and CPT are the parts that must not be fuzzy -- a wrong CPT match
    would point a patient at the wrong procedure's policy entirely.
    """
    payer_n = _normalize_payer(payer)
    state_n = _normalize_state(state)
    cpt_n = _normalize_cpt(cpt)
    if not payer_n or not state_n or not cpt_n:
        return None

    for entry in _load():
        if entry.get("state") != state_n:
            continue
        if cpt_n not in (entry.get("cpt") or []):
            continue
        key = entry.get("payer_key", "")
        if key not in payer_n and payer_n not in key:
            continue
        # Brand-name substring matched, but reject it if either side carries
        # a product-line qualifier the other doesn't -- see
        # _PRODUCT_LINE_QUALIFIERS above.
        if _qualifier_set(payer_n) != _qualifier_set(key):
            continue
        return entry
    return None
