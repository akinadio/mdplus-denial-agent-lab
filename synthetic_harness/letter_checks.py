#!/usr/bin/env python3
"""Two things a reviewer checks before reading a word of the argument.

SENDABILITY. An appeal is processed by a clerk before it reaches anyone
clinical, and a letter missing the member ID or the reference number is
returned or lost at intake -- the argument never gets read, however good it is.
Every identifier checked here is printed on the denial notice, so "the letter
carries it" is a string comparison, not a judgement.

INVENTED IDENTIFIERS. A policy number or an effective date that appears nowhere
in the policy, the notice or the records was made up. In the 2026-09 pilot six
of ChatGPT's thirteen factual errors were exactly this, and they were found by
a model reading the letter -- which is slower, costs money, and disagrees with
itself. A policy number is a short, distinctive token; checking it by string
match is what that job actually needs.

Nothing here calls a model, so both run on every letter for free.
"""
from __future__ import annotations

import re

from .letter_inputs import notice_fields

# What has to be on the envelope for the appeal to be worked at all.
SENDABILITY_FIELDS = ("member_id", "reference_number", "member_name", "denial_date")

# The shapes a plan gives its policies. Deliberately narrow: a false "invented"
# is worse than a miss, because it accuses the system of something it did not do.
_POLICY_ID = re.compile(
    r"\b(?:"
    r"[A-Z]{2,4}\.[A-Z]{2,4}\.[A-Z0-9]{2,6}(?:\.\d+)?"      # CP.MP.114, CMM.JT.IN.311
    r"|\d{4}[A-Z]\d{3,4}[A-Z]{0,2}"                          # 2026T0639I
    r"|(?:Policy|Guideline|Bulletin|CPB|Coverage Policy)\s*(?:number\s*)?#?\s*\d{3,6}"
    r")\b")
_EFFECTIVE = re.compile(
    r"(?:effective|revised|last reviewed|version)[^.\n]{0,40}?"
    r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}/\d{2,4}|"
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},?\s+\d{4})\b", re.I)


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def _date_forms(v: str) -> list[str]:
    """Every way a letter might write the date the notice states.

    Without this the check was biased toward OrthoAppeals and against every
    chatbot: our own letters are handed the notice's exact string "2026-08-07",
    while a chatbot writes "August 7, 2026" -- the same date, scored as missing.
    ChatGPT "failed" sendability on 59 of 60 letters purely on that.
    """
    import datetime
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%m/%d/%y"):
        try:
            d = datetime.datetime.strptime(v.strip(), fmt).date()
        except ValueError:
            continue
        return [d.isoformat(), d.strftime("%B %d, %Y"), d.strftime("%b %d, %Y"),
                d.strftime("%m/%d/%Y"), f"{d.month}/{d.day}/{d.year}",
                d.strftime("%d %B %Y"), f"{d.strftime('%B')} {d.day}, {d.year}"]
    return [v]


def sendability(letter: str, notice: str) -> dict:
    """Which identifiers from the notice the letter actually carries.

    `present` is the count, `complete` is the endpoint: a letter a clerk can
    process without going back to the patient for the basics.
    """
    fields = notice_fields(notice or "")
    L = _norm(letter)
    got, missing = {}, []
    for k in SENDABILITY_FIELDS:
        v = (fields.get(k) or "").strip()
        if not v:
            continue          # the notice never stated it; not the letter's fault
        forms = _date_forms(v) if k in ("denial_date", "dob") else [v]
        ok = any(_norm(f)[:24] in L for f in forms if len(_norm(f)) >= 4)
        got[k] = ok
        if not ok:
            missing.append(k)
    return {"checked": len(got), "present": sum(got.values()),
            "missing": missing, "fields": got,
            "complete": bool(got) and not missing}


def invented_identifiers(letter: str, policy_text: str, other: list[str] | None = None,
                         policy_url: str = "", policy_title: str = "") -> dict:
    """Policy numbers and effective dates in the letter that are in no source.

    `other` is the denial notice and the chart: a reference number off the
    notice is not an invented policy number, and neither is the date of the
    patient's own MRI.
    """
    # The policy's URL and title count as sources. "CPB 0660" is an Aetna
    # bulletin number that lives in the URL
    # (aetna.com/cpb/medical/data/600_699/0660.html) and often nowhere in the
    # body text, so checking the body alone called a correct citation invented
    # -- in every arm, including ours.
    haystack = _norm(policy_text or "") + "\u0000" + "\u0000".join(
        _norm(o) for o in (other or []))
    haystack += "\u0000" + _norm(policy_url) + "\u0000" + _norm(policy_title)
    ids = sorted(set(_POLICY_ID.findall(letter or "")))
    dates = sorted(set(_EFFECTIVE.findall(letter or "")))
    bad_ids = [t for t in ids if _norm(t) not in haystack]
    bad_dates = [t for t in dates if _norm(t) not in haystack]
    return {"policy_ids": len(ids), "policy_ids_invented": bad_ids,
            "effective_dates": len(dates), "effective_dates_invented": bad_dates,
            "any_invented": bool(bad_ids or bad_dates)}
