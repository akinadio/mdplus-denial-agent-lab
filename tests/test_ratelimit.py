"""Tests for per-client rate limiting and the operator-endpoint gate."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from synthetic_harness.ratelimit import ApiGuards, FixedWindowLimiter, client_key


class FixedWindowTests(unittest.TestCase):
    def test_allows_up_to_limit_then_blocks(self):
        lim = FixedWindowLimiter(limit=3, window=60)
        base = 1000.0
        self.assertEqual([lim.check("ip", base + i)[0] for i in range(3)], [True, True, True])
        ok, retry = lim.check("ip", base + 3)
        self.assertFalse(ok)
        self.assertGreater(retry, 0)

    def test_window_resets(self):
        lim = FixedWindowLimiter(limit=2, window=10)
        self.assertTrue(lim.check("ip", 100.0)[0])
        self.assertTrue(lim.check("ip", 101.0)[0])
        self.assertFalse(lim.check("ip", 102.0)[0])
        # After the window passes, the old hits fall off.
        self.assertTrue(lim.check("ip", 112.5)[0])

    def test_keys_are_independent(self):
        lim = FixedWindowLimiter(limit=1, window=60)
        self.assertTrue(lim.check("a", 1.0)[0])
        self.assertTrue(lim.check("b", 1.0)[0])
        self.assertFalse(lim.check("a", 2.0)[0])


def _handler(ip="9.9.9.9", headers=None):
    return SimpleNamespace(client_address=(ip, 12345), headers=headers or {})


class ClientKeyTests(unittest.TestCase):
    def test_uses_socket_peer_by_default(self):
        h = _handler("1.2.3.4", {"X-Forwarded-For": "5.6.7.8"})
        self.assertEqual(client_key(h, trust_proxy=False), "1.2.3.4")

    def test_honors_forwarded_when_trusted(self):
        h = _handler("1.2.3.4", {"X-Forwarded-For": "5.6.7.8, 1.2.3.4"})
        self.assertEqual(client_key(h, trust_proxy=True), "5.6.7.8")


class GuardsTests(unittest.TestCase):
    def test_admin_open_when_no_token(self):
        with patch.dict(os.environ, {}, clear=True):
            g = ApiGuards()
        self.assertTrue(g.admin_ok(_handler(headers={})))

    def test_admin_requires_token_when_set(self):
        with patch.dict(os.environ, {"MDPLUS_ADMIN_TOKEN": "secret"}, clear=True):
            g = ApiGuards()
        self.assertFalse(g.admin_ok(_handler(headers={})))
        self.assertFalse(g.admin_ok(_handler(headers={"X-Admin-Token": "wrong"})))
        self.assertTrue(g.admin_ok(_handler(headers={"X-Admin-Token": "secret"})))

    def test_create_limit_configurable(self):
        with patch.dict(os.environ, {"MDPLUS_RATE_CREATE_PER_MIN": "2"}, clear=True):
            g = ApiGuards()
        h = _handler("2.2.2.2")
        self.assertTrue(g.limit("create", h)[0])
        self.assertTrue(g.limit("create", h)[0])
        self.assertFalse(g.limit("create", h)[0])


if __name__ == "__main__":
    unittest.main()
