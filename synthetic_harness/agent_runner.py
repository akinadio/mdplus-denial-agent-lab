"""Autonomous execution of a prepared arm work order using the Claude CLI.

The original harness spawned `codex exec` wrapped in macOS `sandbox-exec`.
Neither binary exists on Linux, so no arm could ever run here. This module is
the Linux execution engine. It reuses the isolation pattern already proven by
scripts/policy_eval/retrieve.py:

  claude -p <prompt>
      --tools ""                 removes every built-in tool (no Read, no Bash)
      --mcp-config <file>        supplies exactly two tools: web_search, http_fetch
      --strict-mcp-config        ignores every other MCP server on this host
      --allowedTools / --disallowedTools   belt and braces on top of --tools ""
      cwd = a temp directory outside this repository

Because the agent has no file tools, it cannot write result.json itself. It
returns one JSON object on stdout and this module writes the arm artifacts.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .integrity import write_json_atomic
from . import policy_anchors

WORKSPACE = Path(__file__).resolve().parents[1]
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/home/clawd/.local/bin/claude")
MCP_SERVER = WORKSPACE / "scripts" / "policy_eval" / "mcp_tools_server.py"
DEFAULT_MODEL = os.environ.get("MDPLUS_AGENT_MODEL", "claude-opus-5")
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

SYSTEM_PROMPT = (
    "You are a health-insurance appeals researcher helping a patient whose "
    "procedure was denied. You have exactly two tools: web_search and "
    "http_fetch. You have no file access and no shell. Find the payer's own "
    "current coverage policy for the submitted procedure, read the document "
    "itself, and base every claim on what you actually read. Never present a "
    "form, code list, policy index, or routing page as the governing policy. "
    "An honest blocker scores better than a confident wrong answer. "
    "\n\nVOICE OF THE PATIENT- AND DOCTOR-FACING TEXT (the human-readable fields "
    "such as patient_interaction and next_steps): write in plain, warm, simple "
    "language a non-expert can follow on a phone. Keep the clinician on the "
    "patient's side: the surgeon documented that this procedure is needed, and "
    "the appeal's job is to show the payer's OWN published criteria are met. "
    "Frame the denial as the insurer's decision, measured against the insurer's "
    "own rules, that the patient and doctor can have reconsidered -- so the "
    "responsibility sits with the payer, not the patient or the doctor. Do this "
    "through calm, factual framing (\"the plan's own policy says X, and your "
    "records show X\"); do not use inflammatory, sarcastic, or explicitly "
    "accusatory language, and never promise coverage. "
    "\n\nYour final response must be exactly one JSON object and nothing else."
)


def engine_name() -> str:
    """Pick the execution engine for this host.

    Order of preference when unset (MDPLUS_AGENT_ENGINE=auto):
      1. "api"    -- an ANTHROPIC_API_KEY is present. This is the sustainable,
                     unattended path: key-authenticated, no expiring login, no
                     CLI or MCP subprocess. Preferred whenever available.
      2. "codex"  -- macOS with the codex CLI and sandbox-exec (legacy).
      3. "claude" -- the claude CLI fallback (interactive login; expires).
    """
    requested = os.environ.get("MDPLUS_AGENT_ENGINE", "auto")
    if requested != "auto":
        return requested
    # Imported here to avoid a hard dependency on the SDK at module load.
    from .api_runner import api_available

    if api_available():
        return "api"
    if shutil.which("codex") and shutil.which("sandbox-exec"):
        return "codex"
    return "claude"


def _transcript_text(work_order: dict[str, Any]) -> str:
    lines = []
    for row in work_order.get("patient_visible_transcript", []):
        lines.append(f"[{row.get('sequence')}] {row.get('sender')}: {row.get('body')}")
    return "\n\n".join(lines)


def claude_prompt(work_order: dict[str, Any]) -> str:
    """Build a self-contained prompt.

    The stock AGENT_PROMPT.txt tells the agent to read the work order off disk
    and write result.json itself. Under `--tools ""` it can do neither, so the
    case and the schema are embedded here instead.
    """
    arm = work_order["arm"]
    schema = json.dumps(work_order["result_schema"], ensure_ascii=False)
    objective = work_order.get("objective") or work_order.get(
        "source_boundary", {}
    ).get("objective", "")

    # A revision work order carries context that must not be dropped, or the
    # correction silently degrades into an ordinary fresh retrieval.
    revision = ""
    feedback = work_order.get("human_source_feedback")
    if feedback:
        revision += (
            "\nHUMAN SOURCE REVIEW (revision "
            f"{work_order.get('revision')}, decision: {feedback.get('decision')})\n"
            f"Reviewer notes: {feedback.get('notes', '')}\n"
            "Rejected source: "
            f"{json.dumps(feedback.get('rejected_source'), ensure_ascii=False)}\n"
            "Do not reuse the rejected source and do not preserve a conclusion "
            "merely because it appeared in the prior result. Exclude the rejected "
            "source explicitly and retrieve again.\n"
        )
    answered = work_order.get("answered_question")
    if answered:
        revision += (
            f"\nPATIENT ANSWERED A FOLLOW-UP\nQuestion: {answered.get('question')}\n"
            f"Answer: {answered.get('answer')}\n"
        )
    locked = work_order.get("locked_selected_source")
    if locked:
        revision += (
            "\nLOCKED SOURCE\nKeep this already-reviewed source as the selected "
            "source and revise the analysis around the new answer:\n"
            f"{json.dumps(locked, ensure_ascii=False)}\n"
        )
    prior = work_order.get("prior_result")
    if prior:
        revision += (
            "\nPRIOR RESULT (for revision only)\n"
            f"{json.dumps(prior, ensure_ascii=False)}\n"
        )

    from .arms import known_citation_hint_block

    revision += known_citation_hint_block(work_order.get("known_citation_hint"))

    return f"""You are the {arm} retrieval and denial-navigation agent.

EPISODE
- episode_id: {work_order['episode_id']}
- case_id: {work_order.get('case_id')}
- arm: {arm}

OBJECTIVE
{objective}

PATIENT-VISIBLE SUBMISSION
{_transcript_text(work_order)}
{revision}{policy_anchors.anchors_prompt_block(work_order.get("policy_anchors") or [])}
OPERATING RULES
1. Treat the submission as real. Do not assume facts that were not supplied.
2. First normalize payer, product clues, state, procedure, CPT if present, dates,
   and the stated denial language.
3. Perform a genuine retrieval attempt with web_search and http_fetch.
4. Prefer the exact current official payer policy. Verify payer entity, product,
   state, procedure, effective date, and delegated vendor applicability.
5. Label every candidate with evidence_role. A form, code list, policy index, or
   routing guide is supporting_document, never governing_policy.
6. Record every serious candidate and a concise observable reason for selecting
   or rejecting it. Never include private chain-of-thought.
7. Read the selected document itself. Do not rely on uncited summaries.
8. Distinguish missing documentation, genuinely unmet criteria, administrative
   denial, benefit exclusion, investigational denial, site-of-service issue, and
   unresolved uncertainty.
9. Ask only questions a patient can reasonably answer. Route chart-dependent
   facts to the provider.
10. Recommend the most immediately actionable evidence-supported next step that
    favors the patient. Do not promise coverage and do not invent a deadline.
11. Use status "blocked" only after recording attempted candidates and a concrete
    external blocker. It must never mean that work was not attempted.

OUTPUT
Your final response must be exactly one JSON object conforming to this schema.
Do not wrap it in Markdown fences and do not add commentary before or after it.

{schema}
"""


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
    for candidate in reversed(candidates):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "retrieval" in obj and "status" in obj:
            return obj
    for candidate in reversed(candidates):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _write_agent_events(tool_log: Path, destination: Path) -> int:
    """Translate the MCP tool trace into events the harness can ingest."""
    if not tool_log.exists():
        return 0
    rows = []
    for line in tool_log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        action = rec.get("action", "tool_call")
        args = rec.get("args", {})
        obs = rec.get("obs", {}) or {}
        if action == "web_search":
            summary = f"Searched the web for: {args.get('query', '')}"
        elif action == "http_fetch":
            summary = (
                f"Fetched {args.get('url', '')} "
                f"(HTTP {obs.get('status')})"
            )
        else:
            summary = f"Agent tool call: {action}"
        rows.append(
            {
                "event_type": action,
                "status": "failed" if obs.get("error") else "recorded",
                "summary": summary[:500],
                "artifacts": [],
                "sequence": rec.get("i"),
                "args": args,
                "observation": obs,
            }
        )
    if not rows:
        return 0
    with destination.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def run_claude_arm(
    arm_dir: Path,
    work_order: dict[str, Any],
    timeout: int = 1800,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Run one prepared arm to completion and write its artifacts.

    Returns a dict with `returncode` (0 means the arm produced result.json) and
    an `error` string when it did not.
    """
    arm = work_order["arm"]
    if arm != "web_only":
        return {
            "returncode": 2,
            "error": (
                f"the claude engine supports web_only; {arm} needs local file "
                "tools that this isolation profile removes"
            ),
        }

    workdir = Path(tempfile.mkdtemp(prefix="mdplus_arm_"))
    tool_log = arm_dir / "agent_tool_trace.jsonl"
    mcp_config = workdir / "mcp.json"
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
        ),
        encoding="utf-8",
    )

    prompt = claude_prompt(work_order)

    def build_argv(text: str, resume: str | None = None) -> list[str]:
        head = [CLAUDE_BIN, "-p", text]
        if resume:
            head += ["--resume", resume]
        return head + [
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

    argv = build_argv(prompt)
    env = dict(os.environ)
    env["POLICY_EVAL_TOOL_LOG"] = str(tool_log)
    env["POLICY_EVAL_ROW_ID"] = work_order["episode_id"]
    env["PYTHONPATH"] = str(WORKSPACE / "scripts")

    started = time.time()
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
        shutil.rmtree(workdir, ignore_errors=True)
        return {
            "returncode": 124,
            "error": f"agent timed out after {timeout}s",
            "elapsed_s": round(time.time() - started, 1),
        }

    elapsed = round(time.time() - started, 1)
    (arm_dir / "agent_stderr.log").write_text(proc.stderr[:200000], encoding="utf-8")
    event_count = _write_agent_events(tool_log, arm_dir / "agent_events.jsonl")

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        (arm_dir / "agent_stdout.txt").write_text(
            proc.stdout[:200000], encoding="utf-8"
        )
        shutil.rmtree(workdir, ignore_errors=True)
        return {
            "returncode": proc.returncode or 1,
            "error": "agent output was not a valid JSON envelope",
            "elapsed_s": elapsed,
        }

    meta = {
        "engine": "claude",
        "model": model,
        "elapsed_s": elapsed,
        "num_turns": envelope.get("num_turns"),
        "session_id": envelope.get("session_id"),
        "total_cost_usd": envelope.get("total_cost_usd"),
        "permission_denials": envelope.get("permission_denials"),
        "is_error": envelope.get("is_error"),
        "api_error_status": envelope.get("api_error_status"),
        "tool_events": event_count,
        "argv": [a if a != prompt else "<prompt>" for a in argv],
    }
    write_json_atomic(arm_dir / "agent_run_meta.json", meta)

    if envelope.get("is_error"):
        shutil.rmtree(workdir, ignore_errors=True)
        return {
            "returncode": 1,
            "error": f"agent reported an error: {envelope.get('api_error_status')}",
            "elapsed_s": elapsed,
        }

    result = extract_json(envelope.get("result", ""))
    if result is None:
        (arm_dir / "agent_stdout.txt").write_text(
            (envelope.get("result") or "")[:200000], encoding="utf-8"
        )
        shutil.rmtree(workdir, ignore_errors=True)
        return {
            "returncode": 1,
            "error": "agent final response contained no JSON object",
            "elapsed_s": elapsed,
        }

    # A long answer sometimes stops after the retrieval sections, which failed the
    # whole run and threw away several minutes of correct research. Ask the SAME
    # session for the missing sections instead, so the agent still has the policy
    # it already read and does not have to search again.
    repair = _repair_missing_sections(
        result, arm_dir, build_argv=build_argv, workdir=workdir,
        session_id=envelope.get("session_id"), env=env, timeout=timeout,
    )
    shutil.rmtree(workdir, ignore_errors=True)
    if repair:
        meta["repair"] = repair
        write_json_atomic(arm_dir / "agent_run_meta.json", meta)

    # The identifiers are the controller's to assert, not the model's.
    result["episode_id"] = work_order["episode_id"]
    result["arm"] = arm
    write_json_atomic(arm_dir / "result.json", result)
    return {"returncode": 0, "elapsed_s": elapsed}


def _repair_missing_sections(
    result: dict[str, Any],
    arm_dir: Path,
    build_argv,
    workdir: Path,
    session_id: str | None,
    env: dict[str, str],
    timeout: int,
) -> dict[str, Any] | None:
    """Ask the same session to supply top-level sections it left out.

    Mutates `result` in place. Returns a record of what was attempted, or None
    when nothing was missing. Runs at most once.
    """
    from .arms import result_contract

    required = result_contract()["required_top_level_fields"]
    controller_owned = {"episode_id", "arm"}
    missing = [f for f in required if f not in result and f not in controller_owned]
    if not missing:
        return None
    record: dict[str, Any] = {"missing": missing, "session_id": session_id}
    if not session_id:
        record["outcome"] = "no session to resume"
        return record

    ask = (
        "Your previous answer stopped early and left out these required "
        "top-level fields: " + ", ".join(missing) + ". Do not repeat the work you "
        "already did and do not search again unless you must. Reply with ONE JSON "
        "object that contains ONLY those missing fields, filled in from the policy "
        "you already read. Use the same schema as before."
    )
    started = time.time()
    try:
        proc = subprocess.run(
            build_argv(ask, resume=session_id),
            cwd=str(workdir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        record["outcome"] = "repair timed out"
        return record
    record["elapsed_s"] = round(time.time() - started, 1)
    try:
        patch = extract_json(json.loads(proc.stdout).get("result", "")) or {}
    except (json.JSONDecodeError, AttributeError):
        patch = {}
    filled = [f for f in missing if f in patch]
    for field in filled:
        result[field] = patch[field]
    record["filled"] = filled
    record["outcome"] = "repaired" if len(filled) == len(missing) else "partial"
    write_json_atomic(arm_dir / "repair_attempt.json", record)
    return record
