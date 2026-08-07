"""Document-intelligence tests.

The vision model is a FAKE client that returns canned JSON in the Anthropic
response shape, so extraction, per-field confidence scoring, the "never guess"
rule, plan-pinning, and the confirm-list are all exercised WITHOUT any API key
or network.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from synthetic_harness import extract


def _resp(payload: dict) -> SimpleNamespace:
    """An Anthropic-shaped response whose single text block is `payload` as JSON."""
    text = json.dumps(payload)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


class _FakeVision:
    """Returns queued responses; records the content blocks it was sent."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.sent = []
        self.messages = self

    def create(self, **kw):
        self.sent.append(kw)
        return self._responses.pop(0)


def _img(name="page_1.jpg", mime="image/jpeg", data=b"\xff\xd8fake"):
    return {"safe_name": name, "original_name": name, "mime": mime,
            "bytes": data, "size_bytes": len(data)}


CARD_GOOD = {
    "document_type": "insurance_card",
    "fields": {
        "member_name": {"value": "Maria Gomez", "confidence": "high"},
        "insurer_name": {"value": "Aetna", "confidence": "high"},
        "plan_name": {"value": "Aetna Choice POS II", "confidence": "high"},
        "plan_type": {"value": "POS", "confidence": "high"},
        "member_id": {"value": "W123456789", "confidence": "high"},
        "group_number": {"value": "0891234", "confidence": "medium"},
        "rx_bin": {"value": "610591", "confidence": "high"},
        "rx_pcn": {"value": None, "confidence": "unreadable"},
        "customer_service_phone": {"value": "1-800-872-3862", "confidence": "high"},
        "payer_id": {"value": "60054", "confidence": "medium"},
    },
}

LETTER_GOOD = {
    "document_type": "denial_letter",
    "fields": {
        "patient_name": {"value": "Maria Gomez", "confidence": "high"},
        "insurer_name": {"value": "Aetna", "confidence": "high"},
        "plan_name": {"value": None, "confidence": "unreadable"},
        "plan_type": {"value": None, "confidence": "unreadable"},
        "member_id": {"value": "W123456789", "confidence": "medium"},
        "group_id": {"value": None, "confidence": "unreadable"},
        "claim_number": {"value": "CLM-55210", "confidence": "high"},
        "denial_date": {"value": "2026-07-15", "confidence": "high"},
        "appeal_deadline": {"value": "180 days from this notice", "confidence": "high"},
        "denial_reason": {"value": "Not medically necessary", "confidence": "high"},
    },
    "denied_procedures": [
        {"code": "27447", "description": "Total knee arthroplasty",
         "decision": "DENIED", "confidence": "high"},
    ],
    "letter_text": "Dear Maria Gomez,\nClaim CLM-55210 is DENIED.\nProcedure 27447 is not medically necessary.\nYou have 180 days to appeal.",
}


class ScoringTests(unittest.TestCase):
    def test_card_scores_fields_and_flags_only_required_weak(self):
        rec = extract.score_document(CARD_GOOD, "insurance_card")
        self.assertEqual(rec["outcome"], "read")
        self.assertEqual(rec["fields"]["member_id"]["value"], "W123456789")
        self.assertEqual(rec["fields"]["member_id"]["confidence"], "high")
        # rx_pcn is unreadable but NOT required -> not in confirm list.
        self.assertFalse(rec["fields"]["rx_pcn"]["needs_confirmation"])
        self.assertEqual(rec["needs_confirmation"], [])

    def test_blank_value_is_forced_unreadable_even_if_model_says_high(self):
        payload = {
            "document_type": "insurance_card",
            "fields": {
                "member_name": {"value": "  ", "confidence": "high"},
                "insurer_name": {"value": "Aetna", "confidence": "high"},
                "plan_name": {"value": "X", "confidence": "high"},
                "plan_type": {"value": "PPO", "confidence": "high"},
                "member_id": {"value": "[illegible]", "confidence": "high"},
            },
        }
        rec = extract.score_document(payload, "insurance_card")
        self.assertEqual(rec["fields"]["member_name"]["confidence"], "unreadable")
        self.assertIsNone(rec["fields"]["member_name"]["value"])
        self.assertIsNone(rec["fields"]["member_id"]["value"])
        # Both required + unreadable -> both must be confirmed.
        keys = {c["key"] for c in rec["needs_confirmation"]}
        self.assertIn("member_name", keys)
        self.assertIn("member_id", keys)

    def test_low_confidence_required_field_needs_confirmation(self):
        payload = {
            "document_type": "denial_letter",
            "fields": {
                "patient_name": {"value": "M. Gomez", "confidence": "low"},
                "insurer_name": {"value": "Aetna", "confidence": "high"},
                "appeal_deadline": {"value": "180 days", "confidence": "high"},
                "denial_reason": {"value": "not medically necessary", "confidence": "high"},
            },
        }
        rec = extract.score_document(payload, "denial_letter")
        flagged = {c["key"]: c["reason"] for c in rec["needs_confirmation"]}
        self.assertEqual(flagged.get("patient_name"), "hard to read")

    def test_wrong_document_detected(self):
        rec = extract.score_document({"document_type": "other", "fields": {}}, "insurance_card")
        self.assertEqual(rec["outcome"], "wrong_document")

    def test_unparseable_raw_is_unreadable(self):
        raw = {"outcome": "unparseable", "document_type": None, "fields": {}}
        rec = extract.score_document(raw, "insurance_card")
        self.assertEqual(rec["outcome"], "unparseable")


class InsurerCanonTests(unittest.TestCase):
    def test_maps_variants_to_directory_keys(self):
        self.assertEqual(extract.canonical_insurer("Aetna Better Health"), "aetna")
        self.assertEqual(extract.canonical_insurer("UnitedHealthcare"), "unitedhealthcare")
        self.assertEqual(extract.canonical_insurer("Elevance / Anthem"), "anthem")
        self.assertEqual(extract.canonical_insurer("Blue Cross Blue Shield of Texas"), "bluecross")
        self.assertEqual(extract.canonical_insurer("Ambetter from Centene"), "centene")
        self.assertIsNone(extract.canonical_insurer("Some Local Co-op"))

    def test_medicaid_before_medicare(self):
        self.assertEqual(extract.canonical_insurer("State Medicaid"), "medicaid")
        self.assertEqual(extract.canonical_insurer("Medicare Part B"), "medicare")


class PinTests(unittest.TestCase):
    def test_card_pins_exact_plan(self):
        card = extract.score_document(CARD_GOOD, "insurance_card")
        letter = extract.score_document(LETTER_GOOD, "denial_letter")
        pin = extract.pin_plan(card, letter)
        self.assertTrue(pin["pinned"])
        self.assertEqual(pin["identity"]["insurer_key"], "aetna")
        self.assertEqual(pin["identity"]["plan_name"]["value"], "Aetna Choice POS II")
        self.assertEqual(pin["identity"]["coverage_line"], "commercial")

    def test_letter_only_cannot_pin_commercial_plan(self):
        letter = extract.score_document(LETTER_GOOD, "denial_letter")
        pin = extract.pin_plan(None, letter)
        # Insurer known, but no plan name -> not pinned, with a helpful reason.
        self.assertFalse(pin["pinned"])
        self.assertEqual(pin["identity"]["insurer_key"], "aetna")
        self.assertTrue(any("exact plan" in r for r in pin["reasons"]))

    def test_medicare_pins_on_program_without_plan_name(self):
        card = extract.score_document({
            "document_type": "insurance_card",
            "fields": {
                "member_name": {"value": "John Doe", "confidence": "high"},
                "insurer_name": {"value": "Medicare", "confidence": "high"},
                "plan_name": {"value": None, "confidence": "unreadable"},
                "plan_type": {"value": "Original Medicare", "confidence": "high"},
                "member_id": {"value": "1EG4-TE5-MK72", "confidence": "high"},
            },
        }, "insurance_card")
        pin = extract.pin_plan(card, None)
        self.assertTrue(pin["pinned"])
        self.assertEqual(pin["identity"]["coverage_line"], "medicare")


class ReadIntakeTests(unittest.TestCase):
    def test_end_to_end_with_fake_vision(self):
        fake = _FakeVision([_resp(LETTER_GOOD), _resp(CARD_GOOD)])
        out = extract.read_intake(
            letter_files=[_img()], card_files=[_img("card.jpg")], client=fake,
        )
        self.assertEqual(out["outcome"], "read")
        self.assertTrue(out["plan"]["pinned"])
        self.assertEqual(out["needs_confirmation"], [])
        self.assertIn("180 days to appeal", out["letter"]["text"])
        # Two model calls, each carrying image blocks then a text instruction.
        self.assertEqual(len(fake.sent), 2)
        blocks = fake.sent[0]["messages"][0]["content"]
        self.assertEqual(blocks[0]["type"], "image")
        self.assertEqual(blocks[-1]["type"], "text")

    def test_blurry_card_surfaces_confirmations(self):
        blurry = {
            "document_type": "insurance_card",
            "fields": {
                "member_name": {"value": "Maria Gomez", "confidence": "high"},
                "insurer_name": {"value": "Aetna", "confidence": "high"},
                "plan_name": {"value": "Aetna Cho...", "confidence": "low"},
                "plan_type": {"value": None, "confidence": "unreadable"},
                "member_id": {"value": None, "confidence": "unreadable"},
            },
        }
        fake = _FakeVision([_resp(blurry)])
        out = extract.read_intake(card_files=[_img()], client=fake)
        keys = {c["key"] for c in out["needs_confirmation"]}
        # member_id (required, missing), plan_type (required, missing),
        # plan_name (required, low) all get asked; plan pin also unresolved.
        self.assertIn("member_id", keys)
        self.assertIn("plan_type", keys)
        self.assertFalse(out["plan"]["pinned"])

    def test_pdf_uses_document_block(self):
        fake = _FakeVision([_resp(LETTER_GOOD)])
        extract.read_intake(
            letter_files=[_img("page_1.pdf", "application/pdf", b"%PDF-1.4")],
            client=fake,
        )
        blocks = fake.sent[0]["messages"][0]["content"]
        self.assertEqual(blocks[0]["type"], "document")
        self.assertEqual(blocks[0]["source"]["media_type"], "application/pdf")


if __name__ == "__main__":
    unittest.main()
