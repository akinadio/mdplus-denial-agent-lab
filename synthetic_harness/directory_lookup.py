"""The OrthoAppeals policy lookup, one copy for the study and the live site.

The study measured OrthoAppeals answering every case straight from its policy
directory, with no model and no web search: find the plan's row for the state,
insurer and CPT code, and answer from the row's status. The live site used to
send search agents instead and treat the directory as a hint to verify. This
module is the study's path, moved out of scripts/study so both import the same
code and the site behaves the way the paper says it does.

  directory_row(payer, state, cpt)   the plan's row, or None
  study_covers(row)                  whether the study tested this row's status
  answer_from_row(...)               the policy answer the study recorded
  letter_input(...)                  what the letter writer is handed

Statuses the study never tested (UNREACHABLE, STALE, CODE ONLY, NO PRIOR AUTH
REQUIRED, the Medicare "NO LCD" rows) are not "no policy" -- they mean we do
not know yet. For those, and for a plan with no row, the site still searches.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLAT = ROOT / "data" / "policy_platform"
DIRECTORY = PLAT / "app_option_policy_directory.csv"
ACCESS = PLAT / "criteria_access_directory.json"

# Statuses present among the 167 study cases, so the answer for each was scored.
STUDY_STATUSES = (
    "VERIFIED",
    "DOCUMENT PUBLIC",
    "UM POLICY ONLY",
    "CONFIRMED NO POLICY",
    "NO PUBLIC CRITERIA",
    "PROCESS DOC ONLY",
    "GATED",
)
NO_STABLE_LINK = "VERIFIED (criteria public, no stable link"

_rows: list[dict[str, str]] | None = None


def _load() -> list[dict[str, str]]:
    global _rows
    if _rows is None:
        with DIRECTORY.open(encoding="utf-8", newline="") as fh:
            _rows = list(csv.DictReader(fh))
    return _rows


def reload() -> None:
    global _rows
    _rows = None


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\([^)]*\)", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_state(s: str) -> str:
    from .citation_cache import _normalize_state
    return _normalize_state(s or "")


def directory_row(payer: str, state: str, cpt: str) -> dict[str, str] | None:
    """The directory row for this plan, state and code. Exact match first (the
    study's rule, and what the site's own pick lists produce); then the same
    match ignoring case, spacing, parentheticals and state spelling."""
    cpt = re.sub(r"[^0-9]", "", cpt or "")
    rows = _load()
    for r in rows:
        if r["state"] == state and r["insurance_company"] == payer and r["cpt"] == cpt:
            return r
    p, st = _norm(payer), _norm_state(state)
    if not (p and st and cpt):
        return None
    for r in rows:
        if r["cpt"] == cpt and _norm(r["insurance_company"]) == p and _norm_state(r["state"]) == st:
            return r
    return None


def study_covers(row: dict[str, str] | None) -> bool:
    return bool(row) and any(row["status"].startswith(s) for s in STUDY_STATUSES)


def load_access() -> dict:
    return json.loads(ACCESS.read_text(encoding="utf-8")) if ACCESS.exists() else {}


def access_route(payer, note, access):
    ins = (payer or "").lower().strip()
    if ins in access:
        return access[ins]
    for k, v in access.items():
        if k.startswith("_"):
            continue
        if k in ins or ins in k:
            return v
    n = (note or "").lower()
    for v in ("evolent", "carelon", "evicore", "turningpoint", "interqual", "mcg"):
        if v in n and "_" + v in access:
            return access["_" + v]
    return {}


def route_for(payer: str, plan_type: str) -> str:
    """The real appeal route for this payer, not a placeholder."""
    from .policy_text import submission_route
    return submission_route(payer, plan_type or "")


def document_criteria(row, cpt, reason=""):
    """The plan's own words, read out of the plan's own document.

    `reason` is the denial reason from the notice, so the criteria that speak
    to it come first. A letter that quotes the BMI rule at someone denied for
    imaging findings has quoted the policy and argued nothing.
    """
    from .policy_text import criteria_for
    return criteria_for(row["policy_url"], cpt, reason=reason)["quotes"]


def answer_from_row(row, *, payer: str, cpt: str, plan_type: str = "",
                    appeal_deadline: str = "", denial_reason: str = "",
                    model: str = "", access: dict | None = None) -> dict[str, Any]:
    """The policy answer OrthoAppeals gives for this row. Identical to what the
    study recorded for every one of its 167 cases."""
    access = load_access() if access is None else access
    # "VERIFIED (criteria public, no stable link)" rows point at a policy INDEX
    # the patient has to browse from, not the governing document.
    if (row and row["status"].startswith("VERIFIED")
            and not row["status"].startswith(NO_STABLE_LINK)
            and row["policy_url"].strip()):
        return {"answer": {
            "policy_found": True,
            "policy_title": row["policy_title"], "policy_number": "",
            "policy_url": row["policy_url"], "effective_date": row["effective_date"],
            # Our own research note is not the plan's language. Real criteria
            # come from the document itself.
            "criteria_quotes": document_criteria(row, cpt, denial_reason),
            "appeal_deadline": appeal_deadline,
            "submission_route": route_for(payer, plan_type),
            "how_to_obtain_criteria": "",
            "confidence": "high",
            "notes": f"directory hit; status={row['status']}",
        }, "source": "policy_directory", "model": model}
    if row and row["status"].startswith(NO_STABLE_LINK) and row["policy_url"].strip():
        return {"answer": {
            "policy_found": True,
            "policy_title": row["policy_title"], "policy_number": "",
            "policy_url": row["policy_url"], "effective_date": row["effective_date"],
            "criteria_quotes": [],
            "appeal_deadline": appeal_deadline,
            "submission_route": route_for(payer, plan_type),
            "how_to_obtain_criteria": (
                "Your plan publishes these criteria but gives the document no "
                "permanent address. Open the policy list above and click through "
                "to the policy for your surgery -- that document is what your "
                "appeal should quote."),
            "confidence": "high",
            "notes": f"browse entry point, not a stable document; status={row['status']}",
        }, "source": "policy_index_entry", "model": model}

    # The payer's own policy is public and names the code, but sends criteria to
    # a private vendor tool. Cite it AND route.
    if row and row["status"].startswith("DOCUMENT PUBLIC") and row["policy_url"].strip():
        r = access_route(payer, row.get("note", ""), access)
        return {"answer": {
            "policy_found": True,
            "policy_title": row["policy_title"], "policy_number": "",
            "policy_url": row["policy_url"], "effective_date": row["effective_date"],
            "criteria_quotes": [],
            "appeal_deadline": appeal_deadline,
            "submission_route": route_for(payer, plan_type),
            "how_to_obtain_criteria": (r.get("how") or
                "This policy governs your procedure code but sends the medical "
                "criteria to a private review tool. Ask the plan in writing for "
                "the exact criteria used in your denial."),
            "confidence": "high",
            "notes": f"payer policy public, criteria vendor-held; status={row['status']}",
        }, "source": "policy_directory_vendor_held", "route": r, "model": model}

    r = access_route(payer, (row or {}).get("note", ""), access)
    how = (r.get("how") or
           "This plan does not publish criteria for this procedure. Ask the "
           "plan in writing for the exact criteria used in your denial.")
    if row and row["status"].startswith("UM POLICY ONLY") and row["policy_url"].strip():
        # The plan's general utilization-management policy says which vendor's
        # criteria apply -- worth pointing to, never presented as a policy that
        # governs this procedure (it does not mention it).
        how = (f"Your plan publishes no policy for this procedure. Its utilization "
               f"management policy ({row['policy_title']}, {row['policy_url']}) states "
               f"which clinical criteria it applies. Ask the plan in writing for the "
               f"exact criteria used in your denial. " + how)
    return {"answer": {
        "policy_found": False,
        "policy_title": "", "policy_number": "", "policy_url": "",
        "effective_date": "", "criteria_quotes": [],
        "appeal_deadline": appeal_deadline,
        "submission_route": route_for(payer, plan_type),
        "how_to_obtain_criteria": how,
        "confidence": "high",
        "notes": "no public criteria on file; abstained and routed",
    }, "source": "abstention_route", "route": r, "model": model}


def letter_input(ans: dict[str, Any], *, payer: str, plan_type: str, state: str,
                 procedure: str, cpt: str, denial_reason: str, denial_text: str,
                 directory_note: str = "") -> dict[str, Any]:
    """Shape a directory answer into what the letter writer expects.

    The excerpts handed to the letter are lifted verbatim out of the fetched
    document. Nothing goes in here that is not in the payer's document."""
    from .policy_text import criteria_for
    from .letter_inputs import enrich
    got = criteria_for((ans.get("policy_url") or "").strip(), cpt)
    quotes = got["quotes"]
    return enrich({
        "case_identification": {
            "payer": payer, "plan_name": payer,
            "product_type": plan_type, "state": state,
            "procedure": procedure, "cpt": cpt,
            "denial_language": denial_reason,
        },
        "policy_analysis": {
            "denial_category": denial_reason,
            "apparent_reason": denial_reason,
            "criteria_at_issue": quotes,
        },
        "retrieval": {
            "selected_source": {
                "title": ans.get("policy_title", ""),
                "url": ans.get("policy_url", ""),
                "effective_date": ans.get("effective_date", ""),
            },
            "citations": [
                {"claim": "plan criteria", "reference": ans.get("policy_title", ""),
                 "excerpt": q}
                for q in quotes
            ],
        },
    }, denial_text, payer=payer, plan_type=plan_type, directory_note=directory_note)


# ---------------------------------------------------------------- live site ----
# The site still runs its search agent for the step-by-step plan it shows the
# patient, but the policy and the letter come from here, exactly as in the study.

ANSWER_FILE = "directory_answer.json"


def live_answer(payer: str, state: str, cpt: str, denial_text: str, model: str = "") -> dict[str, Any] | None:
    """The study's answer for a live submission, or None when the study's path
    does not apply (no row, or a status the study never tested)."""
    row = directory_row(payer, state, cpt)
    if not study_covers(row):
        return None
    from .quote_relevance import reason_from_notice
    from .letter_inputs import appeal_deadline
    reason = reason_from_notice(denial_text or "")
    out = answer_from_row(row, payer=row["insurance_company"], cpt=row["cpt"],
                          plan_type=row.get("plan_type", ""),
                          appeal_deadline=appeal_deadline(denial_text or ""),
                          denial_reason=reason, model=model)
    out["row"] = {k: row.get(k, "") for k in ("state", "insurance_company", "plan_type",
                                             "surgery", "cpt", "status", "policy_title",
                                             "policy_url", "effective_date", "note")}
    out["denial_reason"] = reason
    return out


def agent_block(d: dict[str, Any] | None) -> str:
    """Tell the search agent what the directory already settled, so the plan it
    writes names the same policy the letter will cite."""
    if not d:
        return ""
    a = d.get("answer") or {}
    src = d.get("source")
    head = "\nGOVERNING POLICY FROM THE ORTHOAPPEALS DIRECTORY (authoritative, already verified)\n"
    if src in ("policy_directory", "policy_index_entry", "policy_directory_vendor_held"):
        body = (f"  Title: {a.get('policy_title')}\n  URL: {a.get('policy_url')}\n"
                f"  Effective date: {a.get('effective_date') or 'not stated'}\n"
                "Use exactly this document as retrieval.selected_source. Do not substitute "
                "another document. Quote criteria only from this document.\n")
        if src != "policy_directory":
            body += f"Its criteria cannot be quoted here. {a.get('how_to_obtain_criteria')}\n"
        return head + body
    return (head + "This plan publishes no policy for this procedure. Do not name any "
            "document as the governing policy. " + (a.get("how_to_obtain_criteria") or "") + "\n")


def apply_to_result(result: dict[str, Any] | None, d: dict[str, Any] | None) -> dict[str, Any] | None:
    """The agent's result with the policy replaced by the directory's. What the
    agent picked is kept alongside, so nothing is hidden."""
    if not result or not d:
        return result
    a = d.get("answer") or {}
    r = json.loads(json.dumps(result))
    ret = dict(r.get("retrieval") or {})
    ret["agent_selected_source"] = ret.get("selected_source")
    ret["agent_citations"] = ret.get("citations")
    if a.get("policy_url"):
        ret["selected_source"] = {
            "title": a.get("policy_title", ""), "url": a.get("policy_url", ""),
            "effective_date": a.get("effective_date") or None,
            "evidence_role": "governing_policy", "origin": "orthoappeals_directory",
        }
        ret["citations"] = [{"claim": "plan criteria", "reference": a.get("policy_title", ""),
                             "url": a.get("policy_url", ""), "excerpt": q, "verified": True}
                            for q in a.get("criteria_quotes") or []]
    else:
        ret["selected_source"] = {}
        ret["citations"] = []
    ret["directory"] = {"source": d.get("source"), "status": (d.get("row") or {}).get("status", ""),
                        "how_to_obtain_criteria": a.get("how_to_obtain_criteria", "")}
    r["retrieval"] = ret
    return r


_NOT_APPEALABLE = ("benefit exclusion", "excluded benefit", "not a covered benefit",
                   "not covered benefit", "plan exclusion", "contractual exclusion",
                   "excluded from coverage")


def assessment(d: dict[str, Any], denial_text: str) -> dict[str, Any]:
    """The study drafted a letter for every case: one quoting the criteria when
    the plan publishes them, one demanding them when it does not. A benefit
    exclusion is the one denial a letter of this kind does not answer."""
    t = (denial_text or "").lower()
    if any(m in t for m in _NOT_APPEALABLE):
        return {"recommended": False, "kind": "not_appealable",
                "reason": "This reads as a benefit exclusion rather than a medical-necessity "
                "denial, so a criteria-met appeal letter likely does not apply. A plan-level "
                "exception or benefits review is the better route."}
    if d.get("source") == "policy_directory":
        why = ("Your plan's governing policy is confirmed and its criteria are published, "
               "so the letter quotes the plan's own rules back to it.")
    else:
        why = ("Your plan does not publish the criteria it applied, so the letter asks the "
               "plan, in writing, for the exact criteria used in your denial.")
    return {"recommended": True, "kind": "appeal_letter", "reason": why, "documentation_gaps": []}


def letter_input_live(d: dict[str, Any], denial_text: str) -> dict[str, Any]:
    row = d.get("row") or {}
    return letter_input(d.get("answer") or {}, payer=row.get("insurance_company", ""),
                        plan_type=row.get("plan_type", ""), state=row.get("state", ""),
                        procedure=row.get("surgery", ""), cpt=row.get("cpt", ""),
                        denial_reason=d.get("denial_reason", ""), denial_text=denial_text,
                        directory_note=row.get("note", ""))
