"""Everything the appeal letter needs that retrieval does not produce.

The pilot graded letters the study had drafted with the deadline, the
submission route, the member's identifiers and the criteria demand all filled
in -- by the study's own code. The live server passed the letter generator the
retrieval result and the denial text, and nothing else. So the study was
measuring a better letter than a patient gets. This module is the one place
those inputs are assembled, and both the server and the study call it.

  enrich(result, denial_text, payer=..., plan_type=...) -> result
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

from .policy_text import submission_route, ROOT

ACCESS_FILE = ROOT / "data" / "policy_platform" / "criteria_access_directory.json"
_ACCESS: dict | None = None

_FIELDS = (
    ("member_name", r"(?:Member|Patient|Member name)\s*:\s*([^\n]+)"),
    ("member_id", r"(?:Member ID|Subscriber ID|ID number|Member #)\s*:?\s*([A-Za-z0-9-]{5,})"),
    ("dob", r"(?:Date of birth|DOB)\s*:?\s*([^\n]+)"),
    ("denial_date", r"(?:Date of notice|Date of denial|Notice date|Date)\s*:\s*([^\n]+)"),
    ("reference_number", r"(?:Reference(?: number| #| no\.?)?|Case (?:number|#)|Claim (?:number|#))\s*:?\s*([A-Za-z0-9-]{4,})"),
)
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|"
                   r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})\b")
_BY = re.compile(r"(?:received|submitted|filed|postmarked)\s+(?:by|no later than|on or before)\s+\(?" + _DATE.pattern[2:-2] + r"\)?", re.I)
_WITHIN = re.compile(r"within\s+(\d{2,3})\s+(?:calendar\s+)?days", re.I)


def _parse_date(s: str) -> datetime.date | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def notice_fields(text: str) -> dict[str, str]:
    """Member, ID, dates and reference number, read off the denial notice the
    way a person would. Only what is actually there."""
    out: dict[str, str] = {}
    for key, pat in _FIELDS:
        m = re.search(pat, text or "", re.I)
        if m:
            out[key] = m.group(1).strip().strip(".")
    return out


def appeal_deadline(text: str) -> str:
    """The deadline the notice states, or one computed from 'within N days of
    <notice date>'. Empty if the notice does not say -- the letter then tells
    the patient to check the notice, which is the honest answer."""
    m = _BY.search(text or "")
    if m:
        d = _parse_date(m.group(1))
        if d:
            return d.isoformat()
    w = _WITHIN.search(text or "")
    nd = notice_fields(text).get("denial_date", "")
    if w and nd:
        d = _parse_date(_DATE.search(nd).group(1)) if _DATE.search(nd) else None
        if d:
            return (d + datetime.timedelta(days=int(w.group(1)))).isoformat()
    return ""


def _access() -> dict:
    global _ACCESS
    if _ACCESS is None:
        try:
            _ACCESS = json.loads(ACCESS_FILE.read_text())
        except Exception:  # noqa: BLE001
            _ACCESS = {}
    return _ACCESS


def criteria_request(payer: str, note: str = "") -> str:
    """How this patient gets the criteria the plan actually applied, from the
    researched access directory: the insurer's own route first, then the
    vendor's. Generic only when nothing is known."""
    acc = _access()
    ins = (payer or "").lower().strip()
    hit = acc.get(ins)
    if hit is None:
        for k, v in acc.items():
            if not k.startswith("_") and k and (k in ins or ins in k):
                hit = v
                break
    if hit is None:
        n = (note or "").lower()
        for v in ("evolent", "carelon", "evicore", "turningpoint", "interqual", "mcg"):
            if v in n and "_" + v in acc:
                hit = acc["_" + v]
                break
    how = (hit or {}).get("how") or ""
    return how or ("Ask the plan in writing for the exact clinical criteria used in this "
                   "denial, including the name and edition of any review guideline. "
                   "You are entitled to them.")


def enrich(result: dict[str, Any], denial_text: str | None, *,
           payer: str = "", plan_type: str = "", directory_note: str = "") -> dict[str, Any]:
    """Return a copy of `result` with everything the letter needs filled in."""
    r = dict(result or {})
    ci = dict(r.get("case_identification") or {})
    text = denial_text or ""
    payer = payer or ci.get("payer") or ""
    plan_type = plan_type or ci.get("product_type") or ""
    for k, v in notice_fields(text).items():
        ci.setdefault(k, v)
    r["case_identification"] = ci
    if text and not r.get("denial_notice_text"):
        r["denial_notice_text"] = text
    if not r.get("appeal_deadline"):
        r["appeal_deadline"] = appeal_deadline(text)
    if not r.get("submission_route"):
        r["submission_route"] = submission_route(payer, plan_type)
    src = (r.get("retrieval") or {}).get("selected_source") or {}
    cites = (r.get("retrieval") or {}).get("citations") or []
    # Demand the criteria whenever the letter cannot quote them: no document,
    # or a document whose criteria are vendor-held.
    if not r.get("criteria_request") and (not src.get("url") or not cites
                                          or "vendor" in (directory_note or "").lower()
                                          or "interqual" in (directory_note or "").lower()):
        r["criteria_request"] = criteria_request(payer, directory_note)
    return r
