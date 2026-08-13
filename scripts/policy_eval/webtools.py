#!/usr/bin/env python3
"""The only two capabilities the retrieval model is given: search and fetch.

SECRET HANDLING. The Brave Search subscription token is read from the
environment variable WEB_SEARCH_API_KEY at call time. It is never logged, never
written to a run artifact, never written to an MCP config file and never
returned to the model. Artifacts record only `search_backend: "Brave Search API"`
and the result count.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from policy_eval.common import (  # noqa: E402
    ExtractionError,
    contains_cpt_27447,
    detect_bot_block,
    detect_login_wall,
    extract_text,
    sha256_bytes,
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
def _decodable_encodings() -> str:
    """Advertise ONLY the content encodings this interpreter can actually decode.

    NEAR MISS, T018, worth stating plainly because it is the exact failure this
    whole task exists to remove. The first version of this header set claimed
    `gzip, deflate, br`. Brotli is not installed here, so one payer CDN switched
    to a brotli variant and `requests` handed back 13 KB of still-compressed
    bytes at HTTP 200. Text extraction then produced mojibake, the recorded
    attestation quote was not found, CPT 27447 was not found, and nothing
    anywhere reported an error. The retrieval model would have abstained on a
    page it was never shown, and abstention is what the headline metric rewards.
    Claiming an encoding we cannot decode is therefore forbidden.
    """
    encodings = ["gzip", "deflate"]
    try:  # pragma: no cover - depends on the installed extras
        import brotli  # noqa: F401

        encodings.append("br")
    except ImportError:
        try:  # pragma: no cover
            import brotlicffi  # noqa: F401

            encodings.append("br")
        except ImportError:
            pass
    try:  # pragma: no cover
        import zstandard  # noqa: F401

        encodings.append("zstd")
    except ImportError:
        pass
    return ", ".join(encodings)


ACCEPT_ENCODING = _decodable_encodings()
DECODABLE_ENCODINGS = frozenset(
    e.strip() for e in ACCEPT_ENCODING.split(",")
) | {"identity", ""}

# A user agent alone is not enough. One recorded payer host answers a request
# that carries only a browser user agent with the same HTTP 200 bot stub it
# gives bare curl, and answers the full header set with the real 53 KB page.
# These are the headers a real Chrome navigation sends.
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": ACCEPT_ENCODING,
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Connection": "keep-alive",
}
FETCH_TIMEOUT = 30
SEARCH_BACKEND = "Brave Search API"
SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

# A persistent session, so cookies a bot-mitigation edge sets on the first
# response are carried on the next one, exactly as a browser would carry them.
_SESSION: requests.Session | None = None


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        s.headers.update(BROWSER_HEADERS)
        _SESSION = s
    return _SESSION


class SearchUnavailable(RuntimeError):
    pass


def search(query: str, count: int = 5) -> dict[str, Any]:
    """Web search via the Brave Search API. Returns title/url/snippet triples."""
    token = os.environ.get("WEB_SEARCH_API_KEY")
    if not token:
        raise SearchUnavailable(
            "WEB_SEARCH_API_KEY is not set. Refusing to run: a harness with no "
            "search path measures the network, not the model."
        )
    resp = requests.get(
        SEARCH_ENDPOINT,
        params={"q": query, "count": max(1, min(int(count), 20))},
        headers={
            "X-Subscription-Token": token,
            "Accept": "application/json",
            # Brave now rejects the request with 422 ("Input should be
            # 'no-cache'") if this header is absent -- a requirement added
            # after this integration was first written. Documented in a
            # since-locked upstream bug (Brave community thread, March 2026)
            # and confirmed against this account: same key, active
            # subscription, every call still 422'd until this was added.
            "Cache-Control": "no-cache",
        },
        timeout=FETCH_TIMEOUT,
    )
    if resp.status_code != 200:
        return {
            "backend": SEARCH_BACKEND,
            "query": query,
            "http_status": resp.status_code,
            "result_count": 0,
            "results": [],
            "error": f"search backend returned HTTP {resp.status_code}: {resp.text[:300]}",
        }
    data = resp.json()
    results = []
    for r in (data.get("web") or {}).get("results", []):
        results.append(
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "snippet": r.get("description"),
            }
        )
    return {
        "backend": SEARCH_BACKEND,
        "query": query,
        "http_status": 200,
        "result_count": len(results),
        "results": results,
        "error": None,
    }


BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"}


def _blocked_reason(url: str) -> str | None:
    """Second line of defence on the isolation boundary.

    `http_fetch` is one of only two capabilities the retrieval model has, so it
    must not become a file reader or a way onto this host's loopback interface.
    """
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        return f"only http and https URLs are allowed, got scheme {parts.scheme!r}"
    host = (parts.hostname or "").lower()
    if not host:
        return "URL has no host"
    if host in BLOCKED_HOSTS or host.endswith(".local"):
        return "loopback and link-local hosts are not fetchable"
    if host.startswith(("10.", "192.168.", "169.254.")) or any(
        host.startswith(f"172.{n}.") for n in range(16, 32)
    ):
        return "private-network hosts are not fetchable"
    return None


def fetch(url: str, max_text_chars: int = 20000) -> dict[str, Any]:
    """Perform a REAL HTTP GET and record the observed facts.

    Adapted from scripts/run_policy_retrieval.py fetch() at L112-135 (the one
    reuse the T004 card permits for HTTP evidence capture), extended with the
    redirect chain, final URL, extracted text, login-wall detection, CPT-27447
    presence and host-resolution evidence that rubric section 6 Stage A needs.

    Every returned record carries `blocked` and `blocked_reason`. `blocked` says
    that WE were refused, which is an artefact of our request shape and must
    never become a row class. `login_wall` says the PAYER demands credentials,
    which is a true property of the payer. The two are computed separately and
    are never merged.
    """
    blocked = _blocked_reason(url)
    if blocked:
        return {
            "url": url,
            "final_url": None,
            "status": None,
            "redirect_chain": [],
            "content_type": None,
            "bytes": 0,
            "sha256": None,
            "text": "",
            "text_truncated": False,
            "contains_cpt_27447": False,
            "login_wall": False,
            "login_wall_reason": None,
            "blocked": False,
            "blocked_reason": None,
            "host": (urlsplit(url).hostname or "").lower() or None,
            "host_resolves": None,
            "error": f"blocked by harness: {blocked}",
        }
    host = (urlsplit(url).hostname or "").lower()
    host_resolves = None
    if host:
        try:
            socket.getaddrinfo(host, None)
            host_resolves = True
        except socket.gaierror:
            host_resolves = False

    if host_resolves is False:
        return {
            "url": url,
            "final_url": None,
            "status": None,
            "redirect_chain": [],
            "content_type": None,
            "bytes": 0,
            "sha256": None,
            "text": "",
            "text_truncated": False,
            "contains_cpt_27447": False,
            "login_wall": False,
            "login_wall_reason": None,
            "blocked": False,
            "blocked_reason": None,
            "host": host,
            "host_resolves": False,
            "error": f"DNS resolution failed for host {host!r}",
        }

    try:
        resp = _session().get(
            url,
            timeout=FETCH_TIMEOUT,
            headers=BROWSER_HEADERS,
            allow_redirects=True,
        )
        body = resp.content
        content_type = resp.headers.get("content-type")
        extraction_error = None
        try:
            text = extract_text(body, content_type)
        except ExtractionError as exc:
            # The document could not be read at all. Never let that fall through
            # as empty page text (which reads as "no policy here"); it is a
            # blocked fetch, recorded below.
            text = ""
            extraction_error = str(exc)
        chain = [h.headers.get("location") or h.url for h in resp.history]
        login, login_reason = detect_login_wall(
            resp.status_code, resp.url, chain, text
        )
        # The bot-block probe reads the RAW body, not the extracted text,
        # because several fingerprints live in script or meta content that
        # text extraction removes.
        if "pdf" in (content_type or "").lower() or body[:5] == b"%PDF-":
            probe = text
        else:
            probe = body[:200000].decode("utf-8", errors="replace")
        is_blocked, blocked_reason = detect_bot_block(
            resp.status_code, dict(resp.headers), probe, len(body)
        )
        # Belt and braces for the brotli near miss described above. We never ask
        # for an encoding we cannot decode, so a body that still arrives in one
        # is a server ignoring Accept-Encoding. Record it as a blocked fetch,
        # which is our artefact and never a row class, rather than let unreadable
        # bytes be scored as a page the model failed to read.
        enc = (resp.headers.get("content-encoding") or "").lower().strip()
        if not is_blocked and enc and enc not in DECODABLE_ENCODINGS:
            is_blocked, blocked_reason = True, f"undecodable_content_encoding:{enc}"
        # A read failure (e.g. an unparseable PDF) is our inability to read the
        # document, not evidence the policy is absent. Record it as blocked so it
        # can never be scored as a page the model read and found nothing in.
        if not is_blocked and extraction_error:
            is_blocked, blocked_reason = True, f"extraction_failed:{extraction_error}"
        return {
            "url": url,
            "final_url": resp.url,
            "status": resp.status_code,
            "redirect_chain": chain,
            "content_type": content_type,
            "bytes": len(body),
            "sha256": sha256_bytes(body),
            "text": text[:max_text_chars],
            "text_len": len(text),
            "text_truncated": len(text) > max_text_chars,
            "contains_cpt_27447": contains_cpt_27447(text),
            "login_wall": login,
            "login_wall_reason": login_reason,
            "blocked": is_blocked,
            "blocked_reason": blocked_reason,
            "host": host,
            "host_resolves": True,
            "error": None,
        }
    except requests.RequestException as exc:
        return {
            "url": url,
            "final_url": None,
            "status": None,
            "redirect_chain": [],
            "content_type": None,
            "bytes": 0,
            "sha256": None,
            "text": "",
            "text_truncated": False,
            "contains_cpt_27447": False,
            "login_wall": False,
            "login_wall_reason": None,
            "blocked": False,
            "blocked_reason": None,
            "host": host,
            "host_resolves": host_resolves,
            "error": str(exc),
        }
