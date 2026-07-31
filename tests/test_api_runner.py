"""Tests for the sustainable Anthropic-API execution engine.

These exercise the tool-use loop, JSON extraction, artifact writing, the
missing-section repair round, and the spend/cost helpers -- all without a real
API key or network by injecting a fake Anthropic client and fake tools.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from synthetic_harness import api_runner
from synthetic_harness.arms import result_contract


def _valid_result() -> dict:
    """A result object carrying every required top-level field."""
    fields = result_contract()["required_top_level_fields"]
    obj = {f: {} for f in fields}
    obj["status"] = "actionable_result"
    obj["retrieval"] = {"candidates": []}
    obj["confidence"] = "medium"
    obj["blockers"] = []
    obj["next_steps"] = {"primary_action": "Call the payer.", "ordered_actions": []}
    return obj


def _work_order() -> dict:
    return {
        "arm": "web_only",
        "episode_id": "ep_000000000001",
        "case_id": "case-1",
        "objective": "Find the governing policy.",
        "result_schema": {"type": "object"},
        "patient_visible_transcript": [
            {"sequence": 1, "sender": "patient", "body": "My knee replacement was denied."}
        ],
    }


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _tool_block(name: str, tid: str, inp: dict):
    return SimpleNamespace(type="tool_use", name=name, id=tid, input=inp)


def _usage(i: int, o: int):
    return SimpleNamespace(input_tokens=i, output_tokens=o)


class FakeMessages:
    """Returns a scripted sequence of responses; records requests it received."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


class ApiRunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.arm_dir = Path(self._tmp.name)
        os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
        # Fake tools so no network is touched.
        self._search_patch = patch(
            "policy_eval.webtools.search",
            lambda q, c=5: {"backend": "fake", "result_count": 1,
                            "results": [{"title": "Policy", "url": "https://payer.example/p", "snippet": "x"}]},
        )
        self._fetch_patch = patch(
            "policy_eval.webtools.fetch",
            lambda url, max_text_chars=12000: {
                "status": 200, "final_url": url, "bytes": 100, "sha256": "abc",
                "login_wall": False, "content_type": "text/html",
                "error": None, "text": "CPT 27447 is covered when...",
                "text_truncated": False,
            },
        )
        self._search_patch.start()
        self._fetch_patch.start()

    def tearDown(self):
        self._search_patch.stop()
        self._fetch_patch.stop()
        self._tmp.cleanup()
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_tool_loop_then_final_result(self):
        """One tool round-trip, then a final JSON answer -> result.json written."""
        responses = [
            SimpleNamespace(
                stop_reason="tool_use",
                usage=_usage(1000, 200),
                content=[
                    _text_block("Let me search."),
                    _tool_block("web_search", "t1", {"query": "aetna knee policy"}),
                    _tool_block("http_fetch", "t2", {"url": "https://payer.example/p"}),
                ],
            ),
            SimpleNamespace(
                stop_reason="end_turn",
                usage=_usage(1500, 400),
                content=[_text_block(json.dumps(_valid_result()))],
            ),
        ]
        costs = []
        with patch.object(api_runner, "_client", return_value=FakeClient(responses)):
            out = api_runner.run_api_arm(
                self.arm_dir, _work_order(), on_cost=costs.append
            )
        self.assertEqual(out["returncode"], 0, out)
        result = json.loads((self.arm_dir / "result.json").read_text())
        # Controller-owned identifiers are asserted, not trusted from the model.
        self.assertEqual(result["episode_id"], "ep_000000000001")
        self.assertEqual(result["arm"], "web_only")
        # Tool trace + translated events were written.
        trace = (self.arm_dir / "agent_tool_trace.jsonl").read_text().splitlines()
        self.assertEqual(len(trace), 2)
        self.assertTrue((self.arm_dir / "agent_events.jsonl").exists())
        meta = json.loads((self.arm_dir / "agent_run_meta.json").read_text())
        self.assertEqual(meta["engine"], "api")
        self.assertEqual(meta["usage"]["input_tokens"], 2500)
        self.assertGreater(costs[0], 0)

    def test_repair_fills_missing_sections(self):
        """A truncated first answer is completed by a repair round on the same chat."""
        partial = _valid_result()
        partial.pop("next_steps")
        partial.pop("confidence")
        responses = [
            SimpleNamespace(
                stop_reason="end_turn",
                usage=_usage(1000, 300),
                content=[_text_block(json.dumps(partial))],
            ),
            SimpleNamespace(  # repair round supplies the missing fields
                stop_reason="end_turn",
                usage=_usage(500, 100),
                content=[_text_block(json.dumps({
                    "next_steps": {"primary_action": "Appeal.", "ordered_actions": []},
                    "confidence": "low",
                }))],
            ),
        ]
        with patch.object(api_runner, "_client", return_value=FakeClient(responses)):
            out = api_runner.run_api_arm(self.arm_dir, _work_order())
        self.assertEqual(out["returncode"], 0, out)
        result = json.loads((self.arm_dir / "result.json").read_text())
        self.assertIn("next_steps", result)
        self.assertEqual(result["confidence"], "low")
        meta = json.loads((self.arm_dir / "agent_run_meta.json").read_text())
        self.assertEqual(meta["repair"]["outcome"], "repaired")

    def test_no_json_is_a_failed_run(self):
        responses = [
            SimpleNamespace(
                stop_reason="end_turn",
                usage=_usage(100, 50),
                content=[_text_block("I could not find a policy, sorry.")],
            ),
        ]
        with patch.object(api_runner, "_client", return_value=FakeClient(responses)):
            out = api_runner.run_api_arm(self.arm_dir, _work_order())
        self.assertNotEqual(out["returncode"], 0)
        self.assertIn("no JSON", out["error"])

    def test_library_arm_is_rejected(self):
        wo = _work_order()
        wo["arm"] = "library_only"
        out = api_runner.run_api_arm(self.arm_dir, wo)
        self.assertEqual(out["returncode"], 2)

    def test_missing_key_is_reported(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        out = api_runner.run_api_arm(self.arm_dir, _work_order())
        self.assertEqual(out["returncode"], 3)

    def test_cost_estimate_scales_with_tokens(self):
        with patch.dict(os.environ, {
            "MDPLUS_PRICE_INPUT_PER_MTOK": "10",
            "MDPLUS_PRICE_OUTPUT_PER_MTOK": "100",
        }):
            cost = api_runner._estimate_cost({"input_tokens": 1_000_000, "output_tokens": 1_000_000})
        self.assertAlmostEqual(cost, 110.0, places=2)


class EngineSelectionTests(unittest.TestCase):
    def test_explicit_override_wins(self):
        from synthetic_harness.agent_runner import engine_name
        with patch.dict(os.environ, {"MDPLUS_AGENT_ENGINE": "api"}):
            self.assertEqual(engine_name(), "api")

    def test_auto_prefers_api_when_available(self):
        from synthetic_harness import agent_runner
        with patch.dict(os.environ, {"MDPLUS_AGENT_ENGINE": "auto"}), \
             patch.object(api_runner, "api_available", return_value=True):
            self.assertEqual(agent_runner.engine_name(), "api")


if __name__ == "__main__":
    unittest.main()
