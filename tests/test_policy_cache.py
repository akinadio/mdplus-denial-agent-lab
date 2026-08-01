"""Tests for the opt-in, verified, staleness-aware policy cache."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from synthetic_harness import policy_cache


# A tiny HTML "policy" that mentions the carrier and the CPT (verifiable).
def _policy_doc(carrier="Aetna", cpt="27447"):
    return (f"<html><body><h1>{carrier} Coverage Policy</h1>"
            f"<p>Knee arthroplasty CPT {cpt} is covered when criteria are met.</p>"
            f"</body></html>").encode()


class PolicyCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(os.environ, {
            "MDPLUS_POLICY_CACHE_ROOT": self._tmp.name,
            "MDPLUS_ENCRYPTION_KEY": "",  # exercise the plaintext path
        }, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_no_consent_stores_nothing(self):
        meta = policy_cache.contribute(
            carrier="Aetna", cpt="27447", content=_policy_doc(),
            consent=False, content_type="text/html",
        )
        self.assertIsNone(meta)
        self.assertEqual(list(Path(self._tmp.name).glob("**/*.meta.json")), [])

    def test_consented_verifiable_doc_is_reusable(self):
        meta = policy_cache.contribute(
            carrier="Aetna", cpt="27447", content=_policy_doc(),
            consent=True, content_type="text/html", now="2026-08-01T00:00:00Z",
        )
        self.assertIsNotNone(meta)
        self.assertTrue(meta["verified"])
        self.assertTrue(meta["cpt_in_doc"])
        self.assertFalse(meta["personal_doc"])
        self.assertTrue(meta["reusable"])
        cands = policy_cache.reuse_candidates("Aetna", "27447",
                                              now=datetime(2026, 8, 2, tzinfo=timezone.utc))
        self.assertEqual(len(cands), 1)

    def test_personal_doc_is_stored_but_not_reusable(self):
        doc = (b"<html><body>Aetna Plan. Member ID: 12345. Member Name: Jane Doe. "
               b"Knee CPT 27447 covered.</body></html>")
        meta = policy_cache.contribute(
            carrier="Aetna", cpt="27447", content=doc, consent=True,
            content_type="text/html", now="2026-08-01T00:00:00Z",
        )
        self.assertTrue(meta["personal_doc"])
        self.assertFalse(meta["reusable"])  # kept, but never served to others
        self.assertEqual(policy_cache.reuse_candidates("Aetna", "27447"), [])

    def test_unverifiable_doc_is_not_reusable(self):
        # CPT not present -> cannot verify -> not reusable.
        doc = b"<html><body>Aetna general marketing page, no codes here.</body></html>"
        meta = policy_cache.contribute(
            carrier="Aetna", cpt="27447", content=doc, consent=True,
            content_type="text/html", now="2026-08-01T00:00:00Z",
        )
        self.assertFalse(meta["verified"])
        self.assertFalse(meta["reusable"])

    def test_staleness_after_90_days(self):
        meta = policy_cache.contribute(
            carrier="Aetna", cpt="27447", content=_policy_doc(), consent=True,
            content_type="text/html", now="2026-05-01T00:00:00Z",
        )
        fresh = datetime(2026, 5, 15, tzinfo=timezone.utc)
        stale = datetime(2026, 9, 1, tzinfo=timezone.utc)  # >90 days later
        self.assertFalse(policy_cache.is_stale(meta, fresh))
        self.assertIsNone(policy_cache.staleness_note(meta, fresh))
        self.assertTrue(policy_cache.is_stale(meta, stale))
        self.assertIn("since been updated", policy_cache.staleness_note(meta, stale))
        # Stale entries drop out of reuse candidates.
        self.assertEqual(policy_cache.reuse_candidates("Aetna", "27447", now=stale), [])

    def test_encrypted_at_rest_when_key_set(self):
        with patch.dict(os.environ, {"MDPLUS_ENCRYPTION_KEY": __import__(
                "synthetic_harness.encryption", fromlist=["generate_key_b64"]
        ).generate_key_b64()}):
            meta = policy_cache.contribute(
                carrier="Cigna", cpt="27447", content=_policy_doc("Cigna"),
                consent=True, content_type="text/html",
            )
            self.assertTrue(meta["encrypted"])
            blob = Path(self._tmp.name) / "cigna" / meta["blob"]
            self.assertTrue(blob.name.endswith(".bin.enc"))
            from synthetic_harness import encryption
            self.assertTrue(encryption.is_encrypted(blob.read_bytes()))


if __name__ == "__main__":
    unittest.main()
