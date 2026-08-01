"""Tests for HTTP security headers."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from synthetic_harness.security import SecurityConfig, security_headers


def _handler(headers=None):
    return SimpleNamespace(headers=headers or {})


class SecurityHeaderTests(unittest.TestCase):
    def _headers(self, path, handler=None, env=None):
        with patch.dict(os.environ, env or {}, clear=True):
            cfg = SecurityConfig()
        return dict(security_headers(cfg, handler or _handler(), path))

    def test_baseline_headers_always_present(self):
        h = self._headers("/patient/map/index.html")
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertEqual(h["Referrer-Policy"], "no-referrer")
        self.assertEqual(h["X-Frame-Options"], "SAMEORIGIN")
        self.assertIn("Content-Security-Policy", h)

    def test_api_paths_are_no_store(self):
        self.assertEqual(self._headers("/api/episodes/ep_1")["Cache-Control"], "no-store")
        self.assertNotIn("Cache-Control", self._headers("/patient/map/index.html"))

    def test_csp_can_be_disabled(self):
        h = self._headers("/", env={"MDPLUS_CSP": ""})
        self.assertNotIn("Content-Security-Policy", h)

    def test_csp_is_overridable(self):
        h = self._headers("/", env={"MDPLUS_CSP": "default-src 'none'"})
        self.assertEqual(h["Content-Security-Policy"], "default-src 'none'")

    def test_hsts_only_over_https_behind_trusted_proxy(self):
        # No proxy trust -> never send HSTS.
        h = self._headers("/", handler=_handler({"X-Forwarded-Proto": "https"}))
        self.assertNotIn("Strict-Transport-Security", h)
        # Trusted proxy + https -> send it.
        h2 = self._headers(
            "/", handler=_handler({"X-Forwarded-Proto": "https"}),
            env={"MDPLUS_TRUST_PROXY": "true"},
        )
        self.assertIn("Strict-Transport-Security", h2)
        # Trusted proxy but plain http -> not sent.
        h3 = self._headers(
            "/", handler=_handler({"X-Forwarded-Proto": "http"}),
            env={"MDPLUS_TRUST_PROXY": "true"},
        )
        self.assertNotIn("Strict-Transport-Security", h3)


if __name__ == "__main__":
    unittest.main()
