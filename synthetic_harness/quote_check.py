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
from synthetic_harness.policy_text import policy_text, verify_quote  # noqa: E402

# Block quotes (markdown "> ") and anything inside double or curly quotes long
# enough to be a claim rather than a phrase.
_BLOCK = re.compile(r"^\s*>\s?(.+)$", re.M)
_INLINE = re.compile(r"[\"“]([^\"”]{40,600})[\"”]")


def quoted_passages(letter: str) -> list[str]:
    out, seen = [], set()
    block = [m.strip() for m in _BLOCK.findall(letter or "")]
    if block:                      # consecutive "> " lines are one quotation
        merged, buf = [], []
        for line in block:
            buf.append(line)
        merged.append(" ".join(buf))
        out.extend(merged)
    out.extend(m.strip() for m in _INLINE.findall(letter or ""))
    keep = []
    for q in out:
        k = re.sub(r"\s+", " ", q)[:80].lower()
        if len(q) < 40 or k in seen:
            continue
        seen.add(k)
        keep.append(q)
    return keep


def check(letter: str, policy_url: str) -> dict:
    """Return what the letter quoted, and whether the document contains it."""
    quotes = quoted_passages(letter)
    if not quotes:
        return {"quotes": 0, "unverifiable": 0, "not_in_policy": 0,
                "verified": 0, "examples": [], "checked": True}
    doc = policy_text(policy_url) if policy_url else {"text": ""}
    text = doc.get("text") or ""
    if not text:
        # No document to check against: the letter quoted something we cannot
        # verify. That is not the same as an invented quote, and is not counted
        # as one.
        return {"quotes": len(quotes), "unverifiable": len(quotes),
                "not_in_policy": 0, "verified": 0,
                "examples": [q[:160] for q in quotes[:3]], "checked": False,
                "why": doc.get("error") or "no policy text available"}
    bad = [q for q in quotes if not verify_quote(q, text)]
    return {"quotes": len(quotes), "unverifiable": 0, "not_in_policy": len(bad),
            "verified": len(quotes) - len(bad),
            "examples": [q[:160] for q in bad[:3]], "checked": True}
