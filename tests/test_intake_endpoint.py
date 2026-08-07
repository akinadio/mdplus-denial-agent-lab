"""Integration test for POST /api/intake/read.

Boots the real ThreadingHTTPServer on an ephemeral port and posts real base64
image bytes, with the vision model replaced by a fake client so the whole path
— attachment decode, extraction, plan-pin, confirm-list, spend recording, JSON
response — runs offline with no API key.
"""

from __future__ import annotations

import base64
import json
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from types import SimpleNamespace

from http.server import ThreadingHTTPServer

from synthetic_harness import server, extract
from tests.test_extract import CARD_GOOD, LETTER_GOOD, _FakeVision, _resp


def _b64_png() -> str:
    # A tiny valid-enough byte blob; the fake client never inspects it.
    return base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")


class IntakeEndpointTests(unittest.TestCase):
    def setUp(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def _post(self, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/intake/read",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_reads_card_and_letter_and_pins_plan(self):
        fake = _FakeVision([_resp(LETTER_GOOD), _resp(CARD_GOOD)])
        with unittest.mock.patch.object(extract, "_client", return_value=fake):
            status, body = self._post({
                "letter_attachments": [{"mime": "image/png", "data": _b64_png()}],
                "card_attachments": [{"mime": "image/png", "data": _b64_png()}],
            })
        self.assertEqual(status, 200)
        self.assertEqual(body["outcome"], "read")
        self.assertTrue(body["plan"]["pinned"])
        self.assertEqual(body["plan"]["identity"]["insurer_key"], "aetna")
        self.assertEqual(body["needs_confirmation"], [])
        self.assertNotIn("usage", body)  # never leaked back to the client

    def test_no_files_is_bad_request(self):
        status, body = self._post({})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_bad_mime_is_bad_request(self):
        status, body = self._post({
            "card_attachments": [{"mime": "application/x-msdownload", "data": _b64_png()}],
        })
        self.assertEqual(status, 400)

    def test_budget_cap_returns_at_capacity(self):
        with unittest.mock.patch.object(server, "budget_exceeded", return_value=True):
            status, body = self._post({
                "card_attachments": [{"mime": "image/png", "data": _b64_png()}],
            })
        self.assertEqual(status, 503)
        self.assertEqual(body["outcome"], "at_capacity")


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
