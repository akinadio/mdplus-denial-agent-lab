"""Tests for envelope encryption of PHI at rest."""

from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synthetic_harness import encryption


def _key_env():
    return {"MDPLUS_ENCRYPTION_KEY": encryption.generate_key_b64()}


class EncryptionTests(unittest.TestCase):
    def test_round_trip(self):
        with patch.dict(os.environ, _key_env(), clear=True):
            blob = encryption.encrypt(b"denial letter text")
            self.assertTrue(encryption.is_encrypted(blob))
            self.assertNotIn(b"denial letter text", blob)  # not plaintext
            self.assertEqual(encryption.decrypt(blob), b"denial letter text")

    def test_each_encryption_is_unique(self):
        with patch.dict(os.environ, _key_env(), clear=True):
            a = encryption.encrypt(b"same input")
            b = encryption.encrypt(b"same input")
            self.assertNotEqual(a, b)  # random DEK + nonces
            self.assertEqual(encryption.decrypt(a), encryption.decrypt(b))

    def test_tampering_is_detected(self):
        with patch.dict(os.environ, _key_env(), clear=True):
            blob = bytearray(encryption.encrypt(b"secret"))
            blob[-1] ^= 0x01  # flip a ciphertext bit
            with self.assertRaises(Exception):
                encryption.decrypt(bytes(blob))

    def test_wrong_key_cannot_decrypt(self):
        with patch.dict(os.environ, _key_env(), clear=True):
            blob = encryption.encrypt(b"secret")
        with patch.dict(os.environ, _key_env(), clear=True):  # different key
            with self.assertRaises(Exception):
                encryption.decrypt(blob)

    def test_available_gating(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(encryption.available())
        with patch.dict(os.environ, _key_env(), clear=True):
            self.assertTrue(encryption.available())

    def test_maybe_encrypt_passthrough_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            data, enc = encryption.maybe_encrypt(b"plain")
            self.assertEqual(data, b"plain")
            self.assertFalse(enc)

    def test_key_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            keyfile = Path(d) / "key"
            keyfile.write_text(encryption.generate_key_b64())
            with patch.dict(os.environ, {"MDPLUS_ENCRYPTION_KEY_FILE": str(keyfile)}, clear=True):
                self.assertTrue(encryption.available())
                self.assertEqual(encryption.decrypt(encryption.encrypt(b"x")), b"x")

    def test_bad_key_length_raises(self):
        with patch.dict(os.environ, {"MDPLUS_ENCRYPTION_KEY": base64.b64encode(b"short").decode()}, clear=True):
            with self.assertRaises(ValueError):
                encryption.encrypt(b"x")


class SaveUploadsEncryptionTests(unittest.TestCase):
    def test_uploads_are_sealed_when_key_present(self):
        from synthetic_harness.letter_reader import save_uploads

        with tempfile.TemporaryDirectory() as d, \
             patch.dict(os.environ, _key_env(), clear=True):
            files = [{"safe_name": "page_0.jpg", "bytes": b"\xff\xd8rawimage"}]
            saved = save_uploads(files, Path(d))
            self.assertEqual(saved, ["page_0.jpg.enc"])
            blob = (Path(d) / "page_0.jpg.enc").read_bytes()
            self.assertTrue(encryption.is_encrypted(blob))
            self.assertEqual(encryption.decrypt(blob), b"\xff\xd8rawimage")

    def test_uploads_plain_without_key(self):
        from synthetic_harness.letter_reader import save_uploads

        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            files = [{"safe_name": "page_0.jpg", "bytes": b"rawimage"}]
            saved = save_uploads(files, Path(d))
            self.assertEqual(saved, ["page_0.jpg"])
            self.assertEqual((Path(d) / "page_0.jpg").read_bytes(), b"rawimage")


if __name__ == "__main__":
    unittest.main()
