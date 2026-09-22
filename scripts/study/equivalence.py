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
                     r"MCP-?\s?\d{3}|CPB\s?\d{4}|Guideline\s\d{3,4}|CG\s?\d{3}|"
                     # Regence "SUR228", Premera "7.01.551", Excellus "7.01.96"
                     r"(?:SUR|MED|DME|PHA|RAD)\s?\d{3}|\d\.\d{2}\.\d{2,3}|"
                     # HealthPartners serves one policy as an HTML page
                     # (contentid=ENTRY_256055) and as a PDF (entry_256055.pdf).
                     r"ENTRY_\d{5,})"
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


# Who wrote the criteria. A different edition or host of the same publisher's
# guideline is the same governing standard; another publisher's guideline for
# the same operation is a different one, however good it is. On 2026-09-22 an
# independent check (does the cited document contain the reviewed criteria of
# the governing one?) found 17 'equivalent' verdicts where the answer was a
# different publisher: Evolent's guideline for a Centene plan governed by its
# own CP.MP.114, MCG's shoulder criteria for a plan governed by Carelon.
_FAMILIES = {
    "carelon": r"carelon|aim specialty|aimspecialtyhealth|\bAIM\b",
    "evolent": r"evolent|radmd|national imaging associates|\bNIA\b|magellan",
    "evicore": r"evicore|\bCMM-\d{3}",
    "mcg": r"\bMCG\b|milliman",
    "interqual": r"interqual",
    "turningpoint": r"turningpoint",
    "cohere": r"cohere",
    "healthhelp": r"healthhelp",
}


def _path(url: str) -> str:
    u = (url or "").strip().lower().split("#", 1)[0].split("?", 1)[0]
    return u.split("://", 1)[-1].split("/", 1)[-1].rstrip("/") if "/" in u.split("://", 1)[-1] else ""


def _brand(url: str) -> str:
    """The insurer's name as its domain spells it: molinahealthcare.com ->
    'molina', excellusbcbs.com -> 'excellus', blue.regence.com -> 'regence'."""
    host = _host(url)
    parts = [p for p in host.split(".") if p not in ("www", "com", "org", "net", "gov", "us")]
    if not parts:
        return ""
    label = parts[-1]
    # the registrable label is the last non-tld part; peel generic suffixes
    # (molinaclinicalpolicy -> molina, southcarolinablues -> southcarolina)
    changed = True
    while changed:
        changed = False
        for suf in ("healthcare", "health", "bcbs", "bluecross", "blueshield", "blues",
                    "plan", "plans", "online", "clinicalpolicy", "clinical", "policy", "provider"):
            if label.endswith(suf) and len(label) > len(suf) + 4:
                label = label[: -len(suf)]
                changed = True
    return label if len(label) >= 5 else ""


def _family(url: str, title: str, text: str, vendor_hint: str = "") -> str:
    """The publisher family of a document, from its URL, title, the first
    pages of its text, and (for the answer key) the vendor the directory
    recorded. Empty when nothing names one -- then the insurer's own host
    is the family."""
    hay = " ".join([url or "", title or "", (text or "")[:4000], vendor_hint or ""])
    for fam, rx in _FAMILIES.items():
        if re.search(rx, hay, re.I):
            return fam
    return ""


def compare(cited_url: str, gold_url: str, cpt: str,
            gold_title: str = "", allow_fetch: bool = True,
            cited_title: str = "", gold_vendor: str = "") -> dict:
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
    # Regence's sur228.pdf answers with a 302 to a Bynder-hosted file; a
    # citation of either address is the same document.
    if gold_url:
        fg = (policy_text(gold_url).get("final_url") or "") if allow_fetch else ""
        fc = (policy_text(cited_url).get("final_url") or "") if allow_fetch else ""
        if fg and _normalize_url(cited_url) == _normalize_url(fg):
            return {"verdict": "exact", "why": "same document, the address it redirects to"}
        if fc and _normalize_url(fc) == _normalize_url(gold_url):
            return {"verdict": "exact", "why": "same document, an address that redirects to it"}

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
        # Whose guideline is it? The answer key's publisher comes from the
        # directory's vendor field, its URL and its title -- not its text,
        # where an insurer's own policy mentions the vendor whose criteria it
        # applies. The cited document's publisher comes from its URL, its
        # title, and its first page, where a hosted copy names its author
        # ("Carelon Clinical Appropriateness Guidelines" on an Anthem PDF).
        fam_gold = _family(gold_url, gold_title, "", gold_vendor)
        fam_cited = _family(cited_url, cited_title, text[:1500])
        if fam_gold:
            if fam_cited == fam_gold:
                return {"verdict": "equivalent", "family": fam_gold,
                        "why": "names the code and states criteria, same publisher",
                        "criteria_found": len(quotes)}
            return {"verdict": "different_document",
                    "why": (f"another publisher's guideline ({fam_cited}) " if fam_cited
                            else "not the governing publisher's guideline ") +
                           f"for a plan governed by {fam_gold}'s"}
        # The insurer's own policy governs: another copy of it lives on the
        # insurer's own site (Molina's policies mention MCG on their first
        # page and are still Molina's), at the same path on a sister host
        # (a member portal mirroring the provider site), or on a site that
        # names the insurer. A vendor's guideline, or another insurer's page,
        # is a different document.
        # the same policy page under a sister brand keeps its tail path:
        # .../medicalpolicy/external-policies/total-ankle-replacement on the
        # provider site, .../medicalpolicyhb/external-policies/total-ankle-
        # replacement on the member portal
        tail = lambda u: "/".join(_path(u).split("/")[-2:])  # noqa: E731
        same_path = bool(gold_url) and _path(gold_url) and (
            _path(cited_url) == _path(gold_url) or
            (len(tail(gold_url)) > 15 and tail(cited_url) == tail(gold_url)))
        brand = _brand(gold_url)
        names_insurer = bool(brand) and brand in " ".join([cited_url, cited_title or "", text[:1500]]).lower()
        if same_host or same_path or names_insurer:
            return {"verdict": "equivalent", "family": "insurer",
                    "why": "names the code and states criteria, same insurer's site",
                    "criteria_found": len(quotes)}
        return {"verdict": "different_document",
                "why": (f"{fam_cited}'s guideline" if fam_cited else "another site's document")
                       + ", but this plan's own policy governs"}
    if names_cpt:
        return {"verdict": "different_document",
                "why": "names the code but states no criteria for it"}
    return {"verdict": "different_document", "why": "does not name the denied code"}
