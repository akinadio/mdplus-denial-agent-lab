"""The PDF extractor must raise on failure, not return empty text.

A swallowed failure returns "" downstream, which reads as "the policy is not on
this page" -- the confidently-wrong absence the eval exists to prevent.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from policy_eval.common import ExtractionError, extract_text, pdf_text


class ExtractionTests(unittest.TestCase):
    def test_garbage_pdf_raises_not_empties(self):
        # Looks like a PDF (magic bytes) but is not parseable.
        bad = b"%PDF-1.7\nnot actually a valid pdf body"
        with self.assertRaises(ExtractionError):
            pdf_text(bad)

    def test_extract_text_propagates_pdf_failure(self):
        bad = b"%PDF-\x00\x01\x02 garbage"
        with self.assertRaises(ExtractionError):
            extract_text(bad, "application/pdf")

    def test_html_still_extracts_normally(self):
        html = b"<html><body><h1>Coverage Policy</h1><p>CPT 27447 is covered.</p></body></html>"
        text = extract_text(html, "text/html")
        self.assertIn("Coverage Policy", text)
        self.assertIn("27447", text)

    def test_plain_text_passthrough(self):
        text = extract_text(b"just some plain text", "text/plain")
        self.assertEqual(text, "just some plain text")


if __name__ == "__main__":
    unittest.main()
