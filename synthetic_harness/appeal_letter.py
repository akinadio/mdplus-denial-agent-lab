"""Denial-reason-aware output: decide the right next move, and draft the letter.

The retrieval agent already classifies *why* the claim was denied and cites the
payer's own policy language. This module turns that into the patient/doctor
deliverable:

- `assess_letter(result)` is the explicit branch on the denial reason. Not every
  denial should produce an appeal letter. A genuine benefit exclusion is not won
  by a medical-necessity letter; criteria that are truly unmet need to be *met*
  first; a blocked run has nothing to cite. Only a denial that turns on
  documentation or administrative grounds -- with a confirmed governing policy to
  quote -- calls for a letter now. The function returns that decision and a
  plain-language reason, so the UI can show "do this first" when a letter is not
  yet the right step.

- `generate_appeal_letter(...)` drafts a provider-to-payer appeal letter grounded
  in the retrieved citations, in the voice we want: simple, doctor-friendly, and
  framing the denial as the payer's decision measured against the payer's own
  published criteria -- without inflammatory or accusatory language, and without
  promising coverage. It never invents PHI: patient/provider specifics are left
  as clearly-marked placeholders for the surgeon's office to fill.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .api_runner import DEFAULT_API_MODEL, _client, _estimate_cost

# A criteria-met appeal letter does not fit a contractual benefit exclusion.
_NOT_APPEALABLE_MARKERS = (
    "benefit exclusion",
    "excluded benefit",
    "not a covered benefit",
    "not covered benefit",
    "plan exclusion",
    "contractual exclusion",
    "excluded from coverage",
)


def _clean(items: Any) -> list[str]:
    return [str(x).strip() for x in (items or []) if str(x).strip()]


def assess_letter(result: dict[str, Any]) -> dict[str, Any]:
    """Decide what the denial reason calls for. See module docstring.

    kind is one of: "appeal_letter" (recommended), "gather_first",
    "meet_criteria", "not_appealable", "blocked".
    """
    status = result.get("status")
    pa = result.get("policy_analysis") or {}
    category = (pa.get("denial_category") or "").lower()
    retrieval = result.get("retrieval") or {}
    source = retrieval.get("selected_source") or {}
    citations = retrieval.get("citations") or []
    grounded = (
        bool(source)
        and source.get("evidence_role") == "governing_policy"
        and len(citations) >= 1
    )

    if status == "blocked":
        return {
            "recommended": False,
            "kind": "blocked",
            "reason": "The retrieval was blocked, so there is no verified policy "
            "to cite yet. Resolve the blocker before drafting a letter.",
        }
    if not grounded:
        return {
            "recommended": False,
            "kind": "gather_first",
            "reason": "No governing policy with citations is confirmed yet, so a "
            "grounded appeal letter can't be drafted. Confirm the policy source "
            "first, then generate the letter.",
        }
    if any(m in category for m in _NOT_APPEALABLE_MARKERS):
        return {
            "recommended": False,
            "kind": "not_appealable",
            "reason": "This reads as a benefit exclusion rather than a "
            "medical-necessity denial, so a criteria-met appeal letter likely "
            "does not apply. A plan-level exception or benefits review is the "
            "better route.",
        }
    unmet = _clean(pa.get("unmet_criteria"))
    gaps = _clean(pa.get("documentation_gaps"))
    if unmet and not gaps:
        return {
            "recommended": False,
            "kind": "meet_criteria",
            "reason": "The plan's criteria appear genuinely unmet (not just "
            "undocumented). The next step is to complete or meet those criteria "
            "before appealing.",
            "unmet_criteria": unmet,
        }
    return {
        "recommended": True,
        "kind": "appeal_letter",
        "reason": "A governing policy is confirmed and the denial turns on "
        "documentation or administrative grounds, so a grounded appeal letter "
        "citing the plan's own criteria is the right next step.",
        "documentation_gaps": gaps,
    }


# Shared across both voices: grounding, framing, and format rules.
_LETTER_COMMON = (
    "\n\nVOICE: simple and clear enough for a patient to read, warm, and firmly "
    "on the side of the patient and their doctor. Frame the denial as the "
    "insurer's own decision, and show it is contradicted by the insurer's OWN "
    "published criteria: 'the plan's policy states X; the records establish X.' "
    "Put the responsibility on the payer, not the patient or the physician -- "
    "but do it through calm, factual, professional framing. Do NOT use sarcasm, "
    "outrage, or explicitly accusatory language, and never promise or guarantee "
    "that coverage will be approved. "
    "\n\nGROUNDING: cite only the policy language provided to you. Do not invent "
    "policy criteria, statutes, deadlines, or facts. Where a patient- or "
    "chart-specific detail is needed (member ID, date of service, provider "
    "name, specific clinical findings), insert a clearly-marked placeholder in "
    "square brackets to be completed -- never fabricate it. "
    "\n\nFORMAT: return the letter as Markdown. Include a subject/RE line "
    "referencing the denial, a short opening stating the request for "
    "reconsideration, a body that quotes the plan's own criteria and maps each "
    "to the evidence, a closing request, and a placeholder signature block. End "
    "with a one-line italic note that this letter is not medical or legal advice "
    "and does not guarantee coverage."
)

SENDER_SYSTEM_PROMPTS = {
    "provider": (
        "You draft health-insurance appeal letters for a surgeon's office to "
        "send to a payer. Write the letter the ordering physician's office would "
        "sign, in the third person about the patient (the physician is the "
        "author, requesting reconsideration on the patient's behalf)."
        + _LETTER_COMMON
    ),
    "patient": (
        "You draft health-insurance appeal letters for the patient (the plan "
        "member) to send to their payer themselves. Write in the first person "
        "from the patient's point of view ('I am appealing the denial of...'), "
        "in plain language, noting that their surgeon has documented that the "
        "procedure is needed. It is a member appeal, not a physician letter."
        + _LETTER_COMMON
    ),
}
# Backwards-compatible alias.
LETTER_SYSTEM_PROMPT = SENDER_SYSTEM_PROMPTS["provider"]


def _ground_citations(result: dict[str, Any]) -> dict[str, Any]:
    """Verify every citation against the payer's own document before the
    letter can quote it.

    Grading 120 letters on 2026-09-05 found invented criteria in quotation marks
    on 47% of in-library cases. The model was not at fault: it was handed our
    internal research notes under the heading "criteria" and told to quote the
    plan. So the document is read here, and:

      readable   -> a caller excerpt is kept only if it is actually in the text;
                    the document's own criteria sentences are added, verbatim;
                    everything else is dropped and counted.
      unreadable -> caller excerpts are kept but marked UNVERIFIED. The prompt
                    then allows them to be paraphrased and attributed, never
                    placed in quotation marks. Throwing real evidence away
                    because a PDF timed out would be its own kind of wrong.
    """
    from synthetic_harness.policy_text import criteria_for, verify_quote

    retrieval = result.get("retrieval") or {}
    source = retrieval.get("selected_source") or {}
    url = (source.get("url") or "").strip()
    given = [c for c in (retrieval.get("citations") or []) if (c or {}).get("excerpt")]
    if not url:
        return result
    cpt = str((result.get("case_identification") or {}).get("cpt") or "")
    got = criteria_for(url, cpt)
    text = got.get("text") or ""
    grounded = dict(result)

    if not text:
        cites = [dict(c, verified=False) for c in given]
        grounded["_criteria_source"] = "unverified"
    else:
        kept = [dict(c, verified=True) for c in given if verify_quote(c["excerpt"], text)]
        seen = {c["excerpt"][:80].lower() for c in kept}
        for q in got["quotes"]:
            if q[:80].lower() not in seen:
                kept.append({"claim": "plan criteria", "reference": source.get("title", ""),
                             "excerpt": q, "verified": True})
        cites = kept
        grounded["_criteria_source"] = got["source"]
        grounded["_citations_dropped"] = len(given) - sum(
            1 for c in given if verify_quote(c["excerpt"], text))
    grounded["retrieval"] = dict(retrieval, citations=cites)
    return grounded


def _letter_context(result: dict[str, Any], patient_submission: str | None) -> str:
    ci = result.get("case_identification") or {}
    pa = result.get("policy_analysis") or {}
    retrieval = result.get("retrieval") or {}
    source = retrieval.get("selected_source") or {}
    citations = retrieval.get("citations") or []

    lines = ["CASE"]
    for label, key in (
        # Whatever the denial notice gave us about the person. Without these
        # the letter opens with [Member Name] and [Member ID] and a reviewer
        # reads it as unfinished -- 67% of our in-library letters did.
        ("Member name", "member_name"),
        ("Member ID", "member_id"),
        ("Date of birth", "dob"),
        ("Denial date", "denial_date"),
        ("Reference number", "reference_number"),
        ("Payer", "payer"),
        ("Plan", "plan_name"),
        ("Product", "product_type"),
        ("State", "state"),
        ("Procedure", "procedure"),
        ("CPT", "cpt"),
        ("Denial language", "denial_language"),
    ):
        if ci.get(key):
            lines.append(f"- {label}: {ci[key]}")

    lines.append("\nDENIAL ANALYSIS")
    if pa.get("denial_category"):
        lines.append(f"- Category: {pa['denial_category']}")
    if pa.get("apparent_reason"):
        lines.append(f"- Apparent reason: {pa['apparent_reason']}")
    for label, key in (
        ("Criteria at issue", "criteria_at_issue"),
        ("Documentation gaps", "documentation_gaps"),
    ):
        vals = _clean(pa.get(key))
        if vals:
            lines.append(f"- {label}: " + "; ".join(vals))

    # A Medicare Advantage case gets its federal argument regardless of what
    # the policy retrieval found: since 2024 (CMS-4201-F), 42 CFR 422.101(b)
    # requires MA plans to follow Medicare's own coverage criteria, and any
    # internal criteria they apply where Medicare has none must be publicly
    # accessible. For a denial resting on InterQual/MCG-style private criteria
    # this is often the strongest sentence in the letter.
    product = (ci.get("product_type") or "").lower()
    if "medicare advantage" in product or re.search(r"\bMA\b|\bpart c\b|d-?snp", product, re.IGNORECASE):
        lines.append(
            "\nMEDICARE ADVANTAGE (include this argument)\n"
            "- This is a Medicare Advantage plan. Under 42 CFR 422.101(b) "
            "(CMS-4201-F, effective 2024) it must follow Medicare's own "
            "coverage criteria (NCDs/LCDs). Where no Medicare criteria exist, "
            "any internal coverage criteria it applies must be based on "
            "current evidence and made publicly accessible. If the denial "
            "rests on criteria the plan keeps private, demand the NCD/LCD it "
            "relied on or the exact public location of the internal criteria "
            "used.")

    # A letter with no deadline and no address is not sendable. The retrieval
    # step finds both; before 2026-09-05 neither was passed through to here, so
    # every drafted letter silently omitted them.
    deadline = (result.get("appeal_deadline") or "").strip()
    route = (result.get("submission_route") or "").strip()
    if deadline or route:
        lines.append("\nDEADLINE AND SUBMISSION (state both in the letter)")
        if deadline:
            lines.append(f"- Appeal must be received by: {deadline}")
        if route:
            lines.append(f"- Send it to: {route}")

    req = (result.get("criteria_request") or "").strip()
    if req:
        lines.append("\nCRITERIA REQUEST (the letter must make this demand, in its own "
                     "paragraph: the plan holds the criteria it applied and must provide "
                     "them in writing)")
        lines.append(req)

    lines.append("\nGOVERNING POLICY (cite this, and only this)")
    if source.get("title"):
        lines.append(f"- Title: {source['title']}")
    if source.get("url"):
        lines.append(f"- URL: {source['url']}")
    if source.get("effective_date"):
        lines.append(f"- Effective date: {source['effective_date']}")

    verified = [c for c in citations if (c or {}).get("verified", True)]
    unverified = [c for c in citations if not (c or {}).get("verified", True)]
    lines.append("\nPOLICY CITATIONS (the plan's own language, verbatim -- these may be quoted)")
    if not verified:
        lines.append("(none -- nothing here may be placed in quotation marks. Do not "
                     "quote the plan anywhere in this letter. Say that the plan's "
                     "criteria have not been quoted and ask for them in writing.)")
    for i, c in enumerate(verified, 1):
        lines.append(f"{i}. Claim: {c.get('claim', '')}\n   Reference: {c.get('reference', '')}"
                     f"\n   Excerpt: \"{c.get('excerpt', '')}\"")
    if unverified:
        lines.append("\nUNVERIFIED CITATIONS (the policy could not be read to confirm "
                     "these -- you may paraphrase and attribute them, e.g. 'the policy "
                     "addresses...', but NEVER put them in quotation marks or present "
                     "them as the plan's exact words)")
        for i, c in enumerate(unverified, 1):
            lines.append(f"{i}. {c.get('claim', '')}: {c.get('excerpt', '')}")

    notice = (result.get("denial_notice_text") or "").strip()
    if notice:
        lines.append("\nTHE DENIAL NOTICE, AS RECEIVED (take names, IDs, dates and the "
                     "reference number from here; do not leave a placeholder for "
                     "anything it states)")
        lines.append(notice[:6000])

    if patient_submission:
        lines.append("\nPATIENT-PROVIDED CONTEXT (use only what is clearly stated)")
        lines.append(patient_submission.strip()[:4000])

    return "\n".join(lines)


def generate_appeal_letter(
    result: dict[str, Any],
    patient_submission: str | None = None,
    model: str = DEFAULT_API_MODEL,
    timeout: int = 300,
    client: Any = None,
    max_tokens: int = 4000,
    sender: str = "provider",
) -> dict[str, Any]:
    """Draft one appeal letter in the requested voice.

    `sender` is "provider" (physician's office to the payer) or "patient" (a
    first-person member appeal). Returns letter Markdown plus usage/cost meta.
    `client` may be injected for testing; otherwise an Anthropic client is
    created from ANTHROPIC_API_KEY.
    """
    system_prompt = SENDER_SYSTEM_PROMPTS.get(sender)
    if system_prompt is None:
        return {"error": f"unknown sender voice {sender!r}"}
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return {"error": "ANTHROPIC_API_KEY is not set; cannot draft a letter"}
        client = _client(timeout)

    result = _ground_citations(result)
    context = _letter_context(result, patient_submission)
    voice = (
        "as the physician's office" if sender == "provider" else "in the patient's own first-person voice"
    )
    user_prompt = (
        f"Draft the appeal letter {voice} from the following retrieved evidence. "
        "Map the plan's criteria to the records.\n\n"
        "QUOTING RULE, and it is absolute: the only text you may put in "
        "quotation marks or a block quote, or attribute to the plan, is text "
        "that appears verbatim from the document in POLICY CITATIONS below. "
        "Copy it character for character. If POLICY CITATIONS is empty or does "
        "not cover the denial reason, write the argument in your own words and "
        "say plainly that the plan has not been quoted -- a reviewer checks "
        "quoted criteria first, and one sentence that is not in the policy "
        "discredits the whole letter. Never reconstruct, paraphrase inside "
        "quotation marks, or invent a policy number, section heading or "
        "effective date.\n\n"
        "Open with a line that names the governing policy exactly as given in "
        "GOVERNING POLICY -- title, and URL if there is one -- so a reviewer can "
        "find it. Do not state a policy number, section, version or effective "
        "date that is not given to you below; if none is given, name the "
        "policy by its title only.\n\n"
        "Use square-bracket placeholders only for details that neither the "
        "denial notice nor the records below contain.\n\n" + context
    )
    usage = {"input_tokens": 0, "output_tokens": 0}
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"letter generation failed: {exc}"}
    u = getattr(response, "usage", None)
    if u is not None:
        usage["input_tokens"] = getattr(u, "input_tokens", 0) or 0
        usage["output_tokens"] = getattr(u, "output_tokens", 0) or 0
    letter = "".join(
        b.text for b in response.content if getattr(b, "type", None) == "text"
    ).strip()
    if not letter:
        return {"error": "letter generation returned no text"}
    return {
        "letter_markdown": letter,
        "model": model,
        "sender": sender,
        "usage": usage,
        "estimated_cost_usd": _estimate_cost(usage),
    }
