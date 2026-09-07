"""Check every quotation in a letter against the policy document itself.

"Appeal-fatal error" was one label covering an invented quotation, a letter
posted to the wrong insurer, and an unfinished template. Those are different
defects with different causes and different fixes, and a reviewer treats them
differently, so they are counted separately now.

The quotation check in particular does not need a judge. A quote is either in
the document or it is not, and that is a string comparison against the text we
fetched. This module does that, so the model-graded rubric is left to judge
only the things that genuinely need judgment.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synthetic_harness.policy_text import policy_text  # noqa: E402

# Block quotes (markdown "> ") and anything inside double or curly quotes long
# enough to be a claim rather than a phrase.
_BLOCK = re.compile(r"^\s*>\s?(.+)$", re.M)
# One line, starts with a letter: a stray quote mark two paragraphs before a
# markdown **Member:** line is not a quotation, and was being counted as one.
_INLINE = re.compile(r"[\"“]([A-Za-z][^\"”\n]{39,600})[\"”]")


def _norm(t: str) -> str:
    """Letters and digits only, single-spaced. A quotation with a period the
    document does not have, or a curly quote, or a line break, is still the
    document's sentence."""
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _blocks(letter: str) -> list[str]:
    """Each run of consecutive '> ' lines is ONE quotation. Joining every
    block line in the letter into a single string turned three separate
    quotations into one that matched nothing, and flagged 19 honest letters."""
    out, cur = [], []
    for line in (letter or "").splitlines():
        m = _BLOCK.match(line)
        if m and m.group(1).strip():
            cur.append(m.group(1).strip())
        elif cur:
            out.append(" ".join(cur)); cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def quoted_passages(letter: str) -> list[str]:
    out, seen = [], set()
    for b in _blocks(letter):
        for piece in re.split(r"[\"”]\s+[\"“]", b):
            out.append(piece.strip(" \"“”"))
    for m in _INLINE.findall(letter or ""):
        # '"A." "B."' captured as one span: split on the quote-space-quote seam
        # and drop any quote marks the capture swallowed.
        for piece in re.split(r"[\"”]\s+[\"“]", m):
            out.append(piece.strip(" \"“”"))
    keep = []
    for q in out:
        k = _norm(q)[:80]
        if len(q) < 40 or k in seen or "\n" in q.strip() or q.lstrip().startswith(("*", "#", "[")):
            continue
        seen.add(k)
        keep.append(q)
    return keep


def in_text(quote: str, text: str) -> bool:
    """Every piece of the quotation is in the text. An ellipsis inside a
    quotation is honest abbreviation, so the pieces are checked separately."""
    nt = _norm(text)
    pieces = [pc for pc in re.split(r"\.\.\.|…|\[\.\.\.\]", quote or "") if _norm(pc)]
    if not pieces:
        return False
    if len(pieces) == 1:
        q = _norm(pieces[0]); return len(q) > 25 and q in nt
    return all(_norm(pc) in nt for pc in pieces if len(_norm(pc)) > 12)


def check(letter: str, policy_url: str, other_sources: list[str] | None = None) -> dict:
    """What the letter quoted, and whether the document contains it.

    `other_sources` are texts the letter may legitimately quote that are not
    the policy -- the denial notice, the patient's records. A letter that
    quotes the denial's own words back at the reviewer has not invented
    anything, and was being counted as though it had."""
    quotes = quoted_passages(letter)
    others = [t for t in (other_sources or []) if t]
    from_other = [q for q in quotes if any(in_text(q, t) for t in others)]
    quotes = [q for q in quotes if q not in from_other]
    base = {"from_other_sources": len(from_other)}
    if not quotes:
        return {**base, "quotes": 0, "unverifiable": 0, "not_in_policy": 0,
                "verified": 0, "examples": [], "checked": True}
    doc = policy_text(policy_url) if policy_url else {"text": ""}
    text = doc.get("text") or ""
    if not text:
        return {**base, "quotes": len(quotes), "unverifiable": len(quotes),
                "not_in_policy": 0, "verified": 0,
                "examples": [q[:160] for q in quotes[:3]], "checked": False,
                "why": doc.get("error") or "no policy text available"}
    bad = [q for q in quotes if not in_text(q, text)]
    return {**base, "quotes": len(quotes), "unverifiable": 0, "not_in_policy": len(bad),
            "verified": len(quotes) - len(bad),
            "examples": [q[:160] for q in bad[:3]], "checked": True}
