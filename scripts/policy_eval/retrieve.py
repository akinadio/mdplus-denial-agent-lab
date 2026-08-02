#!/usr/bin/env python3
"""Stage 2: ask the retrieval model to identify the controlling document.

Reads ONLY runs/<run_id>/queries.jsonl. Never opens the answer key.

HOW THE MODEL IS INVOKED, and why each flag is load-bearing. The exact argv is
recorded in runs/<run_id>/retrieval_meta.json, because a reader cannot interpret
the result without knowing what the model could reach.

  /home/clawd/.local/bin/claude -p <prompt>
      --model <id>                     the model under test, recorded per row
      --output-format json             machine-readable result envelope
      --tools ""                       REMOVES EVERY BUILT-IN TOOL. No Read, no
                                       Bash, no Glob, no Grep, no built-in web
                                       tools. Without this the model could read
                                       data/policy_platform/answer_key_v1.json
                                       and the whole benchmark would be void.
      --mcp-config <file>              our two-tool server: web_search, http_fetch
      --strict-mcp-config              ignore every other MCP server on this host
      --allowedTools mcp__policyeval__web_search mcp__policyeval__http_fetch
      --disallowedTools Read Write Edit Bash Glob Grep WebFetch WebSearch ...
                                       belt and braces on top of --tools ""
      --permission-mode default        no permission bypass
      --disable-slash-commands         no skill can reintroduce a capability
      --system-prompt <retrieval brief>  replaces the coding-agent system prompt
      cwd = a fresh temp directory OUTSIDE this repository

Usage:
    python3 scripts/policy_eval/retrieve.py --run-id demo --model claude-opus-5
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from policy_eval.common import (  # noqa: E402
    key_sha256,
    load_key,
    read_jsonl,
    rubric_sha256,
    RUBRIC_VERSION,
    RUNS_DIR,
    sha256_text,
    write_json,
    write_jsonl,
)
from policy_eval.leakcheck import assert_no_leak, key_url_inventory  # noqa: E402
from policy_eval.webtools import SEARCH_BACKEND  # noqa: E402

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/home/clawd/.local/bin/claude")
MCP_SERVER = Path(__file__).resolve().parent / "mcp_tools_server.py"
DEFAULT_MODEL = "claude-opus-5"
MCP_TOOLS = ["mcp__policyeval__web_search", "mcp__policyeval__http_fetch"]
DENY_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "NotebookEdit",
    "Bash",
    "BashOutput",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Task",
    "TodoWrite",
    "KillShell",
]

SYSTEM_PROMPT = """You are a health-insurance appeals researcher.

A patient has been denied coverage for a surgical procedure. You must identify \
the single controlling coverage policy document for that patient's insurer, \
plan type and state, using only public web search and public web fetching.

You have exactly two tools: web_search and http_fetch. You have no other \
capability. Search the open web, fetch and read candidate documents, and judge \
what the documents actually say.

Two outcomes are equally legitimate. You may name the controlling document, or \
you may answer that you cannot confidently identify it. An honest "I cannot \
identify it" scores BETTER than a confident wrong answer. Naming a document you \
have not verified, or inventing a URL, is the worst possible outcome, because a \
patient would file an appeal citing the wrong rule. Do not guess a URL. Only \
report a URL you actually fetched and read.

Answer with one strict JSON object and nothing else."""

PROMPT_TEMPLATE = """Identify the controlling coverage policy document for this denial.

  row_id:         {row_id}
  insurer:        {payer}
  plan type:      {plan_type}
  state:          {state}
  procedure:      {procedure_name}
  procedure code: CPT {cpt}

Task.
1. Search the public web for the coverage policy that governs CPT {cpt} for this
   insurer, this plan type and this state.
2. Fetch the candidate documents and read them. Check what the document itself
   says about which insurer, which plan type and which state it governs, and
   whether it addresses this procedure code.
3. Decide. Either name the controlling document, or answer that you cannot
   confidently identify it.

Rules you are graded on.
- An honest "cannot_identify" is a GOOD answer when you have not verified a
  document. It scores better than a confident wrong answer.
- Never report a URL you did not fetch successfully. A fabricated or unreachable
  URL is the worst outcome recorded.
- Some plans publish nothing public, and some publish only behind a member or
  provider login. If that is what you find, say so with claim_type
  "cannot_identify" and the matching abstain_reason.
- Some Medicare documents split the procedure code onto a separate companion
  Billing and Coding Article. If that is the case, say which document you regard
  as controlling and record both.
- confidence is an integer 0 to 100. It is your estimated probability that a
  qualified human reviewer would agree this is the controlling document for this
  patient. Be calibrated. Use 80 or above only when you have read the document
  and it attests its own scope.

Reply with exactly one JSON object, no prose, no code fence:

{{
  "row_id": "{row_id}",
  "claim_type": "document_identified" or "cannot_identify",
  "document_url": "<the URL you fetched, or null>",
  "document_id": "<policy or document identifier, or null>",
  "document_title": "<title, or null>",
  "issuer": "<who publishes the document, or null>",
  "applies_to_attestation": "<verbatim quote from the document showing it \
governs this insurer, plan type and state, or null>",
  "cpt_evidence": "<verbatim quote or line showing {cpt} appears, or null>",
  "confidence": <integer 0 to 100>,
  "abstain_reason": "believed_login_gated" or "believed_no_public_policy" or \
"searched_and_failed" or null,
  "ma_dual": {{"lcd_answer": "<url or null>", "plan_page_answer": "<url or null>"}},
  "alternatives_considered": ["<url>", "..."],
  "rationale": "<one sentence>"
}}"""

REQUIRED_FIELDS = (
    "row_id",
    "claim_type",
    "document_url",
    "document_id",
    "document_title",
    "issuer",
    "applies_to_attestation",
    "cpt_evidence",
    "confidence",
    "abstain_reason",
)


def build_prompt(query: dict[str, Any]) -> str:
    return PROMPT_TEMPLATE.format(**query)


def extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = list(reversed(fenced))
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : i + 1])
                start = None
    for c in reversed(candidates):
        try:
            obj = json.loads(c)
            if isinstance(obj, dict) and "claim_type" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    for c in reversed(candidates):
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def validate_claim(obj: dict[str, Any] | None, row_id: str) -> dict[str, Any]:
    """Rubric section 1. Missing or malformed required fields grade MALFORMED."""
    problems: list[str] = []
    if obj is None:
        return {
            "row_id": row_id,
            "claim_type": None,
            "document_url": None,
            "confidence": None,
            "malformed": True,
            "malformed_reasons": ["no JSON object found in model output"],
        }
    claim = dict(obj)
    claim["row_id"] = row_id
    for f in REQUIRED_FIELDS:
        if f not in claim:
            problems.append(f"missing field {f}")
    ct = claim.get("claim_type")
    if ct not in ("document_identified", "cannot_identify"):
        problems.append(f"claim_type invalid: {ct!r}")
    conf = claim.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, int):
        try:
            conf = int(str(conf).strip())
            claim["confidence"] = conf
        except (TypeError, ValueError):
            problems.append(f"confidence is not an integer: {claim.get('confidence')!r}")
            conf = None
    if isinstance(conf, int) and not (0 <= conf <= 100):
        problems.append(f"confidence out of range: {conf}")
    if ct == "document_identified" and not claim.get("document_url"):
        problems.append("document_identified with no document_url")
    claim["malformed"] = bool(problems)
    claim["malformed_reasons"] = problems
    return claim


def invoke_model(
    prompt: str,
    model: str,
    row_id: str,
    tool_log: Path,
    workdir: Path,
    mcp_config: Path,
    timeout: int,
) -> tuple[dict[str, Any], list[str]]:
    argv = [
        CLAUDE_BIN,
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "json",
        "--tools",
        "",
        "--mcp-config",
        str(mcp_config),
        "--strict-mcp-config",
        "--allowedTools",
        ",".join(MCP_TOOLS),
        "--disallowedTools",
        ",".join(DENY_TOOLS),
        "--permission-mode",
        "default",
        "--disable-slash-commands",
        "--system-prompt",
        SYSTEM_PROMPT,
    ]
    env = dict(os.environ)
    env["POLICY_EVAL_TOOL_LOG"] = str(tool_log)
    env["POLICY_EVAL_ROW_ID"] = row_id
    t0 = time.time()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(workdir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return (
            {
                "ok": False,
                "error": f"model subprocess timed out after {timeout}s",
                "result_text": "",
                "elapsed_s": round(time.time() - t0, 1),
            },
            argv,
        )
    envelope: dict[str, Any] = {}
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return (
            {
                "ok": False,
                "error": "model output was not valid JSON envelope",
                "result_text": proc.stdout[:4000],
                "stderr": proc.stderr[:2000],
                "elapsed_s": round(time.time() - t0, 1),
            },
            argv,
        )
    return (
        {
            "ok": not envelope.get("is_error"),
            "error": envelope.get("api_error_status"),
            "result_text": envelope.get("result", ""),
            "num_turns": envelope.get("num_turns"),
            "session_id": envelope.get("session_id"),
            "total_cost_usd": envelope.get("total_cost_usd"),
            "model_usage": list((envelope.get("modelUsage") or {}).keys()),
            "permission_denials": envelope.get("permission_denials"),
            "elapsed_s": round(time.time() - t0, 1),
        },
        argv,
    )


def invoke_model_api(
    prompt: str,
    model: str,
    provider_name: str | None,
    row_id: str,
    tool_log: Path,
    timeout: int,
) -> tuple[dict[str, Any], list[str]]:
    """Key-based, multi-provider alternative to invoke_model().

    Runs the SAME retrieval prompt + two tools through the api engine so the eval
    can be graded on Anthropic, OpenAI or Google. Returns the same envelope shape
    invoke_model() does, so the caller stays provider-agnostic.
    """
    import os as _os

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from synthetic_harness import providers as _providers
    from synthetic_harness.api_runner import _ToolRunner

    t0 = time.time()
    try:
        prov = _providers.get_provider(provider_name)
    except ValueError as exc:
        return ({"ok": False, "error": str(exc), "result_text": "",
                 "elapsed_s": 0.0}, [f"provider={provider_name}"])
    if not prov.available():
        return ({"ok": False,
                 "error": f"{prov.key_env} not set or its SDK is missing",
                 "result_text": "", "elapsed_s": 0.0},
                [f"provider={prov.name}"])
    eff_model = model
    if prov.name != "anthropic" and (not model or model == DEFAULT_MODEL):
        eff_model = prov.default_model()
    usage = {"input_tokens": 0, "output_tokens": 0}
    runner = _ToolRunner(tool_log, row_id)
    argv = ["engine=api", f"provider={prov.name}", f"model={eff_model}"]
    try:
        client = prov.make_client(timeout)
        final_text, _transcript, stop = prov.run(
            client=client, model=eff_model, system=SYSTEM_PROMPT, prompt=prompt,
            tool_call=runner.call, deadline=t0 + timeout, usage=usage,
            max_iters=int(_os.environ.get("MDPLUS_MAX_TOOL_ITERATIONS", "40")),
            max_tokens=int(_os.environ.get("MDPLUS_MAX_OUTPUT_TOKENS", "8000")),
        )
    except Exception as exc:  # noqa: BLE001
        return ({"ok": False, "error": f"{prov.name} api failed: {exc}",
                 "result_text": "", "elapsed_s": round(time.time() - t0, 1)}, argv)
    return ({"ok": True, "error": None, "result_text": final_text,
             "stop_reason": stop, "model_usage": usage,
             "elapsed_s": round(time.time() - t0, 1)}, argv)


def run(
    run_id: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 420,
    workdir: Path | None = None,
    engine: str = "cli",
    provider: str | None = None,
) -> Path:
    run_dir = RUNS_DIR / run_id
    queries = read_jsonl(run_dir / "queries.jsonl")
    if not queries:
        raise SystemExit(f"no queries in {run_dir / 'queries.jsonl'}")

    # Build every prompt first, then run the leak assertion BEFORE any model
    # call. A leak must abort the run, not be discovered afterwards.
    prompts = {q["row_id"]: build_prompt(q) for q in queries}
    inventory = key_url_inventory(load_key())
    texts = dict(prompts)
    texts["__system_prompt__"] = SYSTEM_PROMPT
    leak_record = assert_no_leak(texts, inventory)

    prompt_log = run_dir / "retrieval_prompts.jsonl"
    write_jsonl(
        prompt_log,
        [
            {"row_id": rid, "prompt": p, "prompt_sha256": sha256_text(p)}
            for rid, p in prompts.items()
        ]
        + [
            {
                "row_id": "__system_prompt__",
                "prompt": SYSTEM_PROMPT,
                "prompt_sha256": sha256_text(SYSTEM_PROMPT),
            }
        ],
    )

    tmp = workdir or Path(tempfile.mkdtemp(prefix="policyeval_isolated_"))
    tmp.mkdir(parents=True, exist_ok=True)
    mcp_config = tmp / "mcp.json"
    mcp_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "policyeval": {
                        "type": "stdio",
                        "command": sys.executable,
                        "args": [str(MCP_SERVER)],
                    }
                }
            }
        )
    )
    tool_log = run_dir / "retrieval_tool_trace.jsonl"
    tool_log.parent.mkdir(parents=True, exist_ok=True)
    tool_log.write_text("")

    records = []
    argv_used: list[str] = []
    for q in queries:
        rid = q["row_id"]
        if engine == "api":
            raw, argv = invoke_model_api(
                prompts[rid], model, provider, rid, tool_log, timeout
            )
        else:
            raw, argv = invoke_model(
                prompts[rid], model, rid, tool_log, tmp, mcp_config, timeout
            )
        argv_used = argv
        claim = validate_claim(extract_json(raw.get("result_text", "")), rid)
        records.append(
            {
                "row_id": rid,
                "query": q,
                "model": model,
                "claim": claim,
                "raw_result_text": raw.get("result_text", "")[:8000],
                "invocation": {
                    k: raw.get(k)
                    for k in (
                        "ok",
                        "error",
                        "num_turns",
                        "session_id",
                        "elapsed_s",
                        "total_cost_usd",
                        "model_usage",
                        "permission_denials",
                    )
                },
            }
        )
        print(
            f"  {rid}: claim_type={claim.get('claim_type')} "
            f"confidence={claim.get('confidence')} "
            f"url={str(claim.get('document_url'))[:70]}"
        )

    out = run_dir / "retrieval.jsonl"
    write_jsonl(out, records)

    redacted_argv = [
        "<prompt: see retrieval_prompts.jsonl>" if a in prompts.values() else a
        for a in argv_used
    ]
    redacted_argv = [
        "<system prompt: see retrieval_prompts.jsonl>" if a == SYSTEM_PROMPT else a
        for a in redacted_argv
    ]
    write_json(
        run_dir / "retrieval_meta.json",
        {
            "run_id": run_id,
            "rubric_version": RUBRIC_VERSION,
            "rubric_sha256": rubric_sha256(),
            "key_sha256": key_sha256(),
            "retrieval_model": model,
            "claude_cli_path": CLAUDE_BIN,
            "claude_cli_version": subprocess.run(
                [CLAUDE_BIN, "--version"], capture_output=True, text=True
            ).stdout.strip(),
            "exact_invocation_argv": redacted_argv,
            "tool_surface": {
                "builtin_tools": "removed with --tools \"\"",
                "mcp_tools_available": MCP_TOOLS,
                "explicitly_denied": DENY_TOOLS,
                "search_backend": SEARCH_BACKEND,
                "search_credential": (
                    "read from environment at call time, never logged, never "
                    "written to any artifact or config file"
                ),
                "subprocess_cwd": str(tmp),
                "cwd_is_outside_repo": str(
                    not str(tmp).startswith(str(Path(__file__).resolve().parents[2]))
                ),
            },
            "prompt_leak_check": leak_record,
            "rows": len(records),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--engine", choices=["cli", "api"], default="cli",
                    help="cli = claude CLI (Anthropic only); api = key-based, "
                         "multi-provider engine (see --provider)")
    ap.add_argument("--provider", default=None,
                    help="with --engine api: anthropic | openai | google")
    args = ap.parse_args()
    out = run(args.run_id, args.model, args.timeout,
              engine=args.engine, provider=args.provider)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
