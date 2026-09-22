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
    ref = _norm(policy_url) + "\u0000" + _norm(policy_title)
    haystack += "\u0000" + ref

    def known(tok: str) -> bool:
        if _norm(tok) in haystack:
            return True
        # "CPB 0660" is an Aetna bulletin whose number lives in the URL path
        # (.../data/600_699/0660.html) and nowhere in the body, so the whole
        # token never matches. Match its number against the URL and title
        # instead. Being generous here is the safe direction: calling a correct
        # citation invented is a worse error than missing an invented one.
        digits = re.findall(r"\d{3,}", tok)
        return any(d in ref for d in digits)

    ids = sorted(set(_POLICY_ID.findall(letter or "")))
    dates = sorted(set(_EFFECTIVE.findall(letter or "")))
    bad_ids = [t for t in ids if not known(t)]
    bad_dates = [t for t in dates if _norm(t) not in haystack]
    return {"policy_ids": len(ids), "policy_ids_invented": bad_ids,
            "effective_dates": len(dates), "effective_dates_invented": bad_dates,
            "any_invented": bool(bad_ids or bad_dates)}


# ---------------------------------------------------------------------------
# Rules stated as the plan's that the writer had no source for
# ---------------------------------------------------------------------------
# In 45 of 120 in-library letters on 2026-09-21 the writer stated a threshold
# as the plan's -- "the six weeks the policy contemplates", "an arc of motion
# of at least 90 degrees" -- that was in none of the excerpts it was given. A
# reviewer who checks it against the policy finds it is not there, and the
# letter is discredited. The tell is mechanical: a number with a unit, or a
# duration, in a sentence that attributes a requirement to the plan, where
# that number appears in no excerpt.
_ATTRIB = re.compile(
    r"\b(polic(?:y|ies)|plan|guideline|criteri(?:a|on)|insurer|carrier)\b[^.\n]{0,80}?"
    r"\b(requires?|required|states?|stated|contemplates?|specif(?:y|ies)|lists?|"
    r"calls? for|sets?|mandates?|expects?|defines?|provides?|threshold|"
    r"standard|minimum|maximum)\b|"
    r"\b(under|per|according to|pursuant to)\s+(the\s+)?(polic(?:y|ies)|plan|guideline|criteria)\b|"
    r"\b(polic(?:y|ies)|plan|guideline)['’]s\s+(own\s+)?(criteri|requirement|threshold|standard|minimum)",
    re.I)
_NUMBER = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(-|to|–)?\s*(\d+(?:\.\d+)?)?\s*"
    r"(weeks?|wks?|months?|mos?|years?|yrs?|days?|degrees?|°|mm|cm|percent|%|visits?|"
    r"sessions?|injections?|levels?|compartments?|grade|episodes?|dislocations?)\b", re.I)
_WORDNUM = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
            "seven": "7", "eight": "8", "nine": "9", "ten": "10", "twelve": "12"}


def _numbers(text: str) -> set[str]:
    t = text.lower()
    for w, d in _WORDNUM.items():
        t = re.sub(rf"\b{w}\b", d, t)
    t = t.replace("°", " degrees")
    out = set()
    for m in _NUMBER.finditer(t):
        unit = m.group(4).lower().rstrip("s")
        unit = {"wk": "week", "mo": "month", "yr": "year", "%": "percent"}.get(unit, unit)
        out.add(f"{m.group(1)} {unit}")
        if m.group(3):
            out.add(f"{m.group(3)} {unit}")
    return out


def unsourced_requirements(letter: str, excerpts: list[str],
                           facts: list[str] | None = None) -> dict:
    """Sentences that attribute a quantified requirement to the plan which no
    excerpt contains. `facts` are the records and the notice: a number that
    comes from there is the patient's fact, not an invented rule, even in a
    sentence that also mentions the policy."""
    have = set()
    for e in list(excerpts or []) + list(facts or []):
        have |= _numbers(e)
    flagged = []
    for sent in re.split(r"(?<=[.;!?])\s+|\n+", letter or ""):
        if not _ATTRIB.search(sent):
            continue
        missing = sorted(n for n in _numbers(sent) if n not in have)
        if missing:
            flagged.append({"sentence": sent.strip()[:300], "numbers": missing})
    return {"flagged": flagged, "count": len(flagged)}
