"""Is a cited document an acceptable answer, even if it is not the gold URL?

Exact URL matching made the first pilot's numbers meaningless in both
directions. It marked OrthoAppeals 100% -- gold came out of the same CSV the
tool reads, so it could not miss -- and it marked ChatGPT wrong for citing
Carelon's HTML edition of the guideline our gold had as a PDF, or Centene's
North Carolina copy of CP.MP.114 on a North Carolina case, or a newer version
of the same eviCore guideline. Those are the right document.

An answer is accepted when the document it points at is the payer's own, names
the denied code, and states criteria. That is checkable against the document
rather than against our spreadsheet, which is also what breaks the circularity
on our own arm: the tool now has to be right about the world, not merely
consistent with the file it read.

Verdicts: 'exact', 'equivalent', 'different_document', 'unreadable'.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from synthetic_harness.policy_text import policy_text, find_criteria  # noqa: E402
from synthetic_harness.citation_cache import _normalize_url  # noqa: E402

# A guideline's identity travels in its number, not its filename or its year.
# NOT \b at the start: underscore is a word character, so "Cigna_CMM-314" has
# no boundary before CMM and \b silently misses every eviCore filename.
_DOCNUM = re.compile(r"(?<![A-Za-z0-9])(CMM-\d{3}|CP\.MP\.\d+|MMP\d+(?:\.\d+)?|"
                     r"20\d\dT\d{4}[A-Z]{0,2}|[A-Z]{2,4}\.[A-Z]{2}\.\d+|"
                     # Molina writes MCP-404 / MCP 404 / "Clinical Policy No. 404";
                     # Aetna writes CPB 0660; eviCore and Carelon write
                     # "Guideline 1764". Without these the number never matched
                     # and three Molina answers naming MCP-404 exactly were
                     # scored as the wrong document.
                     r"MCP-?\s?\d{3}|CPB\s?\d{4}|Guideline\s\d{3,4})"
                     r"(?![A-Za-z0-9])", re.I)


def _norm_id(t: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (t or "").upper())


def _ids(*texts: str) -> set[str]:
    """Guideline numbers, normalised so MCP-404, MCP 404 and MCP404 are one id."""
    out = set()
    for t in texts:
        out |= {_norm_id(m.group(1)) for m in _DOCNUM.finditer(t or "")}
    return out


def _host(u: str) -> str:
    try:
        return (urlparse(u).netloc or "").lower().replace("www.", "")
    except Exception:  # noqa: BLE001
        return ""


def compare(cited_url: str, gold_url: str, cpt: str,
            gold_title: str = "", allow_fetch: bool = True,
            cited_title: str = "") -> dict:
    """`cited_title` matters as much as the URL.

    Until 2026-09-20 only the cited URL was inspected, and the guideline-number
    match additionally required the same web host. Both were wrong, and both
    ran against the chatbots. A plan's policy number identifies the policy
    wherever it is hosted: Centene publishes CP.MP.114 on each subsidiary's
    site, so a North Carolina case answered with Carolina Complete Health's
    copy is the SAME document, not a different one. And three answers naming
    "Molina Clinical Policy MCP-404 Shoulder Arthroscopy" in the title were
    scored wrong because the number appeared only in the title, which was never
    read. Nine of nineteen wrong-document verdicts were of this kind.
    """
    cited_url = (cited_url or "").strip()
    if not cited_url:
        return {"verdict": "different_document", "why": "no url cited"}
    if gold_url and _normalize_url(cited_url) == _normalize_url(gold_url):
        return {"verdict": "exact", "why": "same url"}

    # Same document number on the same payer's host is the same guideline in a
    # different edition or format.
    ids_gold = _ids(gold_url, gold_title)
    ids_cited = _ids(cited_url, cited_title)
    same_host = bool(gold_url) and _host(cited_url) == _host(gold_url)
    if ids_gold and ids_cited & ids_gold:
        return {"verdict": "equivalent", "shared_id": sorted(ids_cited & ids_gold),
                "why": "same guideline number, same policy in another edition or "
                       "on a sister plan's site"}

    if not allow_fetch:
        return {"verdict": "different_document", "why": "not checked"}

    doc = policy_text(cited_url)
    text = doc.get("text") or ""
    if not text:
        return {"verdict": "unreadable", "why": doc.get("error") or "no text"}
    names_cpt = bool(cpt) and cpt in text
    quotes = find_criteria(text, cpt)
    ids_doc = _ids(text[:6000])
    if ids_gold and ids_doc & ids_gold:
        return {"verdict": "equivalent", "shared_id": sorted(ids_doc & ids_gold),
                "why": "document carries the same guideline number"}
    if names_cpt and quotes:
        return {"verdict": "equivalent", "why": "names the code and states criteria",
                "criteria_found": len(quotes)}
    if names_cpt:
        return {"verdict": "different_document",
                "why": "names the code but states no criteria for it"}
    return {"verdict": "different_document", "why": "does not name the denied code"}
