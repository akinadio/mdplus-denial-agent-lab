"""Tests for policy anchors (directory + cache leads fed to the agent)."""

from __future__ import annotations

import unittest

from synthetic_harness import policy_anchors


class AnchorTests(unittest.TestCase):
    def test_carrier_fuzzy_match(self):
        self.assertEqual(policy_anchors.carrier_key("UnitedHealthcare"), "UnitedHealthcare")
        self.assertEqual(policy_anchors.carrier_key("Aetna Choice POS II"), "Aetna (CVS Health)")
        self.assertEqual(policy_anchors.carrier_key("Blue Shield of California"),
                         "HCSC (BCBS IL/TX/NM/OK/MT)")  # any Blue -> shared Blue set
        self.assertIsNone(policy_anchors.carrier_key("Some Tiny Regional HMO"))

    def test_cpt_range_and_list_matching(self):
        self.assertTrue(policy_anchors._cpt_matches("29915", "29914-29916"))
        self.assertFalse(policy_anchors._cpt_matches("29920", "29914-29916"))
        self.assertTrue(policy_anchors._cpt_matches("73221", "73721/73221/72148"))
        self.assertTrue(policy_anchors._cpt_matches("27447", "27447"))

    def test_anchors_for_known_carrier_and_cpt(self):
        # Aetna TKA (27447) is in the committed directory with a public URL.
        anchors = policy_anchors.anchors_for("Aetna", "27447")
        self.assertTrue(any(a["source"] == "directory" and a["url"] for a in anchors))
        aetna = next(a for a in anchors if a["source"] == "directory")
        self.assertIn("aetna.com", aetna["url"])

    def test_no_anchor_for_unknown_carrier(self):
        self.assertEqual(policy_anchors.anchors_for("Tiny Regional HMO", "27447"), [])

    def test_medicaid_anchor_uses_state_portal(self):
        anchors = policy_anchors.anchors_for("Texas Medicaid", "27447", "Texas")
        med = [a for a in anchors if a["source"] == "medicaid_directory"]
        self.assertEqual(len(med), 1)
        self.assertIn("tmhp.com", med[0]["url"])

    def test_medicaid_without_state_gives_no_medicaid_anchor(self):
        anchors = policy_anchors.anchors_for("Medicaid", "27447")
        self.assertFalse(any(a["source"] == "medicaid_directory" for a in anchors))

    def test_prompt_block_renders_and_is_empty_when_none(self):
        self.assertEqual(policy_anchors.anchors_prompt_block([]), "")
        block = policy_anchors.anchors_prompt_block(policy_anchors.anchors_for("Cigna", "27447"))
        self.assertIn("KNOWN POLICY LEADS", block)
        self.assertIn("verify", block.lower())


if __name__ == "__main__":
    unittest.main()
