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


LEDGER = {
    "meta": {"verdicts": ["verified", "criteria_proprietary_not_public"]},
    "urls": {
        # Deliberately spelled differently from the SEED entry above: a
        # different query-parameter case and a trailing slash. A citation and a
        # ledger row that name the same document must be recognized as the same
        # document, or the cross-check silently does nothing.
        "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=36575": {
            "per_cpt": {"27447": "verified"},
            "note": "Noridian consolidated its TKA LCDs eff 2025-11-06.",
        },
        "https://www.aetna.com/cpb/medical/data/600_699/0660.html/": {
            "per_cpt": {"27447": "criteria_proprietary_not_public"},
            "note": "Pretend verdict, so the test does not depend on real data.",
        },
    },
}


class VerdictCrossCheckTests(unittest.TestCase):
    """The cache must never be the only voice in the room.

    Our own verification record (the ledger, and the app-option directory
    behind it) has independently fetched and read these documents. When it
    disagrees with a cached citation -- most importantly when it found the
    document carries no usable criteria -- that has to reach the caller, or a
    retrieval run will burn a round trip rediscovering it.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        (root / "known_citations.json").write_text(json.dumps(SEED), encoding="utf-8")
        (root / "url_verification_ledger.json").write_text(json.dumps(LEDGER), encoding="utf-8")
        self._orig = (cc._DATA_PATH, cc._LEDGER_PATH, cc._DIRECTORY_PATH)
        cc._DATA_PATH = root / "known_citations.json"
        cc._LEDGER_PATH = root / "url_verification_ledger.json"
        cc._DIRECTORY_PATH = root / "does_not_exist.csv"
        cc.reload()

    def tearDown(self):
        cc._DATA_PATH, cc._LEDGER_PATH, cc._DIRECTORY_PATH = self._orig
        cc.reload()
        self._tmpdir.cleanup()

    def test_verdict_is_attached_to_a_hit(self):
        hit = cc.lookup("Medicare", "CA", "27447")
        self.assertEqual(hit["ledger_verdict"], "verified")
        self.assertIn("Noridian", hit["ledger_note"])

    def test_url_spelling_differences_still_match(self):
        """Query-param case and a trailing slash must not defeat the match."""
        hit = cc.lookup("Aetna", "TX", "27447")
        self.assertEqual(hit["ledger_verdict"], "criteria_proprietary_not_public")

    def test_lookup_does_not_mutate_the_cached_entry(self):
        cc.lookup("Aetna", "TX", "27447")
        self.assertNotIn("ledger_verdict", cc._load()[0])

    def test_hit_survives_when_no_verdict_exists(self):
        cc._LEDGER_PATH = Path(self._tmpdir.name) / "nothing_here.json"
        cc.reload()
        hit = cc.lookup("Aetna", "TX", "27447")
        self.assertIsNotNone(hit)
        self.assertNotIn("ledger_verdict", hit)

    def test_directory_csv_supplies_a_verdict_when_the_ledger_has_none(self):
        root = Path(self._tmpdir.name)
        (root / "dir.csv").write_text(
            "state,insurance_company,plan_type,surgery,cpt,status,policy_title,"
            "effective_date,policy_url,note\n"
            "Texas,Aetna,Commercial/ACA,Total knee replacement,27447,"
            "NO PUBLIC CRITERIA (vendor),T,,"
            "https://www.aetna.com/cpb/medical/data/600_699/0660.html,vendor tool\n",
            encoding="utf-8",
        )
        cc._LEDGER_PATH = root / "nothing_here.json"
        cc._DIRECTORY_PATH = root / "dir.csv"
        cc.reload()
        self.assertEqual(
            cc.lookup("Aetna", "TX", "27447")["ledger_verdict"],
            "criteria_proprietary_not_public",
        )

    def test_verdict_for_is_usable_on_its_own(self):
        self.assertIsNone(cc.verdict_for("https://example.com/nope.pdf", "27447"))
        self.assertIsNone(cc.verdict_for("", "27447"))


if __name__ == "__main__":
    unittest.main()
