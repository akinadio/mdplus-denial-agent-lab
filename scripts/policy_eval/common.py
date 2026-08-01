#!/usr/bin/env python3
"""Shared primitives for the policy-retrieval eval harness (rubric v1.5).

Nothing in this module reads the answer key on behalf of the retrieval model.
The key loader here is used only by the query emitter, the graders and the
report writer, all of which run on the harness side of the isolation boundary.
"""

from __future__ import annotations

import hashlib
import html as _html
import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
KEY_PATH = REPO_ROOT / "data" / "policy_platform" / "answer_key_v1.json"
RUBRIC_PATH = (
    REPO_ROOT
    / "docs"
    / "goals"
    / "policy-retrieval-eval"
    / "notes"
    / "scoring-rubric-v1.md"
)
RUNS_DIR = REPO_ROOT / "runs"

def _read_rubric_version() -> str:
    # Hardcoding this drifted once: the rubric moved to 1.4 while three modules
    # still stamped 1.3 into run artifacts, mislabelling the very artifact that
    # exists to make a post-hoc rubric edit detectable.
    m = re.search(
        r"^`rubric_version:\s*([0-9]+\.[0-9]+)`",
        RUBRIC_PATH.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not m:
        raise RuntimeError(f"cannot parse rubric_version from {RUBRIC_PATH}")
    return m.group(1)


RUBRIC_VERSION = _read_rubric_version()

# Rubric section 2 Tier 1: strip query parameters EXCEPT semantically required
# ones. The rubric names LCDId, ncdid and policyId. articleId is included here
# under the same principle and is recorded as a deviation in the harness note:
# every CMS Billing and Coding Article URL differs ONLY by articleId, so
# stripping it would normalise A56796 and A59811 to the same string and would
# manufacture false CORRECT grades on exactly the rows this benchmark exists to
# test. `ver` is kept for the same reason (it selects a document version).
SEMANTIC_QUERY_PARAMS = {"lcdid", "ncdid", "policyid", "articleid", "ver"}

LOGIN_PATH_RE = re.compile(r"/(login|signin|sign-in|idp|auth)\b", re.IGNORECASE)
SIGNIN_FORM_RE = re.compile(
    r"(<form[^>]*(login|signin|sign-in)|name=[\"']password[\"']"
    r"|type=[\"']password[\"']|please\s+sign\s+in|log\s?in\s+to\s+continue)",
    re.IGNORECASE,
)

# Bot-mitigation fingerprints. Kept deliberately separate from the login-wall
# patterns above. See detect_bot_block for why the two must never merge.
BOT_BLOCK_MARKERS: tuple[tuple[str, str], ...] = (
    (r"incapsula\s+incident\s+id", "imperva_incapsula_incident_id"),
    (r"_incapsula_resource", "imperva_incapsula_resource"),
    (r"request\s+unsuccessful", "request_unsuccessful_stub"),
    (r"attention\s+required!\s*\|\s*cloudflare", "cloudflare_attention_required"),
    (r"cf-browser-verification", "cloudflare_browser_verification"),
    (r"__cf_chl", "cloudflare_challenge"),
    (r"just\s+a\s+moment\.\.\.", "cloudflare_just_a_moment"),
    (r"px-captcha", "perimeterx_captcha"),
    (r"datadome", "datadome"),
    (r"errors\.edgesuite\.net", "akamai_edgesuite_error"),
)
BOT_BLOCK_RE = re.compile(
    "|".join(f"(?P<m{i}>{pat})" for i, (pat, _) in enumerate(BOT_BLOCK_MARKERS)),
    re.IGNORECASE,
)
# The generic rule below fires on a thin HTTP 200. A stub that carries no
# marker we know still gives itself away by being an HTTP 200 with almost no
# readable text and no sign of the code this benchmark is about.
THIN_200_TEXT_CHARS = 512


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def load_key(path: Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or KEY_PATH).read_text())


def key_sha256(path: Path | None = None) -> str:
    return file_sha256(Path(path or KEY_PATH))


def rubric_sha256(path: Path | None = None) -> str:
    return file_sha256(Path(path or RUBRIC_PATH))


def exact_binomial_upper_bound(n: int, alpha: float = 0.05) -> float:
    """95% one-sided upper bound on a rate given ZERO observed events.

    Rubric section 0.1: 1 - 0.05 ** (1 / N). The 3/N rule-of-three shorthand is
    forbidden anywhere in this harness because it overstates every bound.
    """
    if n <= 0:
        raise ValueError("N must be positive")
    return 1.0 - alpha ** (1.0 / n)


def format_bound(n: int) -> str:
    return f"{exact_binomial_upper_bound(n) * 100:.1f}%"


def normalize_url(url: str | None) -> str | None:
    """Rubric section 2 Tier 1 normalisation.

    Lowercase host, strip `www.`, strip scheme difference, strip fragment,
    strip trailing slash, strip query parameters except semantically required
    ones.
    """
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if not u:
        return None
    if "//" not in u:
        u = "//" + u
    parts = urlsplit(u if "://" in u else "http:" + u)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path or ""
    while path.endswith("/") and len(path) > 1:
        path = path[:-1]
    if path == "/":
        path = ""
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() in SEMANTIC_QUERY_PARAMS
    ]
    kept.sort(key=lambda kv: kv[0].lower())
    kept = [(k.lower(), v) for k, v in kept]
    q = urlencode(kept)
    out = host + path
    if q:
        out += "?" + q
    return out


def url_host(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if "://" not in u:
        u = "http://" + u
    host = (urlsplit(u).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


_STRIP_HTML_MAX_PASSES = 4


def strip_html(html: str) -> str:
    """Return the readable text of an HTML document.

    ORDER MATTERS AND WAS WRONG UNTIL T018. The previous implementation stripped
    tags first and unescaped entities second, so a page that delivers policy
    prose as escaped markup inside a JSON payload leaked a literal tag into the
    text the retrieval model reads: `(&lt;abbr&gt;NCD&lt;/abbr&gt;)` came back
    as `(<abbr>NCD</abbr>)`. Entities are now unescaped BEFORE tags are removed,
    and the pair is repeated until the text stops changing so doubly escaped
    markup also resolves. The pass count is capped so a pathological input
    cannot spin.

    THE TAG PATTERN MUST BE TAG SHAPED, T020. The removal pattern used to be
    `<[^>]+>`, which matches any run from a bare `<` to the next `>` no matter
    what lies between. The Carelon Joint Surgery guideline is a PDF whose
    extracted text carries ten `<` and eight `>` characters in its imaging
    tables, for example `Alpha angle < 55° Normal` and `< 32° Insignificant 39°
    - 42° Borderline >`. The old pattern therefore deleted 167,471 of the
    241,279 extracted characters, including the region at offset 154,826 that
    holds CPT 27447 and its total knee arthroplasty descriptor. Every match run
    through normalize_for_match then reported that document as NOT containing
    27447 while it plainly does, with no error anywhere. That is the fifth false
    absence on this board and, like the other four, it points the flattering
    way: a row whose attestation cannot be confirmed leaves the scored set and
    enlarges the abstention pool that the headline metric rewards. The pattern
    now requires a real tag opening and forbids a further `<` inside the tag,
    so a stray angle bracket in prose can only ever consume prose up to the next
    angle bracket, never across one.
    """
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    for _ in range(_STRIP_HTML_MAX_PASSES):
        before = text
        text = _html.unescape(text)
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?s)<!--.*?-->", " ", text)
        text = re.sub(r"(?s)</?[A-Za-z!?][^<>]*>", " ", text)
        if text == before:
            break
    return re.sub(r"\s+", " ", text).strip()


_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_for_match(s: str | None) -> str:
    """Fold a string to the form used for every identity and attestation check.

    A raw substring test on live payer HTML manufactures phantoms. On the BCBS
    North Carolina page a recorded 325-character quote tested NOT PRESENT while
    being present and unchanged, because the page wraps three abbreviations in
    markup and serves that region as escaped markup inside JSON. This function
    unescapes entities, removes tags, folds case, folds every punctuation mark
    and every kind of quote or dash to a space, and collapses whitespace.
    """
    if not s:
        return ""
    text = strip_html(s)
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    text = _PUNCT_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalized_contains(haystack: str | None, needle: str | None) -> bool:
    """True when `needle` appears in `haystack` under normalize_for_match.

    Every identity check the key relies on must run through this, so that the
    check recorded in the key and the check run by the harness cannot diverge.
    """
    n = normalize_for_match(needle)
    if not n:
        return False
    return n in normalize_for_match(haystack)


class ExtractionError(RuntimeError):
    """Raised when a document could not be read at all.

    This must be distinct from "the document was read and contained no matching
    text": a swallowed parse/import failure that returns "" reads downstream as
    'the policy is not here', which is exactly the confidently-wrong absence the
    eval exists to prevent. Callers turn this into a `blocked` fetch, not empty
    page text.
    """


def pdf_text(data: bytes) -> str:
    """Extract text from a PDF. Returns "" only when the PDF genuinely has no
    extractable text; raises ExtractionError when extraction itself failed."""
    try:
        import io

        from pypdf import PdfReader
    except Exception as exc:  # noqa: BLE001 - pypdf missing is an extraction failure
        raise ExtractionError(f"pdf_reader_unavailable:{type(exc).__name__}") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        return re.sub(
            r"\s+", " ", " ".join((p.extract_text() or "") for p in reader.pages)
        )
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"pdf_parse_failed:{type(exc).__name__}") from exc


def extract_text(data: bytes, content_type: str | None) -> str:
    ct = (content_type or "").lower()
    if "pdf" in ct or data[:5] == b"%PDF-":
        return pdf_text(data)
    try:
        raw = data.decode("utf-8", errors="replace")
    except Exception:
        return ""
    if "html" in ct or "<html" in raw[:4000].lower():
        return strip_html(raw)
    return re.sub(r"\s+", " ", raw).strip()


def contains_cpt_27447(text: str) -> bool:
    return bool(re.search(r"\b27447\b", text or ""))


def detect_login_wall(
    status: int | None, final_url: str | None, redirect_chain: list[str], body_text: str
) -> tuple[bool, str | None]:
    if status in (401, 403):
        return True, f"http_{status}"
    for u in list(redirect_chain) + ([final_url] if final_url else []):
        if u and LOGIN_PATH_RE.search(urlsplit(u).path or ""):
            return True, f"redirect_to_login:{u}"
    head = (body_text or "")[:20000]
    if SIGNIN_FORM_RE.search(head):
        return True, "signin_form_in_body"
    return False, None


def detect_bot_block(
    status: int | None,
    headers: dict[str, Any] | None,
    body_text: str,
    byte_len: int | None = None,
) -> tuple[bool, str | None]:
    """Detect bot mitigation that answers a non-browser request with HTTP 200.

    THIS IS NOT A LOGIN WALL AND MUST NEVER BE MERGED WITH ONE. A login wall is
    a true property of the payer: that payer really does put its policy behind
    credentials, and the row belongs in the gated class. A bot block is an
    artefact of our own request shape: the document may be fully public and we
    simply were not allowed to read it. A bot block must therefore NEVER produce
    a row class, and a blocked fetch must never be scored as model behaviour.

    Why this exists. One recorded payer host, www.horizonblue.com, answers a
    non-browser request with HTTP 200 and a stub of about 930 bytes whose whole
    visible text is `Request unsuccessful. Incapsula incident ID: ...`. Run
    against that stub, detect_login_wall returns (False, None), so before this
    function the harness could not tell a blocked fetch from a successful one.
    The direction of that blindness is not neutral: a blocked fetch makes the
    retrieval model abstain, and abstention is what the headline metric rewards,
    so we would have scored our own network conditions as model caution.

    `body_text` may be the raw decoded body or already-extracted text. Markers
    are searched in whatever is passed, because several fingerprints live in
    script or meta content that text extraction removes.
    """
    hdrs = {str(k).lower(): v for k, v in (headers or {}).items()}
    content_type = str(hdrs.get("content-type") or "").lower()
    body = body_text or ""

    m = BOT_BLOCK_RE.search(body[:200000])
    if m and m.lastgroup:
        idx = int(m.lastgroup[1:])
        return True, BOT_BLOCK_MARKERS[idx][1]

    server = str(hdrs.get("server") or "").lower()
    if status == 200 and ("incapsula" in server or "datadome" in server):
        return True, f"bot_mitigation_server_header:{server}"

    # Generic rule: an HTTP 200 that carries almost no readable text and no sign
    # of CPT 27447 is not a policy page. PDFs are exempt because a short PDF
    # text extraction is a parser failure, not a block, and calling it a block
    # would move the row out of the scored denominator, which is the flattering
    # direction.
    if status == 200 and "pdf" not in content_type:
        stripped = strip_html(body) if "<" in body else re.sub(r"\s+", " ", body).strip()
        if len(stripped) < THIN_200_TEXT_CHARS and not contains_cpt_27447(stripped):
            return True, (
                f"thin_200_response:{len(stripped)}_text_chars"
                f"_of_{byte_len if byte_len is not None else len(body)}_bytes"
            )
    return False, None


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    with Path(path).open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
