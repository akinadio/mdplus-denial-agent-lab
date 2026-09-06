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
        return json.loads(p.read_text())
    from policy_eval.webtools import fetch
    try:
        r = fetch(url, max_text_chars=120000)
        out = {"url": url, "final_url": r.get("final_url"), "status": r.get("status"),
               "text": r.get("text") or "", "error": r.get("error") or ""}
    except Exception as exc:  # noqa: BLE001
        out = {"url": url, "text": "", "error": f"{type(exc).__name__}: {exc}"}
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out))
    return out


def find_criteria(text: str, cpt: str = "", limit: int = 12) -> list[str]:
    """Pull candidate criteria sentences out of a policy document.

    Deliberately dumb and verbatim: it selects, it never paraphrases. Anything
    it returns can be checked against the document character for character,
    which is the property that matters. Passages near the CPT code come first.
    """
    if not text:
        return []
    text = re.sub(r"[ \t]+", " ", text)
    chunks = [c.strip() for c in re.split(r"(?<=[.;:])\s+|\n{2,}", text) if c.strip()]
    hits, near = [], []
    for i, c in enumerate(chunks):
        if len(c) < 40 or len(c) > 600 or _NOISE.match(c):
            continue
        if not _CRITERIA_CUES.search(c):
            continue
        window = " ".join(chunks[max(0, i - 3):i + 4])
        (near if cpt and cpt in window else hits).append(c)
    seen, out = set(), []
    for c in near + hits:
        k = c[:80].lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
        if len(out) >= limit:
            break
    return out


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
        return {"quotes": hit["quotes"], "text": hit.get("text", ""), "source": "library"}
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
