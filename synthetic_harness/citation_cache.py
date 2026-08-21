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

Cross-check against our own verification record
-----------------------------------------------
The cache is not the only thing in this repository that knows about these
documents. `data/policy_platform/url_verification_ledger.json` and
`app_option_policy_directory.csv` hold the result of independently fetching
and reading thousands of payer policies, with a strict verdict vocabulary
(verified / criteria_proprietary_not_public / rejected_code_only / stale /
...). On every hit, `lookup()` consults that record and attaches
`ledger_verdict` (+ `ledger_note`) to the entry it returns, so the retrieval
prompt can say what we independently know about the document rather than
just replaying what one prior run believed.

This matters concretely. Two of the eight seed entries -- UnitedHealthcare
OH/27447 and UnitedHealthcare FL/63030 -- name real, current UHC policy PDFs,
but our own sweep found that UHC keeps the actual medical-necessity criteria
in InterQual; the public document carries codes and a pointer, not criteria.
A run that trusted the cache blindly would fetch a document, find nothing to
quote, and waste the round trip. With the verdict attached, the agent is told
that up front.

STATUS (2026-08-21)
-------------------
Live. `data/policy_platform/known_citations.json` is in the repository with 8
seeded entries. Of those, five agree exactly with our independent
verification (Aetna TX/27447, Cigna FL/27447, Cigna FL/27130, Medicare
CA/27447 L36575, Alaska Medicaid AK/27130); two are the InterQual cases
above; and one -- Blue Shield of California, shoulder -- points at a policy
that by its own terms covers PARTIAL-thickness rotator cuff tears only, and
also claims two CPT codes (29826, 29807) the app does not offer. Check the
cache size at any time with:

    python3 -c "from synthetic_harness import citation_cache as c; print(len(c._load()), 'entries')"
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

_PLATFORM_DIR = Path(__file__).resolve().parents[1] / "data" / "policy_platform"
_DATA_PATH = _PLATFORM_DIR / "known_citations.json"
_LEDGER_PATH = _PLATFORM_DIR / "url_verification_ledger.json"
_DIRECTORY_PATH = _PLATFORM_DIR / "app_option_policy_directory.csv"

# App-directory status strings mapped onto the ledger's verdict vocabulary, so
# a caller only ever has to reason about one set of words.
_DIRECTORY_STATUS_TO_VERDICT = {
    "VERIFIED": "verified",
    "VERIFIED (CMS LCD/NCD)": "verified",
    "VERIFIED (state Medicaid doc)": "verified",
    "VERIFIED (state Medicaid entry point)": "verified",
    "VERIFIED (procedure criteria)": "verified",
    "NO PUBLIC CRITERIA (vendor)": "criteria_proprietary_not_public",
    "CODE ONLY": "rejected_code_only",
    "STALE": "stale_superseded",
    "GATED": "gated_login",
    "UNREACHABLE": "unreachable",
    "NOT FOUND": "not_found",
}

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
    """Force the next lookup() to re-read the files. Mainly for tests."""
    global _cache, _verdicts
    _cache = None
    _verdicts = None


def _normalize_url(raw: str) -> str:
    """Key form for comparing two spellings of the same document URL.

    Lowercased, trailing slash and fragment dropped, query parameters sorted.
    That is enough to make `...lcd.aspx?LCDId=36575` and
    `...lcd.aspx?lcdid=36575` the same key, which is exactly the variation
    that shows up between a model-authored citation and our own ledger.
    """
    if not raw:
        return ""
    s = raw.strip().split("#", 1)[0]
    base, _, query = s.partition("?")
    base = base.rstrip("/").lower()
    if not query:
        return base
    parts = sorted(p.lower() for p in query.split("&") if p)
    return base + "?" + "&".join(parts)


_verdicts: dict[tuple[str, str], tuple[str, str]] | None = None


def _load_verdicts() -> dict[tuple[str, str], tuple[str, str]]:
    """Index our independent verification record as (url, cpt) -> (verdict, note).

    Two sources, ledger first because it is the more detailed one: the
    URL verification ledger (per-URL, per-CPT verdicts with quotes) and, as a
    fallback for documents the ledger does not carry a row for, the
    app-option directory's per-option status. Both are optional -- a
    deployment without the data files simply gets no verdicts, never an
    error.
    """
    global _verdicts
    if _verdicts is not None:
        return _verdicts
    out: dict[tuple[str, str], tuple[str, str]] = {}

    # Fallback source first, so ledger rows overwrite it where both exist.
    if _DIRECTORY_PATH.exists():
        try:
            with _DIRECTORY_PATH.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    verdict = _DIRECTORY_STATUS_TO_VERDICT.get((row.get("status") or "").strip())
                    url = _normalize_url(row.get("policy_url") or "")
                    cpt = _normalize_cpt(row.get("cpt") or "")
                    if verdict and url and cpt:
                        out[(url, cpt)] = (verdict, (row.get("note") or "").strip())
        except (OSError, csv.Error):
            pass

    if _LEDGER_PATH.exists():
        try:
            ledger = json.loads(_LEDGER_PATH.read_text(encoding="utf-8")).get("urls") or {}
        except (OSError, json.JSONDecodeError, AttributeError):
            ledger = {}
        for url, rec in ledger.items():
            if not isinstance(rec, dict):
                continue
            key_url = _normalize_url(url)
            note = (rec.get("note") or "").strip()
            for cpt, verdict in (rec.get("per_cpt") or {}).items():
                out[(key_url, _normalize_cpt(cpt))] = (str(verdict), note)

    _verdicts = out
    return _verdicts


def verdict_for(url: str, cpt: str) -> tuple[str, str] | None:
    """Our own verification verdict for a (document, procedure) pair, if any."""
    key = (_normalize_url(url), _normalize_cpt(cpt))
    if not key[0] or not key[1]:
        return None
    return _load_verdicts().get(key)


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
        # Hand back a copy annotated with what our own verification record
        # says about this exact document for this exact procedure, so callers
        # never have to trust the prior run's self-report alone.
        hit = dict(entry)
        found = verdict_for(entry.get("selected_source_url") or "", cpt_n)
        if found:
            hit["ledger_verdict"], ledger_note = found
            if ledger_note:
                hit["ledger_note"] = ledger_note
        return hit
    return None
