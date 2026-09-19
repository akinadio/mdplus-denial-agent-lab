#!/usr/bin/env python3
"""Is a quotation the RIGHT sentence for this patient, not just a real one?

quote_check answers "do these words appear in the policy". That is a
plagiarism check. It was passing letters that quoted, verbatim and accurately:

  - "Coverage Rationale Surgery of the hip ... is proven and medically
    necessary in certain circumstances."   (a heading; states no rule)
  - "Arthroscopy, Diagnostic, +/- Synovial Biopsy, Hip Arthroscopy, Surgical,
    Hip ..."                                (a row of the CPT coding table)
  - "Surgery may be an option for individuals whose pain cannot be controlled
    by more conservative methods (National Institute of Arthritis ...)"
                                            (the policy's background reading)
  - "Medical records documentation may be required ... but does not guarantee
    coverage"                               (administrative boilerplate)
  - "Surgical treatment for Femoroacetabular Impingement Syndrome is unproven
    and not medically necessary in the presence of advanced osteoarthritis
    (Tonnis Grade ...)"                     (the EXCLUSION -- this one hands
                                             the insurer its own denial)

An appeal is won by quoting the requirement the denial turned on and showing
the chart meets it. So a quotation counts only when it (1) states a rule,
(2) bears on the reason this claim was denied, and (3) is not the exclusion.
Quoting nothing is a failure too -- a letter with no criteria is a letter
arguing from nothing.

Everything here is string matching. No model is asked for an opinion, so the
number is reproducible and costs nothing.
"""
from __future__ import annotations

import re

# A sentence that tells you what has to be true. These are the words a
# coverage rule is written with.
RULE_CUE = re.compile(
    r"\b(must|shall|require[sd]?|is required|at least|minimum of|no less than|"
    r"documented|documentation of|failed|failure of|trial of|weeks of|months of|"
    r"indicated when|criteria (?:are|is) met|when all of|if the (?:patient|member)|"
    r"unresponsive to|refractory to|demonstrat\w+|confirmed by|"
    # The lead-in that opens a criteria list is itself a rule: everything the
    # patient has to satisfy hangs off it. Distinguished from the heading
    # "...is proven and medically necessary IN CERTAIN CIRCUMSTANCES", which
    # promises criteria and gives none -- HEADING catches that first.
    r"(?:is|are) considered medically necessary|medically necessary (?:when|for|if)|"
    r"of the following|is covered when|is indicated (?:when|for))\b", re.I)

# ...and the shapes that look like criteria but are not.
HEADING = re.compile(
    r"^\W*(coverage rationale|applicable codes|definitions|clinical evidence|"
    r"description of services?|policy|purpose|scope|overview|background|"
    r"references|introduction)\b|in certain circumstances\W*$", re.I)
ADMINISTRATIVE = re.compile(
    r"may be required|does not guarantee|subject to the (?:terms|member|"
    r"provisions)|benefit (?:document|plan) |refer to the member|"
    r"this policy does not|not a guarantee|consult the|for informational", re.I)
BACKGROUND = re.compile(
    r"\bet al\b|\(\d{4}\)|systematic review|meta-analys|\bcochrane\b|"
    r"National Institute|randomized (?:controlled )?trial|\bstudies (?:have|were|"
    r"included|varied)\b|the authors\b|literature", re.I)
# The sentence that argues the insurer's side.
EXCLUSION = re.compile(
    r"\b(?:is|are)\s+(?:considered\s+)?(?:unproven|investigational|experimental|"
    r"not medically necessary|not covered|excluded)\b|"
    r"\bdoes not meet\b|\bis contraindicated\b", re.I)

# What each denial reason is argued with. A quotation is on point when it
# states a rule AND speaks to the reason this claim was actually denied --
# quoting the BMI rule at someone denied for imaging findings is not an appeal.
REASON_TERMS: dict[str, list[str]] = {
    "conservative_care": [
        "conservative", "nonsurgical", "non-surgical", "non-operative",
        "nonoperative", "physical therapy", "nsaid", "anti-inflammatory",
        "acetaminophen", "injection", "corticosteroid", "activity modification",
        "weight loss", "bracing", "trial of", "weeks", "months", "failed",
        "unresponsive", "refractory", "home exercise",
    ],
    "imaging": [
        "radiograph", "x-ray", "xray", "imaging", "mri", "magnetic resonance",
        "ct ", "computed tomography", "arthrogram", "kellgren", "lawrence",
        "tonnis", "tönnis", "joint space", "weight-bearing", "weight bearing",
        "grade", "osteophyte", "subchondral", "narrowing",
    ],
    "not_medically_necessary": [
        "medically necessary", "medical necessity", "indicated when",
        "criteria", "considered medically", "coverage", "functional",
        "pain", "symptom", "diagnosis", "failed",
    ],
    "incomplete_documentation": [
        "documented", "documentation", "medical record", "records must",
        "submitted", "chart", "notes", "history", "physical examination",
        "must include",
    ],
}


def classify(quote: str) -> str:
    """What kind of sentence this is. One label, most damning first."""
    q = (quote or "").strip().strip('"')
    if not q:
        return "empty"
    if EXCLUSION.search(q) and not RULE_CUE.search(q):
        return "exclusion"
    if HEADING.search(q):
        return "heading"
    if ADMINISTRATIVE.search(q):
        return "administrative"
    if BACKGROUND.search(q):
        return "background"
    if _looks_like_code_table(q):
        return "code_table"
    if EXCLUSION.search(q):
        # States a rule AND an exclusion: still the insurer's argument.
        return "exclusion"
    if RULE_CUE.search(q):
        return "rule"
    return "other"


def _looks_like_code_table(q: str) -> bool:
    """A run of procedure names or codes, not a sentence.

    "Arthroscopy, Diagnostic, +/- Synovial Biopsy, Hip Arthroscopy, Surgical,
    Hip ..." -- many commas, few words between them, no verb that binds.
    """
    commas = q.count(",")
    if commas < 3:
        return False
    if RULE_CUE.search(q):
        return False
    words = len(q.split())
    if words / (commas + 1) < 6:
        return True
    return bool(re.search(r"(\b\d{5}\b[,;\s]+){3,}", q))


def on_point(quote: str, denial_reason: str) -> bool:
    """A rule that speaks to the reason THIS claim was denied."""
    if classify(quote) != "rule":
        return False
    terms = REASON_TERMS.get(denial_reason or "", [])
    if not terms:
        return True   # unknown reason: a rule is the best we can ask for
    low = (quote or "").lower()
    return any(t in low for t in terms)


def assess(quotes: list[str], denial_reason: str) -> dict:
    """Score a letter's quotations.

    `grounded` is the endpoint: at least one quotation that is a rule, bears on
    the denial reason, and is not the exclusion. A letter with no quotations is
    not grounded -- quoting nothing is a failure, not a neutral result.
    """
    kinds = [classify(q) for q in quotes]
    points = [on_point(q, denial_reason) for q in quotes]
    return {
        "n_quotes": len(quotes),
        "n_on_point": sum(points),
        "n_against_patient": sum(1 for k in kinds if k == "exclusion"),
        "kinds": {k: kinds.count(k) for k in sorted(set(kinds))},
        "grounded": any(points),
        "on_point_quotes": [q for q, p in zip(quotes, points) if p][:5],
    }
