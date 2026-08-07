"""Read a denial letter and/or an insurance card into structured, confidence-
scored fields — the step that lets OrthoAppeals pin the *exact* plan.

Why this module exists
----------------------
`letter_reader.transcribe()` turns an uploaded denial letter into plain text by
shelling out to the `claude` CLI. That is fine for a transcript, but a real
product needs three things it does not give us:

  1. **Structured fields, not prose.** We need the patient's name, the insurer,
     the *specific plan*, the member/group IDs, the denied CPT codes, the denial
     reason and the appeal deadline as discrete values we can act on and drop
     into the letter.
  2. **The insurance card, not just the letter.** An insurer like Aetna has
     dozens of plans, and the plan is what decides which coverage rule applies.
     The card is where the plan and member ID live. We must read it too.
  3. **Honesty about blur.** A phone photo is often partly unreadable. We must
     never *guess* a member ID or a plan. Every field carries a confidence, and
     anything low or missing is handed back to the patient to confirm — we do
     not invent it.

This talks to the model **API** (vision) directly, authenticated by a server
API key, so it is hostable with no CLI and no interactive login (same rationale
as `api_runner`). The model call is a small, injectable seam (`_client`, patched
in tests); all of the scoring/merging/pinning logic below it is pure and tested.
"""

from __future__ import annotations

import base64
import os
from typing import Any

from .agent_runner import extract_json

# Vision-capable model. Kept overridable; defaults to the same family the rest
# of the engine uses.
EXTRACT_MODEL = os.environ.get("MDPLUS_EXTRACT_MODEL", "claude-opus-5")
EXTRACT_TIMEOUT_S = int(os.environ.get("MDPLUS_EXTRACT_TIMEOUT_S", "120"))
MAX_TOKENS = int(os.environ.get("MDPLUS_EXTRACT_MAX_TOKENS", "2000"))

# Confidence vocabulary the model must use, worst to best.
_CONF_ORDER = {"unreadable": 0, "low": 1, "medium": 2, "high": 3}
# At or below this, we ask the patient to confirm rather than trust the read.
CONFIRM_AT_OR_BELOW = "low"

# Anthropic wants images and PDFs as different content-block shapes.
_IMAGE_MIMES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
_PDF_MIME = "application/pdf"


# --------------------------------------------------------------------------
# Field definitions per document kind.  required=True means: if it is missing
# or low-confidence, the patient is asked to confirm it before we build the
# appeal.  label is what the patient sees on the confirm screen.
# --------------------------------------------------------------------------
LETTER_FIELDS: list[dict[str, Any]] = [
    {"key": "patient_name", "label": "Your name", "required": True},
    {"key": "insurer_name", "label": "Insurance company", "required": True},
    {"key": "plan_name", "label": "Plan name", "required": False},
    {"key": "plan_type", "label": "Plan type (HMO, PPO, etc.)", "required": False},
    {"key": "member_id", "label": "Member ID", "required": False},
    {"key": "group_id", "label": "Group number", "required": False},
    {"key": "claim_number", "label": "Claim or reference number", "required": False},
    {"key": "denial_date", "label": "Date of the denial", "required": False},
    {"key": "appeal_deadline", "label": "Appeal deadline", "required": True},
    {"key": "denial_reason", "label": "Reason for the denial", "required": True},
]

CARD_FIELDS: list[dict[str, Any]] = [
    {"key": "member_name", "label": "Your name", "required": True},
    {"key": "insurer_name", "label": "Insurance company", "required": True},
    {"key": "plan_name", "label": "Plan name", "required": True},
    {"key": "plan_type", "label": "Plan type (HMO, PPO, etc.)", "required": True},
    {"key": "member_id", "label": "Member ID", "required": True},
    {"key": "group_number", "label": "Group number", "required": False},
    {"key": "rx_bin", "label": "Rx BIN", "required": False},
    {"key": "rx_pcn", "label": "Rx PCN", "required": False},
    {"key": "customer_service_phone", "label": "Member Services phone", "required": False},
    {"key": "payer_id", "label": "Payer ID", "required": False},
]

_FIELDS_BY_KIND = {"denial_letter": LETTER_FIELDS, "insurance_card": CARD_FIELDS}


# --------------------------------------------------------------------------
# Insurer canonicalization — the SAME buckets the frontend's accessFor/submitFor
# use, so a read of "Aetna Better Health" maps to the "aetna" directory entry.
# --------------------------------------------------------------------------
def canonical_insurer(name: str | None) -> str | None:
    n = (name or "").lower()
    if not n.strip():
        return None
    def has(*w: str) -> bool:
        return any(x in n for x in w)
    if has("unitedhealth", "uhc", "united health"):
        return "unitedhealthcare"
    if has("aetna"):
        return "aetna"
    if has("cigna"):
        return "cigna"
    if has("anthem", "elevance"):
        return "anthem"
    if has("humana"):
        return "humana"
    if has("ambetter", "centene", "wellcare"):
        return "centene"
    if has("molina"):
        return "molina"
    if has("florida blue", "guidewell"):
        return "floridablue"
    if has("medicaid"):
        return "medicaid"
    if has("medicare"):
        return "medicare"
    if has("blue cross", "blue shield", "bcbs", "hcsc", "carefirst", "highmark",
           "wellmark", "premera", "regence", "horizon"):
        return "bluecross"
    return None


def _coverage_line(insurer_key: str | None, plan_type: str | None) -> str:
    """Commercial vs Medicare vs Medicaid — the coarse bucket that changes which
    appeal rules and deadlines apply."""
    if insurer_key == "medicare":
        return "medicare"
    if insurer_key == "medicaid":
        return "medicaid"
    pt = (plan_type or "").lower()
    if "medicare" in pt or "advantage" in pt or "part d" in pt:
        return "medicare"
    if "medicaid" in pt:
        return "medicaid"
    return "commercial"


# --------------------------------------------------------------------------
# Prompts.  Strict JSON, per-field confidence, and an explicit instruction to
# never guess.  The model is told to use "unreadable" rather than invent.
# --------------------------------------------------------------------------
_CONF_RULE = (
    'For every field give a "confidence": one of "high" (clearly legible and '
    'certain), "medium" (legible but partly inferred), "low" (barely legible or '
    'a guess), or "unreadable" (cannot make it out). NEVER invent a value to '
    'look complete: if you cannot read it, set value to null and confidence to '
    '"unreadable". Copy IDs, numbers, dates and codes EXACTLY as printed.'
)

_LETTER_PROMPT = (
    "These images/PDF pages are one health-insurance DENIAL letter. Extract the "
    "following as strict JSON and nothing else.\n\n"
    'Return: {"document_type": "denial_letter" | "other", "fields": { '
    '"patient_name", "insurer_name", "plan_name", "plan_type", "member_id", '
    '"group_id", "claim_number", "denial_date", "appeal_deadline", '
    '"denial_reason" }, "denied_procedures": [ {"code","description",'
    '"decision","confidence"} ] }.\n'
    "Each field in \"fields\" is an object {\"value\", \"confidence\"}. "
    "appeal_deadline is the date or window by which the patient must appeal "
    "(e.g. '180 days from this notice' or an explicit date) — take it verbatim. "
    "denial_reason is a short quote of why it was denied. denied_procedures "
    "lists each CPT/HCPCS code with what happened to it (DENIED/APPROVED).\n"
    'Also include "letter_text": a plain-text verbatim transcription of the '
    "whole letter, preserving line order, with [illegible] for anything you "
    "cannot read. This is what the appeal engine reads, so do not summarise it.\n"
    'If these are not a denial letter, return {"document_type":"other"} and an '
    "empty fields object.\n\n" + _CONF_RULE
)

_CARD_PROMPT = (
    "These images are the front and/or back of one health-insurance ID CARD. "
    "Extract the following as strict JSON and nothing else.\n\n"
    'Return: {"document_type": "insurance_card" | "other", "fields": { '
    '"member_name", "insurer_name", "plan_name", "plan_type", "member_id", '
    '"group_number", "rx_bin", "rx_pcn", "customer_service_phone", "payer_id" } }.\n'
    "Each field is an object {\"value\", \"confidence\"}. plan_type is the "
    "product kind printed on the card (HMO, PPO, EPO, POS, HDHP, Medicare "
    "Advantage, etc.). plan_name is the specific plan/product name, which is "
    "what tells us which coverage rules apply — read it carefully.\n"
    'If these are not an insurance card, return {"document_type":"other"} and '
    "an empty fields object.\n\n" + _CONF_RULE
)

_PROMPT_BY_KIND = {"denial_letter": _LETTER_PROMPT, "insurance_card": _CARD_PROMPT}


# --------------------------------------------------------------------------
# Model seam.  _client is module-level so tests patch it, exactly like
# api_runner._client.
# --------------------------------------------------------------------------
def _client(timeout: int):
    import anthropic

    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=int(os.environ.get("MDPLUS_API_MAX_RETRIES", "4")),
        timeout=float(timeout),
    )


def _content_blocks(files: list[dict[str, Any]], prompt: str) -> list[dict[str, Any]]:
    """Turn decoded attachments (from letter_reader.decode_attachments) into an
    Anthropic vision message: the images/PDFs first, then the instruction."""
    blocks: list[dict[str, Any]] = []
    for f in files:
        mime = f["mime"]
        data = base64.b64encode(f["bytes"]).decode("ascii")
        if mime == _PDF_MIME:
            blocks.append({
                "type": "document",
                "source": {"type": "base64", "media_type": _PDF_MIME, "data": data},
            })
        elif mime in _IMAGE_MIMES:
            media = "image/jpeg" if mime == "image/jpg" else mime
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media, "data": data},
            })
    blocks.append({"type": "text", "text": prompt})
    return blocks


def _raw_extract(files: list[dict[str, Any]], kind: str, *, client=None,
                 model: str | None = None) -> dict[str, Any]:
    """Call the vision model and return the parsed JSON (or a failure record).

    Never raises for a bad read; the caller decides what to show the patient.
    """
    if kind not in _PROMPT_BY_KIND:
        raise ValueError(f"unknown document kind: {kind}")
    if not files:
        return {"outcome": "no files", "document_type": None, "fields": {}}
    model = model or EXTRACT_MODEL
    own = client is None
    if own:
        client = _client(EXTRACT_TIMEOUT_S)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": _content_blocks(files, _PROMPT_BY_KIND[kind])}],
        )
    except Exception as exc:  # pragma: no cover - network/SDK failure path
        return {"outcome": "reader error", "error": str(exc)[:300],
                "document_type": None, "fields": {}}
    usage = {"input_tokens": 0, "output_tokens": 0}
    u = getattr(resp, "usage", None)
    if u is not None:
        usage["input_tokens"] = getattr(u, "input_tokens", 0) or 0
        usage["output_tokens"] = getattr(u, "output_tokens", 0) or 0
    text = "".join(getattr(b, "text", "") for b in getattr(resp, "content", [])
                   if getattr(b, "type", None) == "text")
    obj = extract_json(text)
    if not isinstance(obj, dict):
        return {"outcome": "unparseable", "raw": text[:300],
                "document_type": None, "fields": {}, "_usage": usage}
    obj.setdefault("outcome", "read")
    obj.setdefault("fields", {})
    obj["_usage"] = usage
    return obj


# --------------------------------------------------------------------------
# Scoring — pure, fully tested.
# --------------------------------------------------------------------------
def _norm_conf(value: Any, conf: Any) -> str:
    """Collapse an empty/illegible value to 'unreadable' regardless of what the
    model claimed, so a blank never sails through as high-confidence."""
    c = str(conf or "").lower().strip()
    if c not in _CONF_ORDER:
        c = "low"
    v = value
    if v is None:
        return "unreadable"
    s = str(v).strip()
    if not s or s.lower() in {"[illegible]", "illegible", "n/a", "none", "null", "unknown"}:
        return "unreadable"
    return c


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in {"[illegible]", "illegible", "n/a", "none", "null", "unknown"}:
        return None
    return s


def score_document(raw: dict[str, Any], kind: str) -> dict[str, Any]:
    """Normalize a raw model extraction into per-field {value, confidence,
    needs_confirmation} plus a document-level summary and the list of fields the
    patient should confirm."""
    fields_spec = _FIELDS_BY_KIND[kind]
    raw_fields = raw.get("fields") or {}
    doc_type = raw.get("document_type")

    scored: dict[str, Any] = {}
    confirm: list[dict[str, Any]] = []
    have_any = False

    for spec in fields_spec:
        key = spec["key"]
        cell = raw_fields.get(key) or {}
        if not isinstance(cell, dict):
            cell = {"value": cell, "confidence": "medium"}
        value = _clean_value(cell.get("value"))
        conf = _norm_conf(cell.get("value"), cell.get("confidence"))
        weak = _CONF_ORDER[conf] <= _CONF_ORDER[CONFIRM_AT_OR_BELOW]
        needs = spec["required"] and (value is None or weak)
        scored[key] = {
            "value": value,
            "confidence": conf,
            "label": spec["label"],
            "required": spec["required"],
            "needs_confirmation": needs,
        }
        if value is not None and _CONF_ORDER[conf] >= _CONF_ORDER["medium"]:
            have_any = True
        if needs:
            confirm.append({
                "key": key,
                "label": spec["label"],
                "value": value,
                "confidence": conf,
                "reason": "missing" if value is None else "hard to read",
            })

    procedures = []
    for p in raw.get("denied_procedures") or []:
        if not isinstance(p, dict):
            continue
        procedures.append({
            "code": _clean_value(p.get("code")),
            "description": _clean_value(p.get("description")),
            "decision": _clean_value(p.get("decision")),
            "confidence": _norm_conf(p.get("code"), p.get("confidence")),
        })

    if raw.get("outcome") in {"no files", "reader error", "unparseable"}:
        outcome = raw["outcome"]
    elif doc_type == "other":
        outcome = "wrong_document"
    elif not have_any:
        outcome = "unreadable"
    else:
        outcome = "read"

    return {
        "kind": kind,
        "outcome": outcome,
        "document_type": doc_type,
        "fields": scored,
        "denied_procedures": procedures,
        "needs_confirmation": confirm,
    }


# --------------------------------------------------------------------------
# Merge + plan pin — combine card and letter into one identity, and decide
# whether we can name the *exact* plan or must ask.
# --------------------------------------------------------------------------
def _pick(*cells: dict[str, Any] | None) -> dict[str, Any]:
    """Choose the highest-confidence non-empty reading of a field across docs."""
    best = {"value": None, "confidence": "unreadable"}
    for c in cells:
        if not c or c.get("value") is None:
            continue
        if _CONF_ORDER[c["confidence"]] > _CONF_ORDER[best["confidence"]]:
            best = {"value": c["value"], "confidence": c["confidence"]}
    return best


def pin_plan(card: dict[str, Any] | None, letter: dict[str, Any] | None) -> dict[str, Any]:
    """Return the best identity we can form and whether it is solid enough to
    pin the specific plan, or needs the patient to confirm.

    The card is the authority on plan identity; the letter backfills."""
    cf = (card or {}).get("fields", {})
    lf = (letter or {}).get("fields", {})

    name = _pick(cf.get("member_name"), lf.get("patient_name"))
    insurer = _pick(cf.get("insurer_name"), lf.get("insurer_name"))
    plan_name = _pick(cf.get("plan_name"), lf.get("plan_name"))
    plan_type = _pick(cf.get("plan_type"), lf.get("plan_type"))
    member_id = _pick(cf.get("member_id"), lf.get("member_id"))

    insurer_key = canonical_insurer(insurer["value"])
    coverage = _coverage_line(insurer_key, plan_type["value"])

    # Can we pin the EXACT plan? We need a known insurer AND a plan name/type we
    # actually read with some confidence. Government coverage (Medicare/Medicaid)
    # is pinned by the coverage line itself, not a commercial plan name.
    reasons: list[str] = []
    if coverage in {"medicare", "medicaid"}:
        pinned = insurer_key is not None
        if not pinned:
            reasons.append("We could not tell which program this is.")
    else:
        strong_plan = plan_name["value"] and _CONF_ORDER[plan_name["confidence"]] >= _CONF_ORDER["medium"]
        pinned = bool(insurer_key) and bool(strong_plan)
        if not insurer_key:
            reasons.append("We could not read your insurance company.")
        elif not plan_name["value"]:
            reasons.append("We have your insurer but not the exact plan name — most insurers have many plans.")
        elif not strong_plan:
            reasons.append("The plan name was hard to read, so we want you to confirm it.")

    return {
        "identity": {
            "name": name,
            "insurer_name": insurer,
            "insurer_key": insurer_key,
            "plan_name": plan_name,
            "plan_type": plan_type,
            "member_id": member_id,
            "coverage_line": coverage,
        },
        "pinned": pinned,
        "reasons": reasons,
    }


def read_intake(*, letter_files: list[dict[str, Any]] | None = None,
                card_files: list[dict[str, Any]] | None = None,
                client=None, model: str | None = None) -> dict[str, Any]:
    """Top-level: read whatever the patient uploaded (letter and/or card),
    score both, pin the plan, and return one intake record.

    `needs_confirmation` is the union across documents — the exact list the
    frontend shows on the 'confirm what we read' screen. When it is empty and
    `plan.pinned` is true, the appeal can be built without asking anything."""
    letter = None
    card = None
    usage = {"input_tokens": 0, "output_tokens": 0}

    def _run(files, kind):
        raw = _raw_extract(files, kind, client=client, model=model)
        u = raw.get("_usage") or {}
        usage["input_tokens"] += u.get("input_tokens", 0)
        usage["output_tokens"] += u.get("output_tokens", 0)
        rec = score_document(raw, kind)
        if kind == "denial_letter":
            # The verbatim transcription the appeal engine reads, so the whole
            # flow runs through the API with no CLI reader.
            rec["text"] = _clean_value(raw.get("letter_text")) or None
        return rec

    if letter_files:
        letter = _run(letter_files, "denial_letter")
    if card_files:
        card = _run(card_files, "insurance_card")

    confirm: list[dict[str, Any]] = []
    for doc, src in ((letter, "denial letter"), (card, "insurance card")):
        if not doc:
            continue
        for item in doc["needs_confirmation"]:
            confirm.append({**item, "source": src})

    plan = pin_plan(card, letter)
    if not plan["pinned"]:
        # Surface the plan ambiguity as its own confirmation ask if not already
        # covered by a field-level flag.
        for r in plan["reasons"]:
            confirm.append({"key": "plan", "label": "Your exact plan",
                            "value": plan["identity"]["plan_name"]["value"],
                            "confidence": plan["identity"]["plan_name"]["confidence"],
                            "reason": r, "source": "plan"})

    read_ok = any(d and d["outcome"] == "read" for d in (letter, card))
    return {
        "outcome": "read" if read_ok else "needs_upload_or_unreadable",
        "letter": letter,
        "card": card,
        "plan": plan,
        "needs_confirmation": confirm,
        "usage": usage,
    }
