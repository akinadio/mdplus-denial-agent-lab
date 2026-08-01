"""Sustainable, unattended execution of a prepared arm via the Anthropic API.

Why this module exists
----------------------
The original harness reached the model by shelling out to the `codex`/`claude`
CLI, which is authenticated by an *interactive login* that lives on the host.
That login token expires. An operator has to be around to refresh it, and a run
that outlives the token dies mid-flight (this actually happened in the eval
board's T021 probe). A service that is meant to run untouched for months cannot
depend on a session that a human has to re-authenticate.

This engine talks to the Messages API directly, authenticated by an API **key**
held as a server secret (`ANTHROPIC_API_KEY`). Nothing expires; nothing needs a
human. It also removes the CLI and the MCP subprocess entirely: the agent's only
two capabilities -- `web_search` and `http_fetch` -- are ordinary in-process
function calls here. Because the tool loop is the only surface the model can act
through, the `web_only` isolation is intrinsic: there is no file tool, no shell,
and no path to the local library or the answer key. The macOS `sandbox-exec`
barrier is therefore unnecessary for this engine.

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

# Anthropic tool schemas. Identical capability surface to the MCP server, but
# expressed with the API's `input_schema` key.
API_TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Search the public web. Returns up to `count` results, each with a "
            "title, a URL and a snippet. Use this to find candidate insurer or "
            "Medicare coverage policy documents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "count": {
                    "type": "integer",
                    "description": "Number of results, 1 to 20. Default 5.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "http_fetch",
        "description": (
            "Fetch a public URL over HTTP GET and return the HTTP status, the "
            "final URL after redirects, the content type and the extracted text "
            "(HTML and PDF supported). Use this to read a candidate policy "
            "document and check what it actually says."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute http(s) URL."}
            },
            "required": ["url"],
        },
    },
]


def api_available() -> bool:
    """True when this engine can run: a key is present and the SDK imports."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:  # pragma: no cover - import availability is environment-dependent
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


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


def _client(timeout: int):
    import anthropic

    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=int(os.environ.get("MDPLUS_API_MAX_RETRIES", "4")),
        timeout=float(timeout),
    )


def _text_from_content(content: list[Any]) -> str:
    parts = []
    for block in content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


def _agent_loop(
    *,
    client: Any,
    model: str,
    system_prompt: str,
    prompt: str,
    tools_call: Callable[[str, dict[str, Any]], dict[str, Any]],
    deadline: float,
    usage: dict[str, int],
) -> tuple[str, list[dict[str, Any]], str]:
    """Drive the tool-use conversation to a final text answer.

    Returns (final_text, messages, stop_reason). `messages` is the full running
    transcript so the caller can continue the same conversation for a repair
    round. `usage` accumulates input/output tokens across every request.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    final_text = ""
    stop_reason = "max_iterations"

    for _ in range(MAX_TOOL_ITERATIONS):
        if time.time() > deadline:
            stop_reason = "timeout"
            break
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system_prompt,
            tools=API_TOOLS,
            messages=messages,
        )
        u = getattr(response, "usage", None)
        if u is not None:
            usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
            usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        stop_reason = response.stop_reason
        # Persist the assistant turn verbatim so tool_result ids line up.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            final_text = _text_from_content(response.content)
            break

        tool_results = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            out = tools_call(block.name, dict(block.input or {}))
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(out, ensure_ascii=False),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return final_text, messages, stop_reason


def _repair_missing_sections_api(
    *,
    result: dict[str, Any],
    arm_dir: Path,
    client: Any,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    usage: dict[str, int],
    deadline: float,
) -> dict[str, Any] | None:
    """Ask the SAME conversation for required fields the model left out.

    Mirrors agent_runner._repair_missing_sections but continues the API
    transcript instead of resuming a CLI session. Mutates `result` in place.
    """
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
    messages = messages + [{"role": "user", "content": ask}]
    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system_prompt,
            tools=API_TOOLS,
            messages=messages,
        )
    except Exception as exc:  # noqa: BLE001
        record["outcome"] = f"repair request failed: {exc}"
        return record
    u = getattr(response, "usage", None)
    if u is not None:
        usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
        usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
    patch = extract_json(_text_from_content(response.content)) or {}
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
) -> dict[str, Any]:
    """Run one prepared web arm to completion through the Anthropic API.

    `on_cost`, if given, is called once with the run's estimated USD cost so an
    orchestrator can enforce a spend budget. Returns the run-outcome dict.
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
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {
            "returncode": 3,
            "error": "ANTHROPIC_API_KEY is not set; the api engine cannot run",
        }

    trace_path = arm_dir / "agent_tool_trace.jsonl"
    prompt = claude_prompt(work_order)
    usage = {"input_tokens": 0, "output_tokens": 0}
    started = time.time()
    deadline = started + timeout

    try:
        client = _client(timeout)
        runner = _ToolRunner(trace_path, work_order["episode_id"])
        final_text, messages, stop_reason = _agent_loop(
            client=client,
            model=model,
            system_prompt=SYSTEM_PROMPT,
            prompt=prompt,
            tools_call=runner.call,
            deadline=deadline,
            usage=usage,
        )
    except Exception as exc:  # noqa: BLE001 - any API/SDK failure is a failed run
        elapsed = round(time.time() - started, 1)
        _write_agent_events(trace_path, arm_dir / "agent_events.jsonl")
        return {
            "returncode": 1,
            "error": f"api engine failed: {exc}",
            "elapsed_s": elapsed,
        }

    elapsed = round(time.time() - started, 1)
    event_count = _write_agent_events(trace_path, arm_dir / "agent_events.jsonl")
    cost = _estimate_cost(usage)

    meta: dict[str, Any] = {
        "engine": "api",
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

    repair = _repair_missing_sections_api(
        result=result,
        arm_dir=arm_dir,
        client=client,
        model=model,
        system_prompt=SYSTEM_PROMPT,
        messages=messages,
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
