"""Tests for the known-citation cache (synthetic_harness/citation_cache.py).

Covers: exact matches, normalization (full state names, "CPT " prefixes,
narrative payer text), and -- most importantly -- that a brand-name substring
match is REJECTED when it actually points at a different product line
(Medicaid managed care vs. commercial, Medicare Advantage vs. Original
Medicare). A false-positive cache hit here means showing a real patient the
wrong payer's policy, so these guardrails are load-bearing, not cosmetic.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from synthetic_harness import citation_cache as cc

SEED = [
    {
        "payer_key": "aetna",
        "state": "TX",
        "cpt": ["27447"],
        "selected_source_title": "Aetna CPB 0660",
        "selected_source_url": "https://www.aetna.com/cpb/medical/data/600_699/0660.html",
    },
    {
        "payer_key": "medicare",
        "state": "CA",
        "cpt": ["27447"],
        "selected_source_title": "LCD L36575",
        "selected_source_url": "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?LCDId=36575",
    },
]


class CitationCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data_path = Path(self._tmpdir.name) / "known_citations.json"
        self._data_path.write_text(json.dumps(SEED), encoding="utf-8")
        self._orig_path = cc._DATA_PATH
        cc._DATA_PATH = self._data_path
        cc.reload()

    def tearDown(self):
        cc._DATA_PATH = self._orig_path
        cc.reload()
        self._tmpdir.cleanup()

    def test_exact_match(self):
        hit = cc.lookup("Aetna", "TX", "27447")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["selected_source_title"], "Aetna CPB 0660")

    def test_wrong_cpt_misses(self):
        self.assertIsNone(cc.lookup("Aetna", "TX", "99999"))

    def test_wrong_state_misses(self):
        self.assertIsNone(cc.lookup("Aetna", "NY", "27447"))

    def test_unknown_payer_misses(self):
        self.assertIsNone(cc.lookup("Humana", "TX", "27447"))

    def test_full_state_name_normalizes(self):
        self.assertIsNotNone(cc.lookup("Aetna", "Texas", "27447"))

    def test_cpt_prefix_normalizes(self):
        self.assertIsNotNone(cc.lookup("Aetna", "TX", "CPT 27447"))

    def test_narrative_payer_text_still_matches(self):
        hit = cc.lookup(
            "Medicare (payer entity as stated by patient; not yet confirmed "
            "between Original Medicare and Medicare Advantage)",
            "CA",
            "27447",
        )
        self.assertIsNotNone(hit)

    def test_medicaid_variant_does_not_inherit_commercial_citation(self):
        """The core safety case: a brand-name substring must not cross a
        real product-line boundary."""
        self.assertIsNone(cc.lookup("Aetna Better Health of Texas", "TX", "27447"))

    def test_medicare_advantage_does_not_match_plain_medicare_entry(self):
        self.assertIsNone(cc.lookup("Medicare Advantage", "CA", "27447"))

    def test_missing_fields_miss_cleanly(self):
        self.assertIsNone(cc.lookup("", "TX", "27447"))
        self.assertIsNone(cc.lookup("Aetna", "", "27447"))
        self.assertIsNone(cc.lookup("Aetna", "TX", ""))


if __name__ == "__main__":
    unittest.main()
