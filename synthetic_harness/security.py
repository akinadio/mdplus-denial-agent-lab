"""HTTP security headers for a public, health-adjacent web service.

These are cheap, standards-based hardening headers that every response should
carry. They are deliberately conservative so they do not break the existing
patient app (which uses inline scripts/styles) or the operator app (which uses a
same-origin iframe to render captured policy documents):

- X-Content-Type-Options: nosniff  — no MIME sniffing.
- Referrer-Policy: no-referrer      — never leak the current URL to third parties.
- X-Frame-Options: SAMEORIGIN       — no external framing (clickjacking).
- Cross-Origin-Opener-Policy        — isolate the browsing context.
- Content-Security-Policy           — restrict where resources may come from.
  The default keeps 'unsafe-inline' for scripts/styles because both frontends
  rely on inline code; it still shuts off object embeds, cross-origin framing,
  and base-tag hijacking. Override with MDPLUS_CSP, or set it empty to disable.
- Strict-Transport-Security         — only when the request arrived over HTTPS
  (via a trusted proxy's X-Forwarded-Proto), so it is never sent on plain HTTP.
- Cache-Control: no-store on /api/    — patient data must not sit in caches.
"""

from __future__ import annotations

import os

DEFAULT_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)


class SecurityConfig:
    def __init__(self) -> None:
        # MDPLUS_CSP unset -> default policy; set-but-empty -> no CSP header.
        env_csp = os.environ.get("MDPLUS_CSP")
        self.csp = DEFAULT_CSP if env_csp is None else env_csp
        self.enable_hsts = os.environ.get("MDPLUS_ENABLE_HSTS", "true").lower() in (
            "1", "true", "yes"
        )
        self.trust_proxy = os.environ.get("MDPLUS_TRUST_PROXY", "").lower() in (
            "1", "true", "yes"
        )

    def is_https(self, handler) -> bool:
        if self.trust_proxy:
            return handler.headers.get("X-Forwarded-Proto", "").lower() == "https"
        # We do not terminate TLS ourselves; without a trusted proxy assume http.
        return False


def security_headers(config: SecurityConfig, handler, path: str) -> list[tuple[str, str]]:
    headers = [
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
        ("X-Frame-Options", "SAMEORIGIN"),
        ("Cross-Origin-Opener-Policy", "same-origin"),
    ]
    if config.csp:
        headers.append(("Content-Security-Policy", config.csp))
    if config.enable_hsts and config.is_https(handler):
        headers.append(
            ("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        )
    if path.startswith("/api/"):
        # PHI and per-patient results must never be cached by intermediaries.
        headers.append(("Cache-Control", "no-store"))
    return headers
