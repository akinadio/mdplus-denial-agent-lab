"""Multi-provider agent loop tests.

Each provider is driven with a FAKE client that mimics that SDK's response
shape, so the tool loop, the tool-call round-trip, the final-answer extraction,
and token-usage accounting are all exercised WITHOUT any API key or network.
(Google additionally patches `_tools_and_config` so the real google-genai SDK
need not be installed to test the control flow.)
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from synthetic_harness import providers


def _record_tool():
    calls = []

    def tool_call(name, args):
        calls.append((name, dict(args)))
        return {"ok": True, "echo": args}

    return tool_call, calls


class _FakeAnthropic:
    def __init__(self, responses):
        self._responses = list(responses)
        self.messages = self

    def create(self, **kw):  # noqa: ARG002
        return self._responses.pop(0)


class _FakeOpenAI:
    def __init__(self, responses):
        self._responses = list(responses)
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kw):  # noqa: ARG002
        return self._responses.pop(0)


class _FakeGoogle:
    def __init__(self, responses):
        self._responses = list(responses)
        self.models = self

    def generate_content(self, **kw):  # noqa: ARG002
        return self._responses.pop(0)


COMMON = dict(
    model="m", system="sys", prompt="do it",
    deadline=1e18, max_iters=10, max_tokens=100,
)


class AnthropicLoopTests(unittest.TestCase):
    def test_runs_tool_then_returns_final(self):
        r1 = SimpleNamespace(
            stop_reason="tool_use",
            content=[SimpleNamespace(type="tool_use", id="t1",
                                     name="web_search", input={"query": "knee"})],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
        r2 = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text='{"answer": 1}')],
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
        )
        tool_call, calls = _record_tool()
        usage = {"input_tokens": 0, "output_tokens": 0}
        p = providers.AnthropicProvider()
        final, transcript, stop = p.run(
            client=_FakeAnthropic([r1, r2]), tool_call=tool_call, usage=usage, **COMMON)
        self.assertEqual(final, '{"answer": 1}')
        self.assertEqual(calls, [("web_search", {"query": "knee"})])
        self.assertEqual(usage, {"input_tokens": 13, "output_tokens": 7})
        self.assertTrue(len(transcript) >= 3)  # user, assistant, tool_result...


class OpenAILoopTests(unittest.TestCase):
    def test_runs_tool_then_returns_final(self):
        call = SimpleNamespace(id="c1",
                               function=SimpleNamespace(name="http_fetch",
                                                        arguments='{"url": "https://x"}'))
        r1 = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=[call]),
                finish_reason="tool_calls")],
            usage=SimpleNamespace(prompt_tokens=8, completion_tokens=4),
        )
        r2 = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"answer": 2}', tool_calls=None),
                finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1),
        )
        tool_call, calls = _record_tool()
        usage = {"input_tokens": 0, "output_tokens": 0}
        p = providers.OpenAIProvider()
        final, transcript, stop = p.run(
            client=_FakeOpenAI([r1, r2]), tool_call=tool_call, usage=usage, **COMMON)
        self.assertEqual(final, '{"answer": 2}')
        self.assertEqual(calls, [("http_fetch", {"url": "https://x"})])
        self.assertEqual(usage, {"input_tokens": 10, "output_tokens": 5})
        # system prompt is the first message for OpenAI
        self.assertEqual(transcript[0]["role"], "system")


class GoogleLoopTests(unittest.TestCase):
    def test_runs_tool_then_returns_final(self):
        fake_types = SimpleNamespace(
            Content=lambda role=None, parts=None: SimpleNamespace(
                role=role, parts=list(parts or [])),
            Part=lambda text=None, function_response=None: SimpleNamespace(
                text=text, function_call=None, function_response=function_response),
            FunctionResponse=lambda name=None, response=None: SimpleNamespace(
                name=name, response=response),
        )
        fc_part = SimpleNamespace(
            function_call=SimpleNamespace(name="web_search", args={"query": "hip"}),
            text=None)
        c1 = SimpleNamespace(role="model", parts=[fc_part])
        r1 = SimpleNamespace(candidates=[SimpleNamespace(content=c1)],
                             usage_metadata=SimpleNamespace(
                                 prompt_token_count=9, candidates_token_count=6))
        txt_part = SimpleNamespace(function_call=None, text='{"answer": 3}')
        c2 = SimpleNamespace(role="model", parts=[txt_part])
        r2 = SimpleNamespace(candidates=[SimpleNamespace(content=c2)],
                             usage_metadata=SimpleNamespace(
                                 prompt_token_count=1, candidates_token_count=1))
        tool_call, calls = _record_tool()
        usage = {"input_tokens": 0, "output_tokens": 0}
        p = providers.GoogleProvider()
        with patch.object(providers.GoogleProvider, "_tools_and_config",
                          return_value=(object(), fake_types)):
            final, transcript, stop = p.run(
                client=_FakeGoogle([r1, r2]), tool_call=tool_call, usage=usage, **COMMON)
        self.assertEqual(final, '{"answer": 3}')
        self.assertEqual(calls, [("web_search", {"query": "hip"})])
        self.assertEqual(usage, {"input_tokens": 10, "output_tokens": 7})


class DispatchTests(unittest.TestCase):
    def test_get_provider_known_and_alias(self):
        self.assertIsInstance(providers.get_provider("anthropic"),
                              providers.AnthropicProvider)
        self.assertIsInstance(providers.get_provider("openai"),
                              providers.OpenAIProvider)
        self.assertIsInstance(providers.get_provider("gemini"),
                              providers.GoogleProvider)

    def test_get_provider_unknown_raises(self):
        with self.assertRaises(ValueError):
            providers.get_provider("llama-at-home")

    def test_default_provider_is_anthropic(self):
        with patch.dict("os.environ", {}, clear=False) as _:
            import os
            os.environ.pop("MDPLUS_ENGINE_PROVIDER", None)
            self.assertEqual(providers.get_provider().name, "anthropic")

    def test_tool_shapes_differ_per_provider(self):
        a = providers.AnthropicProvider()._tools()[0]
        o = providers.OpenAIProvider()._tools()[0]
        self.assertIn("input_schema", a)          # Anthropic shape
        self.assertEqual(o["type"], "function")   # OpenAI shape
        self.assertEqual(a["name"], "web_search")


if __name__ == "__main__":
    unittest.main()
