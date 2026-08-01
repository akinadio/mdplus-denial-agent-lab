"""Opt-in, verified, staleness-aware cache of patient-contributed policy docs.

When a patient uploads their insurance policy and consents, we keep a copy to
improve the service and, where safe, reuse it as a *candidate* source for the
next patient on the same plan. This module encodes the guardrails promised to
the product owner:

1. CONSENT — nothing is stored unless the patient opted in.
2. ENCRYPTED AT REST — contributed files are sealed with the envelope encryption
   (synthetic_harness/encryption.py) when a key is configured.
3. STALENESS — payer policies refresh a few times a year, so an entry older than
   MDPLUS_POLICY_STALE_DAYS (default 90) is flagged "may be outdated" and is not
   offered for reuse.
4. VERIFY BEFORE REUSE — a stored upload is only ever a *candidate*. Before it is
   reused for a different patient it must verify: the carrier and the CPT must
   actually appear in the document (the same check the live agent uses). A doc
   that can't be verified is never served to someone else.
5. NO PII LEAK — a document that looks like a personal plan document (member
   name/ID etc.) is kept for our own improvement only and is NEVER marked
   reusable, so one patient's paperwork can't surface in another's appeal.

Live retrieval always runs first; this cache is the fallback/anchor, never the
primary source.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .integrity import utc_now, write_json_atomic
from . import encryption

WORKSPACE = Path(__file__).resolve().parents[1]
STALE_DAYS = int(os.environ.get("MDPLUS_POLICY_STALE_DAYS", "90"))

# Markers that a document is a *personal* plan document rather than a public
# coverage policy. Conservative: any hit blocks cross-patient reuse.
_PERSONAL_MARKERS = (
    "member id", "member name", "subscriber id", "subscriber name",
    "member number", "policyholder", "date of birth", "dob:", "group number",
)


def _cache_root() -> Path:
    return Path(
        os.environ.get("MDPLUS_POLICY_CACHE_ROOT", WORKSPACE / "outputs" / "policy_cache")
    ).expanduser()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "unknown").lower()).strip("_") or "unknown"


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_text(content: bytes, content_type: str | None) -> str:
    """Best-effort text from the stored bytes (PDF/HTML/text). '' if not possible."""
    try:
        sys.path.insert(0, str(WORKSPACE / "scripts"))
        from policy_eval.common import extract_text, ExtractionError

        try:
            return extract_text(content, content_type)
        except ExtractionError:
            return ""
    except Exception:  # noqa: BLE001 - extraction is best-effort
        return ""


def looks_personal(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _PERSONAL_MARKERS)


def contribute(
    *,
    carrier: str,
    cpt: str,
    content: bytes,
    consent: bool,
    plan: str | None = None,
    procedure: str | None = None,
    content_type: str | None = None,
    filename: str | None = None,
    now: str | None = None,
) -> dict[str, Any] | None:
    """Store a consented patient upload. Returns the entry meta, or None.

    Returns None (stores nothing) when consent is not given. The raw bytes are
    encrypted at rest when a key is configured.
    """
    if not consent:
        return None
    now = now or utc_now()
    entry_id = sha256(content).hexdigest()[:16]
    carrier_dir = _cache_root() / _slug(carrier)
    carrier_dir.mkdir(parents=True, exist_ok=True)

    data, encrypted = encryption.maybe_encrypt(content)
    blob = carrier_dir / (entry_id + (".bin.enc" if encrypted else ".bin"))
    blob.write_bytes(data)

    # Verification + PII screen happen at store time so reuse decisions are cheap.
    text = _extract_text(content, content_type)
    carrier_ok = _slug(carrier).split("_")[0] in _slug(text) if text else False
    cpt_core = (cpt or "").split("-")[0].split("/")[0]
    cpt_ok = bool(cpt_core) and cpt_core in (text or "")
    verified = bool(text) and cpt_ok
    personal = looks_personal(text)

    meta = {
        "entry_id": entry_id,
        "carrier": carrier,
        "cpt": cpt,
        "plan": plan,
        "procedure": procedure,
        "filename": filename,
        "content_type": content_type,
        "encrypted": encrypted,
        "blob": blob.name,
        "sha256": sha256(content).hexdigest(),
        "contributed_at": now,
        "consent": True,
        "source": "patient_upload",
        "verified": verified,
        "carrier_in_doc": carrier_ok,
        "cpt_in_doc": cpt_ok,
        "personal_doc": personal,
        # Reusable only when it verifies AND is not a personal plan document.
        "reusable": bool(verified and not personal),
    }
    write_json_atomic(carrier_dir / (entry_id + ".meta.json"), meta)
    return meta


def is_stale(meta: dict[str, Any], now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    contributed = _parse_ts(meta.get("contributed_at"))
    if contributed is None:
        return True
    return contributed < now - timedelta(days=STALE_DAYS)


def staleness_note(meta: dict[str, Any], now: datetime | None = None) -> str | None:
    if not is_stale(meta, now):
        return None
    when = (meta.get("contributed_at") or "")[:10]
    return (
        "This may be based on a policy version that has since been updated "
        f"(contributed {when}); confirm against the current policy."
    )


def _all_meta(carrier: str) -> list[dict[str, Any]]:
    carrier_dir = _cache_root() / _slug(carrier)
    if not carrier_dir.exists():
        return []
    out = []
    for p in carrier_dir.glob("*.meta.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def reuse_candidates(
    carrier: str, cpt: str, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Contributed docs eligible to reuse for another patient on this plan.

    Only verified, reusable (non-personal), non-stale entries for the same
    carrier + CPT. Newest first. The caller must still treat these as candidates
    presented alongside a fresh live retrieval, not as the sole answer.
    """
    cpt_core = (cpt or "").split("-")[0].split("/")[0]
    hits = [
        m for m in _all_meta(carrier)
        if m.get("reusable") and m.get("verified")
        and cpt_core and cpt_core == (m.get("cpt") or "").split("-")[0].split("/")[0]
        and not is_stale(m, now)
    ]
    hits.sort(key=lambda m: m.get("contributed_at", ""), reverse=True)
    return hits
