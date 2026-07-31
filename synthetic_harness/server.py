"""Local internal UI and API for synthetic-patient denial episodes."""

from __future__ import annotations

import json
import argparse
import hashlib
import os
import subprocess
import threading
import traceback
import mimetypes
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .arms import (
    PLATFORM_ROOT,
    SOURCE_LIBRARY_ROOT,
    prepare_arm,
    prepare_correction_arm,
    prepare_follow_up_arm,
)
from .adjudication import latest_adjudication, record_adjudication
from .agent_runner import engine_name, run_claude_arm
from .api_runner import run_api_arm
from .appeal_letter import assess_letter, generate_appeal_letter
from .episode import Episode
from .evaluation import (
    evaluation_eligibility,
    load_verdict,
    prepare_evaluation,
    validate_verdict,
)
from .integrity import read_jsonl, utc_now, write_json_atomic
from .letter_reader import decode_attachments, save_uploads, transcribe
from .metrics import build_metrics
from .results import ingest_arm_result
from .run_log import build_record, log_run_async
from .source_review import (
    latest_source_reviews,
    record_source_review,
    source_fingerprint,
    source_document_for_review,
    source_url_for_review,
)
from .sandboxing import write_web_read_barrier
from .reliability import (
    alert,
    build_health,
    configure_logging,
    reconcile_interrupted_runs,
)
from contextlib import contextmanager

WORKSPACE = Path(__file__).resolve().parents[1]
EPISODES_ROOT = Path(
    os.environ.get(
        "MDPLUS_EPISODES_ROOT",
        WORKSPACE / "outputs" / "synthetic_patient_simulations" / "episodes",
    )
).expanduser().resolve()
UI_DIST = WORKSPACE / "ui" / "dist"
PATIENT_UI = WORKSPACE / "mockups"
RUNS: dict[str, dict[str, Any]] = {}
RUNS_LOCK = threading.Lock()
EVALUATION_RUNS: dict[str, dict[str, Any]] = {}
SERVER_STARTED_AT = utc_now()

# --- Concurrency cap -------------------------------------------------------
# Every arm launch is expensive (a full model run doing live web retrieval).
# Without a bound, N simultaneous patients spawn 2N heavy runs and exhaust the
# box. This semaphore caps how many arms execute at once; excess launches wait
# their turn instead of piling on. Tune with MDPLUS_MAX_CONCURRENT_ARMS.
MAX_CONCURRENT_ARMS = max(1, int(os.environ.get("MDPLUS_MAX_CONCURRENT_ARMS", "4")))
ARM_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_ARMS)
_ACTIVE_ARMS = {"n": 0}
_ACTIVE_LOCK = threading.Lock()


@contextmanager
def arm_slot():
    """Acquire a concurrency slot and track how many arms are running.

    Blocks until a slot is free, so simultaneous patients queue instead of
    overwhelming the host. The active count feeds /api/health.
    """
    ARM_SEMAPHORE.acquire()
    with _ACTIVE_LOCK:
        _ACTIVE_ARMS["n"] += 1
    try:
        yield
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_ARMS["n"] -= 1
        ARM_SEMAPHORE.release()


def active_arm_count() -> int:
    with _ACTIVE_LOCK:
        return _ACTIVE_ARMS["n"]

# --- Spend guard -----------------------------------------------------------
# A rolling daily estimate of model spend (the api engine reports per-run cost).
# When MDPLUS_DAILY_BUDGET_USD is set and the estimate exceeds it, new arms are
# refused until the window rolls over. This is in-process and resets on restart;
# a durable, DB-backed budget is the production version (see the checklist).
DAILY_BUDGET_USD = float(os.environ.get("MDPLUS_DAILY_BUDGET_USD", "0") or "0")
_SPEND_LOCK = threading.Lock()
_SPEND = {"day": "", "usd": 0.0}


def _spend_day() -> str:
    return utc_now()[:10]


def budget_exceeded() -> bool:
    """True when a daily budget is configured and already spent."""
    if DAILY_BUDGET_USD <= 0:
        return False
    with _SPEND_LOCK:
        if _SPEND["day"] != _spend_day():
            _SPEND["day"] = _spend_day()
            _SPEND["usd"] = 0.0
        return _SPEND["usd"] >= DAILY_BUDGET_USD


def record_spend(usd: float) -> None:
    with _SPEND_LOCK:
        if _SPEND["day"] != _spend_day():
            _SPEND["day"] = _spend_day()
            _SPEND["usd"] = 0.0
        _SPEND["usd"] += max(0.0, float(usd or 0.0))


def server_build_id() -> str:
    digest = hashlib.sha256()
    for path in (
        Path(__file__),
        Path(__file__).with_name("arms.py"),
        Path(__file__).with_name("sandboxing.py"),
        Path(__file__).with_name("api_runner.py"),
        Path(__file__).with_name("reliability.py"),
        Path(__file__).with_name("appeal_letter.py"),
    ):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


SERVER_BUILD_ID = server_build_id()


MAX_REQUEST_BYTES = 64 * 1024 * 1024


def json_body(handler: "Handler") -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length > MAX_REQUEST_BYTES:
        raise ValueError("request body is too large")
    raw = handler.rfile.read(length) if length else b"{}"
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    return value


def load_episode(episode_id: str) -> Episode:
    if not re.fullmatch(r"ep_[0-9a-f]{12}", episode_id):
        raise ValueError("invalid episode id")
    return Episode(EPISODES_ROOT / episode_id)


def write_json(handler: "Handler", value: Any, status: int = 200) -> None:
    payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def submission_text(data: dict[str, Any]) -> str:
    visible = {
        "denial_letter": data.get("denial_letter", "").strip(),
        "payer": data.get("payer", "").strip(),
        "plan_name": data.get("plan_name", "").strip(),
        "state": data.get("state", "").strip(),
        "product_clue": data.get("product_clue", "").strip(),
        "procedure": data.get("procedure", "").strip(),
        "cpt": data.get("cpt", "").strip(),
        "treating_practice": data.get("treating_practice", "").strip(),
        "patient_notes": data.get("patient_notes", "").strip(),
    }
    return "Synthetic patient submission:\n" + json.dumps(
        visible, ensure_ascii=False, indent=2
    )


def merge_letter_text(pasted: str, reading: dict[str, Any]) -> str:
    """Combine what the patient typed with what we read off their photo."""
    pasted = (pasted or "").strip()
    read = (reading.get("text") or "").strip()
    if not read:
        if pasted:
            return pasted
        reason = reading.get("reason") or reading.get("outcome") or "it could not be read"
        raise ValueError(
            "We could not read the picture of the letter. "
            "Please take a clearer photo in good light, or type what the letter says. "
            f"({reason})"
        )
    pages = reading.get("pages", 1)
    header = (
        f"Text read from the {pages} page(s) of the denial letter the patient "
        "photographed. Treat this as the letter itself:"
    )
    if pasted:
        return pasted + "\n\n" + header + "\n" + read
    return header + "\n" + read


def create_direct_episode(data: dict[str, Any]) -> Episode:
    if not data.get("denial_letter", "").strip():
        raise ValueError("denial_letter is required")
    episode = Episode.create(EPISODES_ROOT, label="ui-direct-synthetic-patient")
    request = episode.create_message(
        sender="orchestrator",
        recipient="patient_actor",
        body="Submit the synthetic patient's denial materials and visible insurance details.",
        message_type="episode_start",
    )
    response = episode.create_message(
        sender="patient_actor",
        recipient="orchestrator",
        body=submission_text(data),
        message_type="patient_response",
        in_reply_to=request["message_id"],
    )
    requested = data.get("retrieval_mode", "both")
    requested_arms = (
        ["library_only", "web_only"]
        if requested == "both"
        else [requested]
    )
    episode._update_manifest(
        status="patient_submission_received",
        synthetic_input_mode="direct_operator_entry",
        last_patient_response_id=response["message_id"],
        active_patient_request_id=None,
        requested_arms=requested_arms,
    )
    episode.log_event(
        role="orchestrator",
        arm="shared",
        event_type="direct_patient_submission_received",
        status="succeeded",
        summary="Recorded operator-entered synthetic patient data through the internal UI.",
        details={"message_id": response["message_id"]},
    )
    return episode


def launch_prepared_arm(
    episode: Episode,
    arm: str,
    arm_data: dict[str, Any],
) -> None:
    arm_dir = Path(arm_data["arm_directory"])
    stdout_path = arm_dir / "codex_events.jsonl"
    stderr_path = arm_dir / "codex_stderr.log"
    engine = engine_name()
    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
        "--cd",
        str(arm_dir),
        "--output-last-message",
        str(arm_dir / "result.json"),
    ]
    if arm == "web_only":
        # The process is wrapped in sandbox-exec below. Asking Codex to create
        # another macOS sandbox inside that profile fails with
        # `sandbox_apply: Operation not permitted`, including for child MCP
        # runtimes. The outer profile is therefore the sole OS sandbox.
        command.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        command.extend(["--sandbox", "workspace-write"])
    if arm == "library_only":
        command.extend(["--add-dir", str(SOURCE_LIBRARY_ROOT.resolve())])
        command.extend(["--add-dir", str(PLATFORM_ROOT.resolve())])
    replacement_path = arm_data.get("replacement_absolute_path")
    if replacement_path:
        command.extend(["--add-dir", str(Path(replacement_path).parent)])
    command.append("-")
    if arm == "web_only" and engine == "codex":
        profile = write_web_read_barrier(
            workspace=WORKSPACE,
            episode_root=episode.root,
            run_dir=arm_dir,
            source_library_root=SOURCE_LIBRARY_ROOT,
            platform_root=PLATFORM_ROOT,
        )
        command = ["sandbox-exec", "-f", str(profile), *command]

    with RUNS_LOCK:
        RUNS.setdefault(episode.episode_id, {})[arm] = {
            "status": "running",
            "started": True,
            "revision": arm_data.get("revision", 0),
        }
    write_json_atomic(
        episode.root / "system" / arm / "runtime_status.json",
        {
            "status": "running",
            "started_at": utc_now(),
            "revision": arm_data.get("revision", 0),
            "run_directory": str(arm_dir.relative_to(episode.root)),
        },
    )
    episode.log_event(
        role="orchestrator",
        arm=arm,
        event_type="agent_spawned",
        status="running",
        summary=f"Spawned fresh {engine} agent for {arm}.",
        artifacts=[str(Path(arm_data["prompt_path"]).relative_to(episode.root))],
        details={
            "revision": arm_data.get("revision", 0),
            "engine": engine,
            "os_read_barrier": arm == "web_only" and engine == "codex",
        },
    )
    try:
        if engine == "api" and budget_exceeded():
            returncode = 3
            run_error = (
                "Daily model budget reached; new runs are paused until the "
                "budget window rolls over."
            )
        else:
            # Bound concurrent heavy runs. Excess launches block here until a
            # slot frees, rather than overwhelming the host.
            with arm_slot():
                if engine == "api":
                    work_order = json.loads(
                        Path(arm_data["work_order_path"]).read_text(encoding="utf-8")
                    )
                    run = run_api_arm(arm_dir, work_order, on_cost=record_spend)
                    returncode = run["returncode"]
                    run_error = run.get("error")
                elif engine == "claude":
                    work_order = json.loads(
                        Path(arm_data["work_order_path"]).read_text(encoding="utf-8")
                    )
                    run = run_claude_arm(arm_dir, work_order)
                    returncode = run["returncode"]
                    run_error = run.get("error")
                else:
                    with stdout_path.open(
                        "w", encoding="utf-8"
                    ) as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
                        process = subprocess.run(
                            command,
                            input=arm_data["prompt"],
                            text=True,
                            stdout=stdout,
                            stderr=stderr,
                            cwd=WORKSPACE,
                            timeout=1800,
                        )
                    returncode = process.returncode
                    run_error = None
        outcome: dict[str, Any] = {
            "status": "completed" if returncode == 0 else "failed",
            "returncode": returncode,
            "engine": engine,
        }
        if returncode == 0 and (arm_dir / "result.json").exists():
            outcome["validation"] = ingest_arm_result(episode, arm, arm_dir)
            if not outcome["validation"].get("valid"):
                outcome["status"] = "failed"
                errors = outcome["validation"].get("errors", [])
                outcome["error"] = (
                    "Agent returned an invalid result"
                    + (f": {'; '.join(errors[:3])}" if errors else ".")
                )
        elif returncode == 0:
            outcome["status"] = "failed"
            outcome["error"] = "Agent finished without result.json"
        else:
            outcome["error"] = (
                run_error or f"The {engine} agent exited before producing a valid result."
            )
            episode.log_event(
                role="orchestrator",
                arm=arm,
                event_type="agent_failed",
                status="failed",
                summary=f"{arm} agent exited with code {returncode}: {outcome['error']}",
                artifacts=[
                    str(path.relative_to(episode.root))
                    for path in (stdout_path, stderr_path)
                    if path.exists()
                ],
                details={
                    "returncode": returncode,
                    "engine": engine,
                    "revision": arm_data.get("revision", 0),
                },
            )
            alert(
                "arm_failed",
                f"{arm} run failed: {outcome.get('error', 'unknown error')}",
                {"episode_id": episode.episode_id, "arm": arm, "engine": engine,
                 "returncode": returncode},
            )
        with RUNS_LOCK:
            RUNS[episode.episode_id][arm] = outcome
        write_json_atomic(
            episode.root / "system" / arm / "runtime_status.json",
            {
                **outcome,
                "finished_at": utc_now(),
                "revision": arm_data.get("revision", 0),
                "run_directory": str(arm_dir.relative_to(episode.root)),
            },
        )
        log_run_async(
            build_record(
                episode_id=episode.episode_id,
                arm=arm,
                episode_root=episode.root,
                arm_dir=arm_dir,
                outcome={**outcome, "revision": arm_data.get("revision", 0)},
            ),
            arm_dir,
        )
    except Exception as exc:
        episode.log_event(
            role="orchestrator",
            arm=arm,
            event_type="agent_failed",
            status="failed",
            summary=f"{arm} process failed: {exc}",
            details={"traceback": traceback.format_exc(limit=5)},
        )
        alert(
            "arm_crashed",
            f"{arm} run crashed with an unexpected exception: {exc}",
            {"episode_id": episode.episode_id, "arm": arm},
        )
        with RUNS_LOCK:
            RUNS[episode.episode_id][arm] = {
                "status": "failed",
                "error": str(exc),
                "revision": arm_data.get("revision", 0),
            }
        write_json_atomic(
            episode.root / "system" / arm / "runtime_status.json",
            {
                "status": "failed",
                "error": str(exc),
                "finished_at": utc_now(),
                "revision": arm_data.get("revision", 0),
                "run_directory": str(arm_dir.relative_to(episode.root)),
            },
        )
        log_run_async(
            build_record(
                episode_id=episode.episode_id,
                arm=arm,
                episode_root=episode.root,
                arm_dir=arm_dir,
                outcome={
                    "status": "failed",
                    "error": str(exc),
                    "engine": engine,
                    "revision": arm_data.get("revision", 0),
                },
            ),
            arm_dir,
        )


def launch_arm(episode: Episode, arm: str) -> None:
    launch_prepared_arm(episode, arm, prepare_arm(episode, arm, WORKSPACE))


def launch_correction(
    episode: Episode,
    arm: str,
    feedback: dict[str, Any],
) -> None:
    launch_prepared_arm(
        episode,
        arm,
        prepare_correction_arm(episode, arm, feedback),
    )


def launch_follow_up(
    episode: Episode,
    arm: str,
    question: str,
    answer: str,
) -> None:
    launch_prepared_arm(
        episode,
        arm,
        prepare_follow_up_arm(episode, arm, question, answer),
    )


def start_episode_runs(episode: Episode, arms: list[str]) -> None:
    for arm in arms:
        thread = threading.Thread(target=launch_arm, args=(episode, arm), daemon=True)
        thread.start()


def start_correction_run(
    episode: Episode,
    arm: str,
    feedback: dict[str, Any],
) -> None:
    thread = threading.Thread(
        target=launch_correction,
        args=(episode, arm, feedback),
        daemon=True,
    )
    thread.start()


def start_follow_up_run(
    episode: Episode,
    arm: str,
    question: str,
    answer: str,
) -> None:
    thread = threading.Thread(
        target=launch_follow_up,
        args=(episode, arm, question, answer),
        daemon=True,
    )
    thread.start()


def launch_evaluation(episode: Episode) -> None:
    prepared = prepare_evaluation(episode)
    evaluation_dir = Path(prepared["evaluation_directory"])
    stdout_path = evaluation_dir / "codex_events.jsonl"
    stderr_path = evaluation_dir / "codex_stderr.log"
    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
        "--sandbox",
        "workspace-write",
        "--cd",
        str(evaluation_dir),
        "--output-last-message",
        prepared["verdict_path"],
        "-",
    ]
    EVALUATION_RUNS[episode.episode_id] = {"status": "running"}
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr:
            process = subprocess.run(
                command,
                input=prepared["prompt"],
                text=True,
                stdout=stdout,
                stderr=stderr,
                cwd=WORKSPACE,
                timeout=1200,
            )
        if process.returncode or not Path(prepared["verdict_path"]).exists():
            EVALUATION_RUNS[episode.episode_id] = {
                "status": "failed",
                "returncode": process.returncode,
            }
            episode.log_event(
                role="evaluator",
                arm="evaluation",
                event_type="evaluation_failed",
                status="failed",
                summary="Independent automated evaluation did not complete.",
                artifacts=[
                    str(stdout_path.relative_to(episode.root)),
                    str(stderr_path.relative_to(episode.root)),
                ],
            )
            return
        verdict = load_verdict(episode)
        errors = validate_verdict(episode, verdict or {})
        write_json_atomic(
            evaluation_dir / "verdict_validation.json",
            {
                "valid": not errors,
                "errors": errors,
                "validated_at": utc_now(),
            },
        )
        if errors:
            EVALUATION_RUNS[episode.episode_id] = {
                "status": "failed",
                "errors": errors,
            }
            episode.log_event(
                role="evaluator",
                arm="evaluation",
                event_type="evaluation_validation_failed",
                status="failed",
                summary="Automated evaluation output failed validation.",
                details={"errors": errors},
            )
            return
        EVALUATION_RUNS[episode.episode_id] = {"status": "completed"}
        episode.log_event(
            role="evaluator",
            arm="evaluation",
            event_type="evaluation_completed",
            status="succeeded",
            summary="Independent automated evaluation completed.",
            artifacts=["evaluation/automated_verdict.json"],
            details={
                "human_review_priority": verdict.get("human_review_priority")
                if verdict
                else None
            },
        )
    except Exception as exc:
        EVALUATION_RUNS[episode.episode_id] = {
            "status": "failed",
            "error": str(exc),
        }


def start_evaluation(episode: Episode) -> None:
    threading.Thread(target=launch_evaluation, args=(episode,), daemon=True).start()


def load_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def patient_submission_snapshot(episode: Episode) -> dict[str, Any] | None:
    messages_path = episode.root / "patient_workspace" / "logs" / "messages.jsonl"
    if not messages_path.exists():
        return None
    for row in reversed(read_jsonl(messages_path)):
        if row.get("sender") != "patient_actor":
            continue
        envelope = load_json_if_exists(episode.root / row["envelope_path"])
        body = (envelope or {}).get("body", "")
        prefix = "Synthetic patient submission:\n"
        if body.startswith(prefix):
            try:
                return json.loads(body[len(prefix) :])
            except json.JSONDecodeError:
                return {"raw_text": body}
    return None


def summarize_live_command(command: str) -> str:
    urls = re.findall(r"https?://[^'\" ]+", command)
    if urls:
        parsed = urlparse(urls[0])
        query = parse_qs(parsed.query).get("q", [])
        if query:
            return f"Searching the web for: {query[0]}"
        return f"Opening {parsed.netloc}{parsed.path}"
    lowered = command.lower()
    if "work_order.json" in lowered:
        return "Reading the patient-visible work order."
    if "shasum" in lowered or "sha256" in lowered:
        return "Verifying the downloaded document checksum."
    if "pdftotext" in lowered:
        return "Extracting searchable text from the policy document."
    if "rg " in lowered or "grep " in lowered:
        return "Inspecting the retrieved policy for relevant criteria."
    return "Running a bounded retrieval step."


def live_agent_events(episode: Episode, arm: str, runtime: dict[str, Any]) -> list[dict[str, Any]]:
    if runtime.get("status") != "running":
        return []
    path = episode.root / "system" / arm / "codex_events.jsonl"
    rows = read_jsonl(path) if path.exists() else []
    activity: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        item = row.get("item", {})
        if row.get("type") == "item.started" and item.get("type") == "command_execution":
            activity.append(
                {
                    "event_id": f"live_{arm}_{index}",
                    "arm": arm,
                    "status": "running",
                    "timestamp": utc_now(),
                    "summary": summarize_live_command(item.get("command", "")),
                    "volatile": True,
                }
            )
        elif row.get("type") == "item.completed" and item.get("type") == "agent_message":
            text = " ".join(str(item.get("text", "")).split())
            if text and not text.startswith("{"):
                activity.append(
                    {
                        "event_id": f"live_{arm}_{index}",
                        "arm": arm,
                        "status": "running",
                        "timestamp": utc_now(),
                        "summary": text[:240],
                        "volatile": True,
                    }
                )
    return activity[-7:]


def load_arm_result(episode: Episode, arm: str) -> dict[str, Any] | None:
    """The current best result for an arm: active > frozen > validated result."""
    arm_dir = episode.root / "system" / arm
    result = load_json_if_exists(arm_dir / "active_result.json")
    if result is None:
        result = load_json_if_exists(arm_dir / "frozen_result.json")
    if result is None:
        validations = sorted((arm_dir / "attempts").glob("validation_*.json"))
        latest_validation = load_json_if_exists(validations[-1]) if validations else None
        if latest_validation is None or latest_validation.get("valid"):
            result = load_json_if_exists(arm_dir / "result.json")
    return result


def generate_and_store_appeal_letter(episode: Episode, arm: str) -> dict[str, Any]:
    """Assess whether the denial calls for a letter and, if so, draft + store it.

    Returns {"assessment": ..., "letter": {...}} where letter is present only
    when a grounded appeal letter is the right next step and generation
    succeeded. Respects the daily spend budget.
    """
    result = load_arm_result(episode, arm)
    if result is None:
        return {"error": f"no result available for {arm} yet"}
    assessment = assess_letter(result)
    payload: dict[str, Any] = {"arm": arm, "assessment": assessment}
    if not assessment.get("recommended"):
        return payload
    if budget_exceeded():
        payload["assessment"] = {
            **assessment,
            "deferred": "Daily model budget reached; letter drafting is paused.",
        }
        return payload

    submission = patient_submission_snapshot(episode)
    submission_text = None
    if isinstance(submission, dict):
        for key in ("denial_letter_text", "denial_text", "notes", "story", "raw_text"):
            if submission.get(key):
                submission_text = str(submission[key])
                break
    with arm_slot():
        drafted = generate_appeal_letter(result, patient_submission=submission_text)
    if drafted.get("estimated_cost_usd"):
        record_spend(drafted["estimated_cost_usd"])
    if drafted.get("error"):
        payload["error"] = drafted["error"]
        return payload

    arm_dir = episode.root / "system" / arm
    (arm_dir / "appeal_letter.md").write_text(drafted["letter_markdown"], encoding="utf-8")
    meta = {k: v for k, v in drafted.items() if k != "letter_markdown"}
    meta.update({"arm": arm, "kind": assessment.get("kind"), "generated_at": utc_now()})
    write_json_atomic(arm_dir / "appeal_letter_meta.json", meta)
    episode.log_event(
        role="orchestrator",
        arm=arm,
        event_type="appeal_letter_drafted",
        status="succeeded",
        summary="Drafted a grounded appeal letter from the confirmed policy.",
        artifacts=[f"system/{arm}/appeal_letter.md"],
        details={"estimated_cost_usd": drafted.get("estimated_cost_usd")},
    )
    payload["letter"] = {"markdown": drafted["letter_markdown"], "meta": meta}
    return payload


def episode_snapshot(episode: Episode) -> dict[str, Any]:
    manifest = episode.manifest()
    events = []
    for path in sorted((episode.root / "system" / "logs").glob("*.jsonl")):
        events.extend(read_jsonl(path))
    events.sort(key=lambda row: row.get("timestamp", ""))
    arms: dict[str, Any] = {}
    with RUNS_LOCK:
        runtime = dict(RUNS.get(episode.episode_id, {}))
    for arm in ("library_only", "web_only"):
        arm_dir = episode.root / "system" / arm
        result = load_json_if_exists(arm_dir / "active_result.json")
        if result is None:
            result = load_json_if_exists(arm_dir / "frozen_result.json")
        if result is None:
            validations = sorted((arm_dir / "attempts").glob("validation_*.json"))
            latest_validation = load_json_if_exists(validations[-1]) if validations else None
            if latest_validation is None or latest_validation.get("valid"):
                result = load_json_if_exists(arm_dir / "result.json")
        persisted_runtime = load_json_if_exists(arm_dir / "runtime_status.json")
        arms[arm] = {
            "runtime": runtime.get(
                arm,
                persisted_runtime or {"status": "not_started"},
            ),
            "result": result,
            "validation": load_json_if_exists(arm_dir / "freeze_manifest.json"),
        }
        # Denial-reason-aware output: tell the UI whether an appeal letter is the
        # right next step, and whether one has already been drafted.
        if result:
            arms[arm]["appeal"] = {
                "assessment": assess_letter(result),
                "letter_available": (arm_dir / "appeal_letter.md").exists(),
            }
        events.extend(live_agent_events(episode, arm, arms[arm]["runtime"]))
    active_hashes = {
        arm: data["result"].get("_sha256", "")
        for arm, data in arms.items()
        if data.get("result")
    }
    active_source_fingerprints: dict[str, str] = {}
    for arm, data in arms.items():
        active_path = episode.root / "system" / arm / "active_result.json"
        fallback_path = episode.root / "system" / arm / "frozen_result.json"
        path = active_path if active_path.exists() else fallback_path
        if path.exists():
            from .integrity import sha256_file

            active_hashes[arm] = sha256_file(path)
        result = data.get("result") or {}
        active_source_fingerprints[arm] = source_fingerprint(
            result.get("retrieval", {}).get("selected_source")
        )
    verdict_validation = load_json_if_exists(
        episode.root / "evaluation" / "verdict_validation.json"
    )
    verdict = load_verdict(episode)
    if verdict_validation and not verdict_validation.get("valid"):
        verdict = None
    return {
        "manifest": manifest,
        "patient_submission": patient_submission_snapshot(episode),
        "events": events[-100:],
        "arms": arms,
        "integrity": episode.verify(),
        "source_reviews": latest_source_reviews(
            episode,
            active_hashes,
            active_source_fingerprints,
        ),
        "evaluation": {
            "eligibility": evaluation_eligibility(episode),
            "runtime": EVALUATION_RUNS.get(
                episode.episode_id, {"status": "not_started"}
            ),
            "verdict": verdict,
            "validation": verdict_validation,
            "human_adjudication": latest_adjudication(episode),
        },
    }


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        parsed = urlparse(path).path
        # The patient-facing site is served here so it shares an origin with the
        # API; a cross-origin page cannot reach it from the static preview host.
        if parsed == "/patient" or parsed.startswith("/patient/"):
            relative = parsed[len("/patient") :].lstrip("/") or "map/index.html"
            candidate = (PATIENT_UI / relative).resolve()
            if not candidate.is_relative_to(PATIENT_UI.resolve()):
                return str(PATIENT_UI / "map" / "index.html")
            if candidate.is_dir():
                candidate = candidate / "index.html"
            return str(candidate)
        relative = parsed.lstrip("/") or "index.html"
        candidate = UI_DIST / relative
        if not candidate.exists() and "." not in Path(relative).name:
            candidate = UI_DIST / "index.html"
        return str(candidate)

    def do_POST(self) -> None:
        try:
            if self.path == "/api/episodes":
                data = json_body(self)
                # A photo of the letter cannot reach the retrieval agent, which
                # has no file access and no vision. Read it here first and pass
                # the words along instead of the picture.
                uploads = decode_attachments(data.pop("attachments", None))
                reading = None
                if uploads:
                    reading = transcribe(uploads)
                    data["denial_letter"] = merge_letter_text(
                        data.get("denial_letter", ""), reading
                    )
                episode = create_direct_episode(data)
                if uploads:
                    folder = episode.root / "patient_uploads"
                    save_uploads(uploads, folder)
                    write_json_atomic(folder / "read_receipt.json", reading)
                    episode.log_event(
                        role="orchestrator",
                        arm="shared",
                        event_type="denial_letter_photo_read",
                        status="succeeded",
                        summary=(
                            f"Read {reading.get('pages', 0)} uploaded page(s) of the "
                            "denial letter into text."
                        ),
                        details={
                            "pages": reading.get("pages"),
                            "characters": reading.get("characters"),
                            "elapsed_s": reading.get("elapsed_s"),
                            "cost_usd": reading.get("cost_usd"),
                        },
                    )
                requested = data.get("retrieval_mode", "both")
                arms = (
                    ["library_only", "web_only"]
                    if requested == "both"
                    else [requested]
                )
                start_episode_runs(episode, arms)
                write_json(self, episode_snapshot(episode), HTTPStatus.CREATED)
                return
            if self.path.endswith("/follow-up"):
                episode_id = self.path.split("/")[3]
                episode = load_episode(episode_id)
                data = json_body(self)
                request = episode.create_message(
                    sender="orchestrator",
                    recipient="patient_actor",
                    body="Please answer this requested follow-up:\n" + data["question"],
                    message_type="follow_up_question",
                    in_reply_to=episode.manifest().get("last_patient_response_id"),
                )
                response = episode.create_message(
                    sender="patient_actor",
                    recipient="orchestrator",
                    body=data["answer"],
                    message_type="patient_response",
                    in_reply_to=request["message_id"],
                )
                episode._update_manifest(last_patient_response_id=response["message_id"])
                start_follow_up_run(
                    episode,
                    data["arm"],
                    data["question"],
                    data["answer"],
                )
                write_json(self, episode_snapshot(episode))
                return
            if self.path.endswith("/source-feedback"):
                episode_id = self.path.split("/")[3]
                episode = load_episode(episode_id)
                data = json_body(self)
                feedback = record_source_review(
                    episode=episode,
                    arm=data["arm"],
                    decision=data["decision"],
                    notes=data.get("notes", ""),
                    upload=data.get("upload"),
                )
                if data["decision"] in {"rejected", "replaced"}:
                    start_correction_run(
                        episode,
                        data["arm"],
                        feedback,
                    )
                write_json(self, episode_snapshot(episode))
                return
            if self.path.endswith("/retry-arm"):
                episode_id = self.path.split("/")[3]
                episode = load_episode(episode_id)
                data = json_body(self)
                arm = data["arm"]
                current = RUNS.get(episode_id, {}).get(arm)
                persisted = load_json_if_exists(
                    episode.root / "system" / arm / "runtime_status.json"
                )
                if (current or persisted or {}).get("status") == "running":
                    raise ValueError(f"{arm} is already running")
                reviews = latest_source_reviews(episode)
                latest = reviews.get(arm)
                if latest and latest.get("decision") in {"rejected", "replaced"}:
                    start_correction_run(episode, arm, latest)
                else:
                    start_episode_runs(episode, [arm])
                write_json(self, episode_snapshot(episode))
                return
            if self.path.endswith("/appeal-letter"):
                episode_id = self.path.split("/")[3]
                episode = load_episode(episode_id)
                data = json_body(self)
                arm = data.get("arm", "web_only")
                write_json(self, generate_and_store_appeal_letter(episode, arm))
                return
            if self.path.endswith("/evaluate"):
                episode_id = self.path.split("/")[3]
                episode = load_episode(episode_id)
                start_evaluation(episode)
                write_json(self, episode_snapshot(episode))
                return
            if self.path.endswith("/adjudicate"):
                episode_id = self.path.split("/")[3]
                episode = load_episode(episode_id)
                data = json_body(self)
                record_adjudication(
                    episode=episode,
                    decision=data["decision"],
                    notes=data.get("notes", ""),
                    corrections=data.get("corrections"),
                )
                write_json(self, episode_snapshot(episode))
                return
            write_json(self, {"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            write_json(
                self,
                {"error": str(exc), "type": type(exc).__name__},
                HTTPStatus.BAD_REQUEST,
            )

    def do_GET(self) -> None:
        if "/appeal-letter/" in self.path and self.path.startswith("/api/episodes/"):
            try:
                parts = self.path.split("/")
                episode_id, arm = parts[3], parts[5].split("?")[0]
                episode = load_episode(episode_id)
                arm_dir = episode.root / "system" / arm
                letter = arm_dir / "appeal_letter.md"
                if not letter.exists():
                    write_json(self, {"error": "no letter drafted"}, HTTPStatus.NOT_FOUND)
                    return
                write_json(
                    self,
                    {
                        "arm": arm,
                        "markdown": letter.read_text(encoding="utf-8"),
                        "meta": load_json_if_exists(arm_dir / "appeal_letter_meta.json"),
                    },
                )
            except Exception as exc:
                write_json(self, {"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        if "/source-document/" in self.path and self.path.startswith("/api/episodes/"):
            try:
                parts = self.path.split("/")
                episode_id, arm = parts[3], parts[5]
                path, media_type = source_document_for_review(
                    load_episode(episode_id), arm
                )
                if not path:
                    url = source_url_for_review(
                        load_episode(episode_id), arm
                    )
                    if url:
                        self.send_response(HTTPStatus.FOUND)
                        self.send_header("Location", url)
                        self.end_headers()
                        return
                    write_json(self, {"error": "renderable source not available"}, HTTPStatus.NOT_FOUND)
                    return
                content = path.read_bytes()
                resolved_media_type = (
                    media_type
                    or mimetypes.guess_type(path.name)[0]
                    or "application/octet-stream"
                )
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", resolved_media_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
                self.send_header("X-Content-Type-Options", "nosniff")
                if resolved_media_type in {"text/html", "application/xhtml+xml"}:
                    self.send_header(
                        "Content-Security-Policy",
                        "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data: https:;",
                    )
                self.end_headers()
                self.wfile.write(content)
            except Exception as exc:
                write_json(self, {"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        if self.path.startswith("/api/episodes/"):
            try:
                episode_id = self.path.split("/")[3]
                write_json(self, episode_snapshot(load_episode(episode_id)))
            except Exception as exc:
                write_json(self, {"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        if self.path == "/api/health":
            with _SPEND_LOCK:
                spend = dict(_SPEND)
            write_json(
                self,
                build_health(
                    episodes_root=EPISODES_ROOT,
                    engine=engine_name(),
                    build_id=SERVER_BUILD_ID,
                    started_at=SERVER_STARTED_AT,
                    ui_built=UI_DIST.exists(),
                    max_concurrent_arms=MAX_CONCURRENT_ARMS,
                    active_arms=active_arm_count(),
                    spend=spend,
                    daily_budget_usd=DAILY_BUDGET_USD,
                    budget_paused=budget_exceeded(),
                ),
            )
            return
        if self.path == "/api/metrics":
            write_json(self, build_metrics(EPISODES_ROOT))
            return
        super().do_GET()

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    if not UI_DIST.exists():
        raise SystemExit("UI build missing. Run: cd ui && npm install && npm run build")
    EPISODES_ROOT.mkdir(parents=True, exist_ok=True)
    configure_logging()
    # Crash recovery: a run thread cannot survive a restart, so any arm still
    # marked "running" on disk is stale. Flip it to "interrupted" so the UI and
    # the retry guard don't wait on a run that will never finish.
    reconcile_interrupted_runs(EPISODES_ROOT)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Denial Simulation Lab: http://{args.host}:{args.port} (engine: {engine_name()})")
    server.serve_forever()


if __name__ == "__main__":
    main()
