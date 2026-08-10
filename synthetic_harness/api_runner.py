"""Sustainable, unattended execution of a prepared web arm via a model API.

Why this module exists
----------------------
The original harness reached the model by shelling out to the `codex`/`claude`
CLI, which is authenticated by an *interactive login* that lives on the host.
That login token expires. An operator has to be around to refresh it, and a run
that outlives the token dies mid-flight. A service meant to run untouched for
months cannot depend on a session a human has to re-authenticate.

This engine talks to a model API directly, authenticated by an API **key** held
as a server secret. Nothing expires; nothing needs a human. It also removes the
CLI and the MCP subprocess entirely: the agent's only two capabilities --
`web_search` and `http_fetch` -- are ordinary in-process function calls here.
Because the tool loop is the only surface the model can act through, the
`web_only` isolation is intrinsic: there is no file tool, no shell, and no path
to the local library or the answer key.

Multi-provider
--------------
The tool loop itself is provider-independent and lives in `providers.py`, so the
identical task/tools/prompts run on Anthropic (Claude), OpenAI (GPT), or Google
(Gemini). Pick with `MDPLUS_ENGINE_PROVIDER` (or pass `provider=`). This is what
lets us measure which model grounds appeals most accurately — the moat — on a
level field.

Contract
--------
`run_api_arm()` returns the same shape as `run_claude_arm()`:
`{"returncode": 0}` on success (it wrote `result.json`), otherwise a non-zero
`returncode` and an `error` string. It writes the same sibling artifacts
(`agent_tool_trace.jsonl`, `agent_events.jsonl`, `agent_run_meta.json`).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import providers
from .integrity import write_json_atomic
from .agent_runner import (
    SYSTEM_PROMPT,
    claude_prompt,
    extract_json,
    _write_agent_events,
)

DEFAULT_API_MODEL = os.environ.get("MDPLUS_API_MODEL", "claude-opus-5")
# Bounds a single run's cost. The agent reads a handful of policy pages; a run
# that wants 40 tool round-trips is looping, not researching.
MAX_TOOL_ITERATIONS = int(os.environ.get("MDPLUS_MAX_TOOL_ITERATIONS", "40"))
MAX_OUTPUT_TOKENS = int(os.environ.get("MDPLUS_MAX_OUTPUT_TOKENS", "8000"))

# Per-arm text budget mirrors the MCP tool server (mcp_tools_server._call_tool).
_SEARCH_DEFAULT_COUNT = 5
_FETCH_MAX_TEXT_CHARS = 12000

# The Anthropic-shaped tool surface, kept as a re-export for callers/tests that
# reference it. The canonical, provider-independent definitions live in
# providers.CANONICAL_TOOLS.
API_TOOLS = providers.AnthropicProvider()._tools()


def api_available(provider: str | None = None) -> bool:
    """True when the engine can run: the selected provider's key is present and
    its SDK imports. Defaults to MDPLUS_ENGINE_PROVIDER, then Anthropic."""
    try:
        return providers.get_provider(provider).available()
    except ValueError:
        return False


class _ToolRunner:
    """Executes the two tools in-process and records a per-run JSONL trace.

    A fresh instance per arm keeps the call counter and log path local, so
    concurrent arms never share state (unlike the env-driven MCP logger).
    """

    def __init__(self, trace_path: Path, row_id: str):
        self._trace_path = trace_path
        self._row_id = row_id
        self._lock = threading.Lock()
        self._i = 0
        # Imported lazily so the module loads on hosts without `requests`.
        from policy_eval.webtools import fetch, search, SearchUnavailable

        self._fetch = fetch
        self._search = search
        self._search_unavailable = SearchUnavailable

    def _log(self, action: str, args: dict[str, Any], obs: dict[str, Any]) -> None:
        with self._lock:
            self._i += 1
            rec = {
                "i": self._i,
                "action": action,
                "args": args,
                "obs": obs,
                "row_id": self._row_id,
            }
            with self._trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "web_search":
            query = str(args.get("query", ""))
            count = int(args.get("count", _SEARCH_DEFAULT_COUNT) or _SEARCH_DEFAULT_COUNT)
            try:
                res = self._search(query, count)
            except self._search_unavailable as exc:
                res = {"error": str(exc), "result_count": 0, "results": []}
            self._log(
                "web_search",
                {"query": query, "count": count},
                {
                    "backend": res.get("backend"),
                    "result_count": res.get("result_count"),
                    "urls": [r.get("url") for r in res.get("results", [])],
                    "error": res.get("error"),
                },
            )
            return {
                "query": query,
                "results": res.get("results", []),
                "result_count": res.get("result_count", 0),
                "error": res.get("error"),
            }
        if name == "http_fetch":
            url = str(args.get("url", ""))
            res = self._fetch(url, max_text_chars=_FETCH_MAX_TEXT_CHARS)
            self._log(
                "http_fetch",
                {"url": url},
                {
                    "status": res["status"],
                    "final_url": res["final_url"],
                    "bytes": res["bytes"],
                    "sha256": res["sha256"],
                    "login_wall": res["login_wall"],
                    "error": res["error"],
                },
            )
            # Surface a blocked/unreadable fetch as an explicit error so the model
            # never reads an empty body as "the policy is not here."
            error = res["error"]
            if res.get("blocked") and not error:
                error = f"fetch blocked or unreadable: {res.get('blocked_reason')}"
            return {
                "url": url,
                "final_url": res["final_url"],
                "http_status": res["status"],
                "content_type": res["content_type"],
                "login_wall": res["login_wall"],
                "blocked": res.get("blocked", False),
                "blocked_reason": res.get("blocked_reason"),
                "error": error,
                "text": res["text"],
                "text_truncated": res["text_truncated"],
            }
        return {"error": f"unknown tool {name!r}"}


# The row/arm-level `timeout` argument is a TOTAL budget for the whole
# multi-turn tool loop, not a per-call one. Passing it straight through as the
# HTTP client's timeout was a real bug: the Anthropic SDK retries a hanging or
# failed request up to `max_retries` times with backoff, so ONE stuck call
# could take (per-call timeout) x (1 + max_retries) -- with a 900s row budget
# and the default 4 retries, a single bad connection could hang for over an
# hour, and the outer deadline check in _agent_loop only runs BETWEEN calls, so
# it never gets a chance to stop it. Capping the per-call timeout here, well
# under any realistic row budget, means the client's own retry ceiling is
# always in minutes, not hours, and the outer deadline check becomes
# meaningful again. Override with MDPLUS_API_CALL_TIMEOUT if a slower network
# genuinely needs more per-call headroom.
API_CALL_TIMEOUT = float(os.environ.get("MDPLUS_API_CALL_TIMEOUT", "120"))


def _client(timeout: int):
    """Anthropic client factory. Kept module-level (and patchable in tests) so
    the default/Anthropic path is unchanged by the multi-provider refactor."""
    import anthropic

    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=int(os.environ.get("MDPLUS_API_MAX_RETRIES", "4")),
        timeout=min(float(timeout), API_CALL_TIMEOUT),
    )


def _resolve(provider_name: str | None, model: str) -> tuple[Any, str]:
    """Pick the provider adapter and the effective model. When the caller left
    the model at the Anthropic default but selected another provider, fall back
    to that provider's own default model."""
    provider = providers.get_provider(provider_name)
    if provider.name != "anthropic" and (not model or model == DEFAULT_API_MODEL):
        model = provider.default_model()
    elif not model:
        model = provider.default_model()
    return provider, model


def _make_client(provider: Any, timeout: int) -> Any:
    # Anthropic goes through the module-level _client so existing tests that
    # patch it keep working; other providers build their own client.
    if provider.name == "anthropic":
        return _client(timeout)
    return provider.make_client(timeout)


def _repair_missing_sections(
    *,
    result: dict[str, Any],
    arm_dir: Path,
    provider: Any,
    client: Any,
    model: str,
    transcript: Any,
    usage: dict[str, int],
    deadline: float,
) -> dict[str, Any] | None:
    """Ask the SAME conversation for required fields the model left out.
    Mutates `result` in place. Provider-agnostic: the model call goes through
    `provider.continue_once`."""
    from .arms import result_contract

    required = result_contract()["required_top_level_fields"]
    controller_owned = {"episode_id", "arm"}
    missing = [f for f in required if f not in result and f not in controller_owned]
    if not missing:
        return None
    record: dict[str, Any] = {"missing": missing}
    if time.time() > deadline:
        record["outcome"] = "no time to repair"
        return record

    ask = (
        "Your previous answer stopped early and left out these required "
        "top-level fields: " + ", ".join(missing) + ". Do not repeat the work "
        "you already did and do not search again unless you must. Reply with ONE "
        "JSON object that contains ONLY those missing fields, filled in from the "
        "policy you already read. Use the same schema as before."
    )
    try:
        text = provider.continue_once(
            client=client, model=model, system=SYSTEM_PROMPT,
            transcript=transcript, ask=ask, usage=usage,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001
        record["outcome"] = f"repair request failed: {exc}"
        return record
    patch = extract_json(text) or {}
    filled = [f for f in missing if f in patch]
    for field in filled:
        result[field] = patch[field]
    record["filled"] = filled
    record["outcome"] = "repaired" if len(filled) == len(missing) else "partial"
    write_json_atomic(arm_dir / "repair_attempt.json", record)
    return record


def run_api_arm(
    arm_dir: Path,
    work_order: dict[str, Any],
    timeout: int = 1800,
    model: str = DEFAULT_API_MODEL,
    on_cost: Callable[[float], None] | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Run one prepared web arm to completion through the selected model API.

    `provider` selects Anthropic / OpenAI / Google (defaults to
    MDPLUS_ENGINE_PROVIDER, then Anthropic). `on_cost`, if given, is called once
    with the run's estimated USD cost so an orchestrator can enforce a budget.
    Returns the run-outcome dict.
    """
    arm = work_order["arm"]
    if arm != "web_only":
        return {
            "returncode": 2,
            "error": (
                f"the api engine supports web_only; {arm} needs local file "
                "tools that this engine deliberately does not expose"
            ),
        }
    try:
        prov, model = _resolve(provider, model)
    except ValueError as exc:
        return {"returncode": 3, "error": str(exc)}
    if not prov.available():
        return {
            "returncode": 3,
            "error": (
                f"{prov.key_env} is not set (or its SDK is missing); the "
                f"{prov.name} engine cannot run"
            ),
        }

    trace_path = arm_dir / "agent_tool_trace.jsonl"
    prompt = claude_prompt(work_order)
    usage = {"input_tokens": 0, "output_tokens": 0}
    started = time.time()
    deadline = started + timeout

    try:
        client = _make_client(prov, timeout)
        runner = _ToolRunner(trace_path, work_order["episode_id"])
        final_text, transcript, stop_reason = prov.run(
            client=client,
            model=model,
            system=SYSTEM_PROMPT,
            prompt=prompt,
            tool_call=runner.call,
            deadline=deadline,
            usage=usage,
            max_iters=MAX_TOOL_ITERATIONS,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001 - any API/SDK failure is a failed run
        elapsed = round(time.time() - started, 1)
        _write_agent_events(trace_path, arm_dir / "agent_events.jsonl")
        return {
            "returncode": 1,
            "error": f"{prov.name} engine failed: {exc}",
            "elapsed_s": elapsed,
        }

    elapsed = round(time.time() - started, 1)
    event_count = _write_agent_events(trace_path, arm_dir / "agent_events.jsonl")
    cost = _estimate_cost(usage)

    meta: dict[str, Any] = {
        "engine": "api",
        "provider": prov.name,
        "model": model,
        "elapsed_s": elapsed,
        "stop_reason": stop_reason,
        "usage": usage,
        "estimated_cost_usd": cost,
        "tool_events": event_count,
    }

    if final_text == "" and stop_reason in ("timeout", "max_iterations"):
        write_json_atomic(arm_dir / "agent_run_meta.json", meta)
        if on_cost:
            on_cost(cost)
        return {
            "returncode": 124 if stop_reason == "timeout" else 1,
            "error": f"agent did not produce a final answer ({stop_reason})",
            "elapsed_s": elapsed,
        }

    result = extract_json(final_text)
    if result is None:
        (arm_dir / "agent_stdout.txt").write_text(final_text[:200000], encoding="utf-8")
        write_json_atomic(arm_dir / "agent_run_meta.json", meta)
        if on_cost:
            on_cost(cost)
        return {
            "returncode": 1,
            "error": "agent final response contained no JSON object",
            "elapsed_s": elapsed,
        }

    repair = _repair_missing_sections(
        result=result,
        arm_dir=arm_dir,
        provider=prov,
        client=client,
        model=model,
        transcript=transcript,
        usage=usage,
        deadline=deadline,
    )
    if repair:
        meta["repair"] = repair
    meta["usage"] = usage
    meta["estimated_cost_usd"] = _estimate_cost(usage)
    write_json_atomic(arm_dir / "agent_run_meta.json", meta)
    if on_cost:
        on_cost(meta["estimated_cost_usd"])

    # The identifiers are the controller's to assert, not the model's.
    result["episode_id"] = work_order["episode_id"]
    result["arm"] = arm
    write_json_atomic(arm_dir / "result.json", result)
    return {"returncode": 0, "elapsed_s": elapsed}


def _estimate_cost(usage: dict[str, int]) -> float:
    """Rough USD estimate from token usage and configurable per-Mtok prices.

    Defaults are order-of-magnitude placeholders; set the env vars to your
    model's real published prices for accurate budget accounting.
    """
    in_price = float(os.environ.get("MDPLUS_PRICE_INPUT_PER_MTOK", "15"))
    out_price = float(os.environ.get("MDPLUS_PRICE_OUTPUT_PER_MTOK", "75"))
    cost = (
        usage.get("input_tokens", 0) / 1_000_000 * in_price
        + usage.get("output_tokens", 0) / 1_000_000 * out_price
    )
    return round(cost, 4)
