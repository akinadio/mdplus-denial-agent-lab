"""Fetch and cache the actual text of a policy document.

The whole claim of this product is that the appeal quotes the payer's own
words. Until now the directory held a title and a URL and no policy text at
all, so when the letter generator was told to "quote the plan's criteria" it
had nothing to quote and invented language that reads like criteria. The
2026-09-05 grading found that on 47% of in-library letters -- the exact failure
the tool exists to prevent, and worse than being unable to answer, because an
invented quote is checkable and discredits everything around it.

So: read the document. Text is cached on disk by URL, because the same policy
serves dozens of cases and the study should not fetch it dozens of times.

  from synthetic_harness.policy_text import criteria_for, policy_text
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
CACHE = ROOT / "data" / "policy_platform" / "policy_text_cache"
LIBRARY = ROOT / "data" / "policy_platform" / "criteria_extractions.json"

# Sentences that carry a coverage rule, rather than scope, history or coding.
_CRITERIA_CUES = re.compile(
    r"\b(medically necessary|indicated when|considered medical|criteria|"
    r"documented|conservative|failed|at least|minimum of|weeks of|months of|"
    r"trial of|nonsurgical|non-surgical|unresponsive|refractory)\b", re.I)
_NOISE = re.compile(r"^\s*(page \d+|table of contents|©|copyright|proprietary)", re.I)


def _key(url: str) -> Path:
    return CACHE / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".json")


def policy_text(url: str, refresh: bool = False) -> dict:
    """Return {'text', 'status', 'final_url', 'error'} for a policy URL."""
    if not (url or "").strip():
        return {"text": "", "error": "no url"}
    p = _key(url)
    if p.exists() and not refresh:
        cached = json.loads(p.read_text())
        # An empty result is a failure to read, not a fact about the document.
        # It is never a cache hit, so a fixed extractor gets a second try.
        if cached.get("text"):
            return cached
    from policy_eval.webtools import fetch
    try:
        r = fetch(url, max_text_chars=400000)
        text = r.get("text") or ""
        # fetch() reports a failed PDF extraction as blocked_reason
        # "extraction_failed:...", with status 200 and empty text. On
        # 2026-09-05 that read as "200, no criteria" for 32 of 44 documents
        # because pypdf was not installed. Say what actually happened.
        err = r.get("error") or ""
        if not text and not err:
            err = (r.get("blocked_reason") or r.get("login_wall_reason")
                   or f"no text extracted (content-type {r.get('content_type')})")
        out = {"url": url, "final_url": r.get("final_url"), "status": r.get("status"),
               "content_type": r.get("content_type"), "text": text, "error": err}
    except Exception as exc:  # noqa: BLE001
        out = {"url": url, "text": "", "error": f"{type(exc).__name__}: {exc}"}
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out))
    return out


# What a procedure is called inside a policy. The CPT itself usually appears
# only in a codes table at the end of a section, so "near the CPT" found the
# codes table; the criteria live under the procedure's own heading.
PROCEDURE_TERMS = {
    "27130": ["total hip arthroplasty", "hip arthroplasty", "total hip replacement", "hip replacement"],
    "27447": ["total knee arthroplasty", "knee arthroplasty", "total knee replacement", "knee replacement"],
    "27446": ["unicompartmental", "partial knee", "unicondylar"],
    "29881": ["meniscectomy", "knee arthroscopy", "arthroscopic knee"],
    "29880": ["meniscectomy", "knee arthroscopy"],
    "29888": ["anterior cruciate", "acl reconstruction", "cruciate ligament"],
    "29914": ["femoroacetabular", "hip arthroscopy", "arthroscopic hip"],
    "23472": ["total shoulder arthroplasty", "shoulder arthroplasty", "shoulder replacement"],
    "29827": ["rotator cuff"],
    "29806": ["labral", "instability", "capsulorrhaphy", "bankart"],
    "22551": ["anterior cervical discectomy", "cervical fusion", "cervical arthrodesis", "acdf"],
    "22612": ["lumbar fusion", "lumbar spinal fusion", "lumbar arthrodesis", "spinal fusion"],
    "63030": ["laminotomy", "discectomy", "lumbar decompression", "microdiscectomy"],
    "27702": ["total ankle arthroplasty", "ankle arthroplasty", "ankle replacement"],
    "28296": ["hallux valgus", "bunion", "bunionectomy"],
}
# Front matter and definitions that read like criteria but are not this
# procedure's rule. A letter that quotes "Carelon reviews all of its Guidelines
# at least annually" has quoted the policy and said nothing.
_BOILERPLATE = re.compile(
    r"guidelines? (establish|are designed|apply)|reviews all of its|take precedence|"
    r"appropriate use criteria:|description and scope|table of contents|"
    r"for this guideline.s purposes|copyright|all rights reserved|proprietary|"
    r"made available for|limited uses of|individual use, only|"
    # an imaging-guidelines preface inside a surgery guideline, and the
    # clinical-evidence section's study summaries, both read like criteria
    r"provision of diagnostic imaging|imaging guidelines|"
    r"\b(participants|patients|individuals|subjects) (were|met the inclusion)|"
    r"\b(randomized|cohort|retrospective|prospective|meta-analysis|systematic review)\b|"
    r"\b(one|two|three|four|five|six|seven|eight|nine) (hundred|thousand)\b", re.I)
_SECTION_END = re.compile(r"\b(References|Codes|CPT Codes|ICD-10|Coding|Revision History)\b")


def _procedure_window(text: str, cpt: str) -> str:
    """The stretch of the document that is about this procedure.

    Picks the occurrence of the procedure's name that is followed soonest by
    criteria language -- that skips the table of contents, where the name
    appears first but says nothing -- and runs to the section's codes or
    references, or 15k characters, whichever comes first.
    """
    terms = PROCEDURE_TERMS.get(cpt, [])
    if not terms or not text:
        return ""
    low = text.lower()
    best, best_gap = None, 10**9
    for t in terms:
        for m in re.finditer(re.escape(t), low):
            tail = low[m.start(): m.start() + 4000]
            k = re.search(r"medically necessary|clinical indications|indicated|criteria|"
                          r"considered", tail)
            gap = k.start() if k else 10**8
            if gap < best_gap:
                best, best_gap = m.start(), gap
    if best is None:
        return ""
    body = text[best: best + 15000]
    e = _SECTION_END.search(body, 800)
    return body[: e.start()] if e else body


def _sentences(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text)
    return [c.strip() for c in re.split(r"(?<=[.;:])\s+|\n{2,}", text) if c.strip()]


def find_criteria(text: str, cpt: str = "", limit: int = 14) -> list[str]:
    """Pull the criteria sentences for THIS procedure out of a policy.

    Deliberately dumb and verbatim: it selects, it never paraphrases. Anything
    it returns can be checked against the document character for character,
    which is the property that matters. The procedure's own section comes
    first; the rest of the document only fills in behind it.
    """
    if not text:
        return []
    seen, out = set(), []

    def take(chunks, want):
        carry = 0   # items of a list that a lead-in sentence just opened
        for c in chunks:
            if len(out) >= want:
                break
            if len(c) < 25 or len(c) > 600 or _NOISE.match(c) or _BOILERPLATE.search(c):
                continue
            # "...is medically necessary for ANY of the following:" is followed by
            # the indications themselves, which are noun phrases with no cue
            # word in them. They are the criteria; keep the next few.
            opens_list = bool(re.search(r"following:?\s*$", c, re.I))
            if not _CRITERIA_CUES.search(c) and carry <= 0:
                continue
            k = c[:80].lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(c)
            carry = 4 if opens_list else carry - 1

    take(_sentences(_procedure_window(text, cpt)), limit)
    if len(out) < 6:                      # thin section, or no section found
        take(_sentences(text), limit)
    return out[:limit]


def verify_quote(quote: str, text: str) -> bool:
    """Is this quote actually in the document? Whitespace-insensitive."""
    n = lambda s: re.sub(r"\s+", " ", s).strip().lower()  # noqa: E731
    q = n(quote)
    return len(q) > 25 and q in n(text)


_LIB: dict | None = None


def _library() -> dict:
    """Criteria extracted ahead of time, keyed by policy URL.

    Built by scripts/policy_platform/build_criteria_library.py. A patient is
    waiting while the app answers, so a live fetch of a 60-page PDF is the
    fallback, not the plan.
    """
    global _LIB
    if _LIB is None:
        try:
            raw = json.loads(LIBRARY.read_text())
        except Exception:  # noqa: BLE001
            raw = []
        entries = raw.get("policies", raw) if isinstance(raw, dict) else raw
        _LIB = {e["policy_url"]: e for e in entries if isinstance(e, dict) and e.get("policy_url")}
    return _LIB


def criteria_for(url: str, cpt: str = "", allow_fetch: bool = True) -> dict:
    """Verbatim criteria for a policy, and the text they were taken from.

    Returns {'quotes', 'text', 'source'}. `source` is 'library', 'fetch' or
    'none'. An empty quotes list is a real answer and must be passed through as
    one: a letter with nothing to quote has to say so, not invent something.
    """
    url = (url or "").strip()
    if not url:
        return {"quotes": [], "text": "", "source": "none"}
    hit = _library().get(url)
    if hit and hit.get("quotes"):
        # The library keeps quotes, not the document. Verification needs the
        # document, and the cache has it from the same read -- without this,
        # every library hit looked like an unreadable policy and the letter
        # was told not to quote the very sentences we had just handed it.
        text = hit.get("text") or ""
        if not text:
            p = _key(url)
            if p.exists():
                text = (json.loads(p.read_text()).get("text") or "")
        return {"quotes": hit["quotes"], "text": text, "source": "library"}
    if not allow_fetch:
        return {"quotes": [], "text": "", "source": "none"}
    doc = policy_text(url)
    text = doc.get("text") or ""
    return {"quotes": find_criteria(text, cpt), "text": text,
            "source": "fetch" if text else "none"}


# --- where the appeal actually goes --------------------------------------
_ROUTES: dict | None = None
_NATIONAL: list | None = None
ROUTES_FILE = ROOT / "data" / "policy_platform" / "appeal_submission_routes.json"
NATIONAL_FILE = ROOT / "data" / "policy_platform" / "national_submission_routes.json"


def _national() -> list:
    """The nationals -- UHC, Aetna, Cigna, Anthem, Humana, Centene, Molina --
    exported from the same object the browser uses, so the letter and the page
    cannot drift apart."""
    global _NATIONAL
    if _NATIONAL is None:
        try:
            _NATIONAL = json.loads(NATIONAL_FILE.read_text())["routes"]
        except Exception:  # noqa: BLE001
            _NATIONAL = []
    return _NATIONAL


def _national_match(ins: str) -> dict | None:
    best = None
    for r in _national():
        for t in r.get("match", []):
            if t and t in ins and (best is None or len(t) > best[0]):
                best = (len(t), r)
        groups = r.get("match_all_of")
        if groups and all(any(t in ins for t in g) for g in groups):
            best = best or (0, r)
    return best[1] if best else None


def _routes() -> dict:
    global _ROUTES
    if _ROUTES is None:
        try:
            raw = json.loads(ROUTES_FILE.read_text())["routes"]
        except Exception:  # noqa: BLE001
            raw = []
        _ROUTES = {}
        for r in raw:
            for t in r.get("match", []):
                _ROUTES[t.lower()] = r
    return _ROUTES


def submission_route(payer: str, plan_type: str = "") -> str:
    """One sentence a patient can act on: where this appeal goes.

    Until 2026-09-05 the study's answers carried the literal string
    "per-carrier submission directory" here, so every drafted letter told the
    patient nothing about where to send it. The routes themselves were
    researched from each payer's own site and had been sitting in submit.js the
    whole time.

    A low-confidence route ships only its safe parts. An address is never
    guessed -- the denial letter is always authoritative, and saying so is a
    better answer than a plausible wrong PO box.
    """
    ins = (payer or "").lower().strip()
    table = _routes()
    # Longest matching token wins, so "blue cross of idaho" beats a shorter
    # accidental match -- the same rule the page applies.
    r, best = table.get(ins), 0
    if r is None:
        for k, v in table.items():
            if k and k in ins and len(k) > best:
                r, best = v, len(k)
    if r is None:
        r = _national_match(ins)
    if r is None:
        return ("Use the appeal address printed on your denial letter, or call the "
                "number on the back of your insurance card and ask where member "
                "appeals are filed.")
    bits = []
    if r.get("how") and r.get("confidence") != "low":
        bits.append(r["how"])
    if r.get("portal"):
        bits.append(f"Online: {r['portal']}")
    if r.get("mail") and r.get("confidence") == "high":
        bits.append(f"By mail: {r['mail']}")
    if r.get("fax"):
        bits.append(f"By fax: {r['fax']}")
    bits.append(f"By phone: {r.get('phone') or 'the number on the back of your insurance card'}")
    if r.get("window"):
        bits.append(f"Deadline: {r['window']} -- but your denial letter is authoritative.")
    if r.get("ma_note") and "medicare" in (plan_type or "").lower():
        bits.append(r["ma_note"])
    if not r.get("mail") or r.get("confidence") != "high":
        bits.append("Use the appeal address printed on your denial letter.")
    return " ".join(bits)
