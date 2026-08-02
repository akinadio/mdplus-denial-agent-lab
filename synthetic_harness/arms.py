"""Preparation and validation boundaries for isolated retrieval arms."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .episode import Episode
from .integrity import read_jsonl, sha256_file, utc_now, write_json_atomic
from . import policy_anchors

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_ROOT = Path(
    os.environ.get("MDPLUS_POLICY_PLATFORM_ROOT", WORKSPACE_ROOT / "data/policy_platform")
).expanduser().resolve()
SOURCE_LIBRARY_ROOT = Path(
    os.environ.get("MDPLUS_POLICY_LIBRARY_ROOT", WORKSPACE_ROOT / "data/policy_library")
).expanduser().resolve()

ARM_RULES = {
    "library_only": {
        "objective": "Retrieve the best applicable policy from the existing internal library, parse it, and determine the patient-facing next action.",
        "allowed_sources": [
            str(SOURCE_LIBRARY_ROOT),
            str(PLATFORM_ROOT / "source_registry.json"),
            str(PLATFORM_ROOT / "source_registry.csv"),
        ],
        "forbidden_sources": [
            "Internet, browser search, curl, wget, or any live network retrieval",
            str(PLATFORM_ROOT / "criteria_extractions.json"),
            "The web_only arm directory or logs",
            "Sealed truth, controller keys, evaluation artifacts, and patient_packet.json",
        ],
    },
    "web_only": {
        "objective": "Retrieve the best applicable current official policy through fresh online research, parse it, and determine the patient-facing next action.",
        "allowed_sources": [
            "Fresh web search and official payer, delegated vendor, regulator, or federal sources",
            "Patient-visible messages copied into this work order",
        ],
        "forbidden_sources": [
            str(SOURCE_LIBRARY_ROOT),
            str(PLATFORM_ROOT),
            "Any local scraped policy, source registry, criteria extraction, or prior arm result",
            "The library_only arm directory or logs",
            "Sealed truth, controller keys, evaluation artifacts, and patient_packet.json",
        ],
    },
}


def patient_visible_transcript(episode: Episode) -> list[dict[str, Any]]:
    rows = read_jsonl(episode.root / "patient_workspace" / "logs" / "messages.jsonl")
    transcript: list[dict[str, Any]] = []
    for row in rows:
        envelope_path = episode.root / row["envelope_path"]
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        transcript.append(
            {
                "message_id": envelope["message_id"],
                "sequence": envelope["sequence"],
                "sender": envelope["sender"],
                "recipient": envelope["recipient"],
                "message_type": envelope["message_type"],
                "in_reply_to": envelope["in_reply_to"],
                "body": envelope["body"],
                "body_sha256": envelope["body_sha256"],
            }
        )
    return transcript


def result_contract() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "required_top_level_fields": [
            "episode_id",
            "arm",
            "status",
            "case_identification",
            "retrieval",
            "policy_analysis",
            "patient_interaction",
            "next_steps",
            "confidence",
            "blockers",
        ],
        "status_values": [
            "needs_patient_follow_up",
            "actionable_result",
            "blocked",
        ],
        "retrieval_requirements": {
            "candidates": "Every seriously considered source, with URL/path, official status, applicability, date, and selection/rejection reason.",
            "selected_source": "At most one best source, with exact URL/path, title, effective/current date, source type, document hash when local, and local_snapshot_path whenever the document can be downloaded for human rendering.",
            "citations": "Direct page, line, section, or short excerpt references supporting every consequential policy claim.",
        },
        "patient_interaction_requirements": {
            "questions": "Only necessary, patient-answerable questions. Each question needs a rationale and expected answer type.",
            "provider_records_needed": "Clinical records or facts the patient should not be expected to establish.",
            "question_stop_reason": "Why no more patient questions are needed, or why the arm remains blocked.",
        },
        "next_step_requirements": {
            "primary_action": "The immediate action most favorable to the patient that remains supported by evidence.",
            "ordered_actions": "Sequenced actions with responsible party and evidence/document requirements.",
            "deadline": "Only if directly supported; otherwise null with a verification instruction.",
            "safety_caveat": "Material uncertainty or limitation.",
        },
    }


def result_schema() -> dict[str, Any]:
    def strict_object(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": list(properties),
            "properties": properties,
        }

    nullable_string = {"type": ["string", "null"]}
    string_array = {"type": "array", "items": {"type": "string"}}
    source_fields = {
        "title": nullable_string,
        "source_type": nullable_string,
        "evidence_role": {
            "enum": [
                "governing_policy",
                "supporting_document",
                "appeal_or_routing_document",
            ]
        },
        "url": nullable_string,
        "path": nullable_string,
        "local_snapshot_path": nullable_string,
        "effective_date": nullable_string,
        "sha256": nullable_string,
        "official": {"type": "boolean"},
        "current": {"type": ["boolean", "null"]},
        "applicable": {"type": ["boolean", "null"]},
    }
    candidate = strict_object(
        {
            **source_fields,
            "selected": {"type": "boolean"},
            "decision_summary": {"type": "string"},
        }
    )
    selected_source = {
        "anyOf": [
            strict_object(source_fields),
            {"type": "null"},
        ]
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": result_contract()["required_top_level_fields"],
        "properties": {
            "episode_id": {"type": "string"},
            "arm": {"enum": ["library_only", "web_only"]},
            "status": {"enum": result_contract()["status_values"]},
            "case_identification": strict_object(
                {
                    "payer": nullable_string,
                    "plan_name": nullable_string,
                    "product_type": nullable_string,
                    "state": nullable_string,
                    "procedure": nullable_string,
                    "cpt": nullable_string,
                    "denial_language": nullable_string,
                    "unresolved_fields": string_array,
                }
            ),
            "retrieval": strict_object(
                {
                    "candidates": {"type": "array", "items": candidate},
                    "selected_source": selected_source,
                    "citations": {
                        "type": "array",
                        "items": strict_object(
                            {
                                "claim": {"type": "string"},
                                "reference": {"type": "string"},
                                "excerpt": {"type": "string"},
                            }
                        ),
                    },
                }
            ),
            "policy_analysis": strict_object(
                {
                    "denial_category": {"type": "string"},
                    "apparent_reason": {"type": "string"},
                    "criteria_at_issue": string_array,
                    "documentation_gaps": string_array,
                    "unmet_criteria": string_array,
                    "uncertainty": string_array,
                }
            ),
            "patient_interaction": strict_object(
                {
                    "questions": {
                        "type": "array",
                        "items": strict_object(
                            {
                                "question_id": {"type": "string"},
                                "text": {"type": "string"},
                                "rationale": {"type": "string"},
                                "answer_type": {"type": "string"},
                            }
                        ),
                    },
                    "provider_records_needed": string_array,
                    "question_stop_reason": {"type": "string"},
                }
            ),
            "next_steps": strict_object(
                {
                    "primary_action": {"type": "string"},
                    "responsible_party": {"type": "string"},
                    "ordered_actions": {
                        "type": "array",
                        "items": strict_object(
                            {
                                "order": {"type": "integer"},
                                "party": {"type": "string"},
                                "action": {"type": "string"},
                                "records_needed": string_array,
                            }
                        ),
                    },
                    "deadline": strict_object(
                        {
                            "value": nullable_string,
                            "source": nullable_string,
                            "verification_needed": {"type": "boolean"},
                        }
                    ),
                    "safety_caveat": {"type": "string"},
                }
            ),
            "confidence": strict_object(
                {
                    "overall": {"type": "string"},
                    "retrieval": {"type": "string"},
                    "policy_analysis": {"type": "string"},
                    "next_steps": {"type": "string"},
                    "rationale": {"type": "string"},
                }
            ),
            "blockers": {
                "type": "array",
                "items": strict_object(
                    {
                        "code": {"type": "string"},
                        "description": {"type": "string"},
                        "resolution": {"type": "string"},
                    }
                ),
            },
        },
    }


def agent_prompt(episode: Episode, arm: str, work_order_path: Path) -> str:
    rules = ARM_RULES[arm]
    allowed = "\n".join(f"- {item}" for item in rules["allowed_sources"])
    forbidden = "\n".join(f"- {item}" for item in rules["forbidden_sources"])
    return f"""You are the {arm} retrieval and denial-navigation agent for an internal blind simulation.

EPISODE
- episode_id: {episode.episode_id}
- case_id: {episode.case_id}
- arm: {arm}

Read only this work order:
{work_order_path}

OBJECTIVE
{rules['objective']}

ALLOWED EVIDENCE
{allowed}

FORBIDDEN EVIDENCE
{forbidden}

OPERATING RULES
1. Treat the patient-visible transcript as a real submission. Do not assume facts not supplied.
2. First normalize payer, product clues, state, procedure/test, CPT if present, dates, and the stated denial language.
3. Perform a genuine source-retrieval attempt within this arm's boundary.
4. Prefer the exact current official payer policy. Verify payer entity, product, state, procedure, effective date, and delegated vendor applicability.
4a. Label every candidate and selected source with `evidence_role`. A form, code list, policy index, or routing guide is supporting evidence, not the governing policy. If the governing policy cannot be inspected, do not present a supporting document as a successful governing-policy retrieval.
5. Record every serious candidate and a concise observable reason for selecting or rejecting it. Do not log private chain-of-thought.
6. Parse the selected document itself. Do not rely on uncited summaries.
7. Distinguish:
   - missing documentation,
   - genuinely unmet criteria,
   - administrative denial,
   - benefit exclusion,
   - investigational/experimental denial,
   - site-of-service issue,
   - unresolved uncertainty.
8. Ask only questions a patient can reasonably answer. Route chart-dependent facts and clinical interpretation to the provider.
9. Recommend the most immediately actionable evidence-supported next step favorable to the patient. Do not promise coverage or invent a deadline.
10. If evidence is insufficient, return a precise blocker and escalation path.
11. Write only observable results and concise decision summaries; never include hidden chain-of-thought.
12. You MUST perform genuine retrieval and inspect the selected document before returning a terminal result. `blocked` is valid only after recording attempted candidates and a concrete external blocker; it must never mean that work has not yet been attempted.
13. For the web_only arm, use direct shell and HTTP retrieval tools such as curl. Do not invoke MCP, browser-control, node_repl, or other child runtimes; the worker already runs inside the episode's OS-level read barrier.

OUTPUT
After completing all retrieval and document-inspection work, make your FINAL RESPONSE a single JSON object conforming exactly to `result_schema` in the work order directory. Do not wrap it in Markdown and do not return an interim JSON response. The controller will save that final response to:
{work_order_path.parent / 'result.json'}

When practical, also append concise structured search/retrieval events to:
{work_order_path.parent / 'agent_events.jsonl'}

Do not access or modify any other arm directory."""


def correction_prompt(
    episode: Episode,
    arm: str,
    work_order_path: Path,
    decision: str,
) -> str:
    rules = ARM_RULES[arm]
    allowed = "\n".join(f"- {item}" for item in rules["allowed_sources"])
    if decision == "replaced":
        task = """The human reviewer supplied a replacement policy. Treat that uploaded document as the only candidate source for this revision. Inspect it directly, assess whether it applies to the submitted patient, parse its denial-relevant criteria, and regenerate the patient questions and next actions. Do not reuse the prior source's conclusions."""
    else:
        task = """The human reviewer rejected the previously selected policy. Perform a fresh retrieval within this arm's normal source boundary, explicitly exclude the rejected source, use the reviewer note as retrieval feedback, and regenerate the analysis from the newly selected source. If no defensible alternative exists, return a concrete blocker."""
    return f"""You are the {arm} correction agent for an internal blind simulation.

EPISODE
- episode_id: {episode.episode_id}
- case_id: {episode.case_id}
- arm: {arm}
- correction decision: {decision}

Read only this correction work order:
{work_order_path}

CORRECTION TASK
{task}

ALLOWED EVIDENCE
{allowed}
- The human feedback and replacement document, if present, identified in the correction work order.

FORBIDDEN EVIDENCE
{chr(10).join(f"- {item}" for item in rules["forbidden_sources"])}

RULES
1. Treat the patient-visible transcript as the complete patient submission.
2. Inspect the corrected source itself and cite it directly.
3. Do not preserve conclusions merely because they appeared in the rejected result.
4. Ask only patient-answerable questions and route chart-dependent information to the provider.
5. Do not invent deadlines or promise coverage.
6. Record concise observable source decisions, never private chain-of-thought.
7. A blocked result requires a real attempted correction and a precise blocker.

OUTPUT
After completing the correction, make your FINAL RESPONSE one JSON object conforming exactly to `result_schema` in the work order. Do not wrap it in Markdown and do not return interim JSON. The controller will save it as:
{work_order_path.parent / 'result.json'}

When practical, append observable correction events to:
{work_order_path.parent / 'agent_events.jsonl'}
"""


def prepare_arm(episode: Episode, arm: str, workspace_root: Path) -> dict[str, Any]:
    if arm not in ARM_RULES:
        raise ValueError(f"unsupported arm: {arm}")
    manifest = episode.manifest()
    if not manifest.get("last_patient_response_id"):
        raise ValueError("a patient submission must be recorded before preparing retrieval arms")
    if manifest.get("active_patient_request_id"):
        raise ValueError("cannot prepare an arm while a patient request is unanswered")

    arm_dir = episode.root / "system" / arm
    transcript = patient_visible_transcript(episode)
    contract = result_contract()
    work_order = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "episode_id": episode.episode_id,
        "case_id": episode.case_id,
        "arm": arm,
        "objective": ARM_RULES[arm]["objective"],
        "patient_visible_transcript": transcript,
        "source_boundary": ARM_RULES[arm],
        "result_contract": contract,
        "result_schema": result_schema(),
        "policy_anchors": policy_anchors.anchors_for(
            manifest.get("payer"), manifest.get("cpt"), manifest.get("state")
        ),
    }
    work_order_path = arm_dir / "work_order.json"
    contract_path = arm_dir / "result_contract.json"
    schema_path = arm_dir / "result_schema.json"
    prompt_path = arm_dir / "AGENT_PROMPT.txt"
    write_json_atomic(work_order_path, work_order)
    write_json_atomic(contract_path, contract)
    write_json_atomic(schema_path, result_schema())
    prompt_path.write_text(
        agent_prompt(episode, arm, work_order_path.resolve()),
        encoding="utf-8",
    )
    prompt_path.chmod(0o600)

    episode.log_event(
        role="orchestrator",
        arm=arm,
        event_type="retrieval_arm_prepared",
        status="succeeded",
        summary=f"Prepared isolated {arm} work order from patient-visible messages only.",
        artifacts=[
            str(work_order_path.relative_to(episode.root)),
            str(contract_path.relative_to(episode.root)),
            str(schema_path.relative_to(episode.root)),
            str(prompt_path.relative_to(episode.root)),
        ],
        details={
            "transcript_message_count": len(transcript),
            "work_order_sha256": sha256_file(work_order_path),
        },
    )
    return {
        "episode_id": episode.episode_id,
        "arm": arm,
        "arm_directory": str(arm_dir),
        "work_order_path": str(work_order_path),
        "prompt_path": str(prompt_path),
        "schema_path": str(schema_path),
        "prompt": prompt_path.read_text(encoding="utf-8"),
    }


def prepare_correction_arm(
    episode: Episode,
    arm: str,
    feedback: dict[str, Any],
) -> dict[str, Any]:
    if feedback.get("decision") not in {"rejected", "replaced"}:
        raise ValueError("only rejected or replaced source reviews require correction")
    revisions_root = episode.root / "system" / arm / "revisions"
    revisions_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    revision_number = len([path for path in revisions_root.glob("rev_*") if path.is_dir()]) + 1
    revision_dir = revisions_root / f"rev_{revision_number:03d}"
    revision_dir.mkdir(parents=True, exist_ok=False, mode=0o700)

    prior_result_path = episode.root / "system" / arm / "active_result.json"
    if not prior_result_path.exists():
        prior_result_path = episode.root / "system" / arm / "frozen_result.json"
    if not prior_result_path.exists():
        raise FileNotFoundError("cannot correct an arm without a prior frozen result")
    prior_result = json.loads(prior_result_path.read_text(encoding="utf-8"))
    replacement = feedback.get("replacement_source")
    replacement_absolute = (
        str((episode.root / replacement["path"]).resolve()) if replacement else None
    )
    work_order = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "episode_id": episode.episode_id,
        "case_id": episode.case_id,
        "arm": arm,
        "revision": revision_number,
        "patient_visible_transcript": patient_visible_transcript(episode),
        "human_source_feedback": {
            "decision": feedback["decision"],
            "notes": feedback.get("notes", ""),
            "rejected_source": feedback.get("selected_source"),
            "replacement_source": replacement,
            "replacement_absolute_path": replacement_absolute,
            "feedback_record_hash": feedback["record_hash"],
        },
        "prior_result": prior_result,
        "source_boundary": ARM_RULES[arm],
        "result_contract": result_contract(),
        "result_schema": result_schema(),
        "policy_anchors": policy_anchors.anchors_for(
            episode.manifest().get("payer"), episode.manifest().get("cpt"),
            episode.manifest().get("state"),
        ),
    }
    work_order_path = revision_dir / "work_order.json"
    contract_path = revision_dir / "result_contract.json"
    schema_path = revision_dir / "result_schema.json"
    prompt_path = revision_dir / "AGENT_PROMPT.txt"
    write_json_atomic(work_order_path, work_order)
    write_json_atomic(contract_path, result_contract())
    write_json_atomic(schema_path, result_schema())
    prompt_path.write_text(
        correction_prompt(
            episode,
            arm,
            work_order_path.resolve(),
            feedback["decision"],
        ),
        encoding="utf-8",
    )
    prompt_path.chmod(0o600)
    episode.log_event(
        role="orchestrator",
        arm=arm,
        event_type="correction_arm_prepared",
        status="succeeded",
        summary=f"Prepared {arm} correction revision {revision_number} after source {feedback['decision']}.",
        artifacts=[
            str(work_order_path.relative_to(episode.root)),
            str(prompt_path.relative_to(episode.root)),
        ],
        details={
            "revision": revision_number,
            "decision": feedback["decision"],
            "feedback_record_hash": feedback["record_hash"],
            "replacement_sha256": replacement.get("sha256") if replacement else None,
        },
    )
    return {
        "episode_id": episode.episode_id,
        "arm": arm,
        "revision": revision_number,
        "arm_directory": str(revision_dir),
        "work_order_path": str(work_order_path),
        "prompt_path": str(prompt_path),
        "schema_path": str(schema_path),
        "replacement_absolute_path": replacement_absolute,
        "prompt": prompt_path.read_text(encoding="utf-8"),
    }


def prepare_follow_up_arm(
    episode: Episode,
    arm: str,
    question: str,
    answer: str,
) -> dict[str, Any]:
    revisions_root = episode.root / "system" / arm / "revisions"
    revisions_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    revision_number = len([path for path in revisions_root.glob("rev_*") if path.is_dir()]) + 1
    revision_dir = revisions_root / f"rev_{revision_number:03d}"
    revision_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    prior_result_path = episode.root / "system" / arm / "active_result.json"
    if not prior_result_path.exists():
        prior_result_path = episode.root / "system" / arm / "result.json"
    if not prior_result_path.exists():
        raise FileNotFoundError("cannot continue dialogue without a prior arm result")
    prior_result = json.loads(prior_result_path.read_text(encoding="utf-8"))
    selected_source = prior_result.get("retrieval", {}).get("selected_source")
    if not selected_source:
        raise ValueError("cannot continue dialogue without a selected source")
    work_order = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "episode_id": episode.episode_id,
        "case_id": episode.case_id,
        "arm": arm,
        "revision": revision_number,
        "revision_type": "patient_follow_up",
        "patient_visible_transcript": patient_visible_transcript(episode),
        "answered_question": {"question": question, "answer": answer},
        "prior_result": prior_result,
        "locked_selected_source": selected_source,
        "source_boundary": ARM_RULES[arm],
        "result_contract": result_contract(),
        "result_schema": result_schema(),
    }
    work_order_path = revision_dir / "work_order.json"
    contract_path = revision_dir / "result_contract.json"
    schema_path = revision_dir / "result_schema.json"
    prompt_path = revision_dir / "AGENT_PROMPT.txt"
    write_json_atomic(work_order_path, work_order)
    write_json_atomic(contract_path, result_contract())
    write_json_atomic(schema_path, result_schema())
    prompt = f"""You are continuing the {arm} denial-navigation episode after the synthetic patient answered a targeted follow-up.

Read only:
{work_order_path.resolve()}

The selected policy is locked for this revision because it has already been chosen and may have been human-confirmed. Inspect that same source as needed. Incorporate the new patient answer, update the criterion-level gap analysis, determine whether any additional patient-answerable question is truly necessary, and regenerate the next actionable step.

Do not silently change the selected source. Do not invent clinical-record facts, deadlines, or coverage outcomes. Route provider-only evidence to the provider. Store observable summaries only, never private chain-of-thought.

After completing the analysis, make your FINAL RESPONSE one JSON object conforming exactly to `result_schema` in the work order. Do not wrap it in Markdown or return interim JSON. The controller will save it as:
{revision_dir / 'result.json'}

When practical, append observable events to:
{revision_dir / 'agent_events.jsonl'}
"""
    prompt_path.write_text(prompt, encoding="utf-8")
    prompt_path.chmod(0o600)
    episode.log_event(
        role="orchestrator",
        arm=arm,
        event_type="patient_follow_up_revision_prepared",
        status="succeeded",
        summary=f"Prepared {arm} revision {revision_number} using a new synthetic-patient answer.",
        artifacts=[
            str(work_order_path.relative_to(episode.root)),
            str(prompt_path.relative_to(episode.root)),
        ],
        details={
            "revision": revision_number,
            "question": question,
        },
    )
    return {
        "episode_id": episode.episode_id,
        "arm": arm,
        "revision": revision_number,
        "arm_directory": str(revision_dir),
        "work_order_path": str(work_order_path),
        "prompt_path": str(prompt_path),
        "schema_path": str(schema_path),
        "prompt": prompt,
    }


def prepare_both_arms(episode: Episode, workspace_root: Path) -> dict[str, Any]:
    return {
        arm: prepare_arm(episode, arm, workspace_root)
        for arm in ("library_only", "web_only")
    }
