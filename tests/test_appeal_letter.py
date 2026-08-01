"""Tests for denial-reason-aware output and appeal-letter drafting."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from synthetic_harness import appeal_letter


def _grounded_result(**over):
    result = {
        "status": "actionable_result",
        "case_identification": {
            "payer": "Aetna", "plan_name": "Choice POS II", "procedure": "TKA",
            "cpt": "27447", "denial_language": "not medically necessary",
        },
        "policy_analysis": {
            "denial_category": "documentation gap",
            "apparent_reason": "conservative care not documented in submission",
            "criteria_at_issue": ["3 months conservative care"],
            "documentation_gaps": ["PT notes not attached"],
            "unmet_criteria": [],
        },
        "retrieval": {
            "selected_source": {
                "title": "Aetna CPB 0673", "evidence_role": "governing_policy",
                "url": "https://aetna.example/cpb0673", "effective_date": "2026-01-01",
            },
            "citations": [
                {"claim": "conservative care 3 months", "reference": "CPB 0673 §II",
                 "excerpt": "at least 3 months of conservative therapy"},
            ],
        },
    }
    result.update(over)
    return result


class AssessTests(unittest.TestCase):
    def test_documentation_gap_recommends_letter(self):
        a = appeal_letter.assess_letter(_grounded_result())
        self.assertTrue(a["recommended"])
        self.assertEqual(a["kind"], "appeal_letter")

    def test_blocked_is_not_recommended(self):
        a = appeal_letter.assess_letter(_grounded_result(status="blocked"))
        self.assertFalse(a["recommended"])
        self.assertEqual(a["kind"], "blocked")

    def test_no_governing_source_gathers_first(self):
        r = _grounded_result()
        r["retrieval"]["selected_source"]["evidence_role"] = "supporting_document"
        a = appeal_letter.assess_letter(r)
        self.assertFalse(a["recommended"])
        self.assertEqual(a["kind"], "gather_first")

    def test_no_citations_gathers_first(self):
        r = _grounded_result()
        r["retrieval"]["citations"] = []
        a = appeal_letter.assess_letter(r)
        self.assertFalse(a["recommended"])
        self.assertEqual(a["kind"], "gather_first")

    def test_benefit_exclusion_not_appealable(self):
        r = _grounded_result()
        r["policy_analysis"]["denial_category"] = "Benefit exclusion (cosmetic)"
        a = appeal_letter.assess_letter(r)
        self.assertFalse(a["recommended"])
        self.assertEqual(a["kind"], "not_appealable")

    def test_genuinely_unmet_criteria_means_meet_first(self):
        r = _grounded_result()
        r["policy_analysis"]["unmet_criteria"] = ["has not completed 3 months PT"]
        r["policy_analysis"]["documentation_gaps"] = []
        a = appeal_letter.assess_letter(r)
        self.assertFalse(a["recommended"])
        self.assertEqual(a["kind"], "meet_criteria")


class GenerateTests(unittest.TestCase):
    def test_letter_generation_uses_citations_and_returns_markdown(self):
        drafted_text = "RE: Appeal of denial\n\nYour plan's policy states..."

        class FakeMessages:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=drafted_text)],
                    usage=SimpleNamespace(input_tokens=800, output_tokens=600),
                )

        fake = SimpleNamespace(messages=FakeMessages())
        out = appeal_letter.generate_appeal_letter(
            _grounded_result(), patient_submission="I tried PT for months.", client=fake
        )
        self.assertIn("letter_markdown", out)
        self.assertEqual(out["letter_markdown"], drafted_text)
        self.assertGreater(out["estimated_cost_usd"], 0)
        # The policy citation excerpt must be handed to the model as grounding.
        sent = fake.messages.calls[0]["messages"][0]["content"]
        self.assertIn("at least 3 months of conservative therapy", sent)
        self.assertIn("CPB 0673", sent)

    def test_patient_voice_uses_patient_system_prompt(self):
        class FakeMessages:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="I am appealing...")],
                    usage=SimpleNamespace(input_tokens=10, output_tokens=10),
                )

        fake = SimpleNamespace(messages=FakeMessages())
        out = appeal_letter.generate_appeal_letter(
            _grounded_result(), client=fake, sender="patient"
        )
        self.assertEqual(out["sender"], "patient")
        self.assertIn("first person", fake.messages.calls[0]["system"])

    def test_unknown_sender_errors(self):
        out = appeal_letter.generate_appeal_letter(_grounded_result(), sender="lawyer")
        self.assertIn("error", out)

    def test_missing_key_without_client_errors(self):
        with patch.dict(os.environ, {}, clear=True):
            out = appeal_letter.generate_appeal_letter(_grounded_result())
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
