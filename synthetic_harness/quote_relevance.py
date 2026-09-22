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
    # Policies write durations as ">= three weeks" or "6 months of", and PDF
    # extraction breaks words apart ("thre e weeks"), so match a number plus a
    # unit rather than a fixed phrase. Missing this scored a real
    # conservative-care criterion as "other".
    r"(?:\d+|one|two|three|four|five|six|eight|twelve)\s*(?:week|month|day)s?\b|"
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
    r"National Institute|randomi[sz]ed (?:controlled )?trial|\bstudies (?:have|were|"
    r"included|varied|exhibited|showed|reported|demonstrated)\b|\ball studies\b|"
    r"the authors\b|literature|"
    # A policy's clinical-evidence section reads like a paper, because it is
    # one. On 2026-09-20 find_criteria was returning "Of them, 113 participants
    # (51.6%) in the arthroplasty group...", "At 12 months of follow-up the
    # arthroscopy group had a greater mean improvement in iHOT-33 (MD = 8.42,
    # p = ...)" and "All studies exhibited a high risk of bias" AS COVERAGE
    # CRITERIA, because they contain duration and requirement words. A coverage
    # rule states what a patient must show; it does not report a p-value, a
    # between-group difference or a risk-of-bias assessment.
    r"\bp\s*[=<>]\s*0?\.\d|\b(?:MD|SMD|WMD|OR|RR|HR)\s*=\s*[-\d]|"
    r"\bparticipants?\b|\bsubjects\b|\bcohort\b|\brisk of bias\b|"
    r"\bof follow-?up\b|\bmean (?:improvement|difference|change|score)\b|"
    r"\b(?:intervention|control|treatment|comparison) group\b|"
    r"\bconfidence interval\b|\b95% CI\b|\(range,|"
    # A coverage rule is a standalone statement. Evidence prose continues a
    # paragraph, so it opens with a connective: "however, a considerable number
    # of the allografts failed, requiring repeat allografting (range, 11%-48%)".
    r"^\W*(?:however|moreover|furthermore|conversely|in contrast|by contrast|"
    r"of them|of these|overall|notably|similarly)\b", re.I)
# The sentence that argues the insurer's side.
EXCLUSION = re.compile(
    r"\b(?:is|are)\s+(?:considered\s+)?(?:unproven|investigational|experimental|"
    r"not medically necessary|not covered|excluded)\b|"
    r"\bdoes not meet\b|\bis contraindicated\b", re.I)

# What each denial reason is argued with. A quotation is on point when it
# states a rule AND speaks to the reason this claim was actually denied --
# quoting the BMI rule at someone denied for imaging findings is not an appeal.
# Two of the four denial reasons name a SPECIFIC deficiency -- no adequate
# conservative trial, imaging that does not support necessity -- so the appeal
# has to answer that specific point, and quoting some other requirement is not
# an answer. The other two ("does not meet the plan's criteria for medical
# necessity", "documentation was incomplete") name nothing in particular; the
# answer to those is to quote the governing criteria and show the chart meets
# them, so any clinical rule from the right section is on point.
#
# Reading the letters is what settled this. Harvard Pilgrim / CPT 29881 was
# denied for incomplete documentation and our letter quoted "Failure of at
# least 6 months of non-operative treatment, including quadriceps
# strengthening..." -- exactly the right move, scored as off point because the
# sentence contains no documentation vocabulary.
SPECIFIC_DEFICIENCY = {"conservative_care", "imaging"}

# --------------------------------------------------------------------------
# WHICH SURGERY A SENTENCE IS ABOUT
# --------------------------------------------------------------------------
# The big vendor guidelines -- Carelon Joint Surgery, Evolent Musculoskeletal
# Surgery, eviCore -- are one document covering a dozen operations. A sentence
# can be a real rule, verbatim, on the right topic, and still be the rule for a
# DIFFERENT operation. On 2026-09-21 the smoke test caught OrthoAppeals handing
# a shoulder labral repair (29806) the criteria for shoulder REPLACEMENT out of
# Carelon, and another the cervical-FUSION six-week rule out of Evolent, and
# the grounded endpoint counted both as grounded. A reviewer reads that letter
# and sees the patient arguing under the wrong surgery's rules.
#
# Terms are ones a policy uses to name or scope that operation's criteria. A
# sentence naming a family that is neither the case's own nor a close
# neighbour (a shoulder instability section will mention the rotator cuff) is
# about another operation.
PROCEDURE_FAMILY_TERMS: dict[str, list[str]] = {
    "hip_arthroplasty": ["hip arthroplasty", "hip replacement", "hip resurfacing"],
    "knee_arthroplasty": ["knee arthroplasty", "knee replacement", "tricompartmental"],
    "uka": ["unicompartmental", "unicondylar", "partial knee"],
    "shoulder_arthroplasty": ["shoulder arthroplasty", "shoulder replacement",
                              "reverse shoulder", "glenoid prosthesis",
                              "glenoid sclerosis", "flattened glenoid"],
    "ankle_arthroplasty": ["ankle arthroplasty", "ankle replacement", "tibiotalar"],
    "meniscus": ["meniscectomy", "meniscal", "meniscus"],
    "acl": ["anterior cruciate", "acl reconstruction"],
    "hip_arthroscopy": ["femoroacetabular", "hip arthroscopy", "arthroscopic hip",
                        "tonnis", "tönnis", "alpha angle"],
    "rotator_cuff": ["rotator cuff"],
    "shoulder_instability": ["capsulorrhaphy", "bankart", "shoulder dislocation",
                             "glenohumeral instability", "recurrent subluxation",
                             "slap lesion", "labral tear of the shoulder"],
    # Not "myelopathy": cord compression is a criterion in lumbar and thoracic
    # sections too, and Aetna's lumbar laminectomy rule lists it -- it was
    # dropping a real lumbar criterion as "cervical".
    "cervical": ["cervical", "acdf"],
    "lumbar_fusion": ["lumbar fusion", "lumbar arthrodesis", "lumbar spinal fusion",
                      "spondylolisthesis", "pseudarthrosis"],
    "lumbar_decompression": ["laminectomy", "laminotomy", "discectomy",
                             "lumbar decompression", "foraminotomy"],
    "bunion": ["hallux", "bunion", "metatarsophalangeal", "intermetatarsal"],
    "patellar": ["patellar instability", "patellar dislocation", "patellofemoral",
                 "medial patellofemoral ligament"],
}
CPT_FAMILY: dict[str, str] = {
    "27130": "hip_arthroplasty", "27447": "knee_arthroplasty", "27446": "uka",
    "29880": "meniscus", "29881": "meniscus", "29888": "acl", "29914": "hip_arthroscopy",
    "23472": "shoulder_arthroplasty", "29827": "rotator_cuff",
    "29806": "shoulder_instability", "22551": "cervical", "22612": "lumbar_fusion",
    "63030": "lumbar_decompression", "27702": "ankle_arthroplasty", "28296": "bunion",
}
# Same joint, overlapping language: mentioning the neighbour is normal.
_NEIGHBOURS: dict[str, set[str]] = {
    # Partial and total knee replacement both require an intact ACL.
    "knee_arthroplasty": {"uka", "meniscus", "patellar", "acl"},
    "uka": {"knee_arthroplasty", "meniscus", "patellar", "acl"},
    # Shoulder replacement requires a functioning rotator cuff.
    "shoulder_arthroplasty": {"rotator_cuff"},
    "meniscus": {"acl", "knee_arthroplasty", "uka"},
    "acl": {"meniscus", "patellar"},
    "lumbar_fusion": {"lumbar_decompression"},
    "lumbar_decompression": {"lumbar_fusion"},
    "shoulder_instability": {"rotator_cuff"},
    "rotator_cuff": {"shoulder_instability", "shoulder_arthroplasty"},
    "hip_arthroplasty": {"hip_arthroscopy"},
    "hip_arthroscopy": {"hip_arthroplasty"},
}


# Body regions, as whole words. A spine policy covers cervical, thoracic and
# lumbar under the same procedure names -- Aetna's "Cervical laminectomy ..."
# names laminectomy, the lumbar case's own operation, and is still the wrong
# rule for a lumbar decompression.
_REGIONS: dict[str, re.Pattern] = {k: re.compile(v, re.I) for k, v in {
    # Not "labral": the hip has a labrum too (Carelon's hip arthroscopy
    # section lists "labral reconstruction" and was being dropped as shoulder).
    "shoulder": r"\b(shoulder|glenohumeral|glenoid|humeral|acromi\w*|rotator)\b",
    "hip": r"\b(hips?|acetabul\w*|femoroacetabular|femoral head)\b",
    "knee": r"\b(knees?|patell\w*|menisc\w*|tibiofemoral|cruciate)\b",
    "ankle": r"\b(ankles?|tibiotalar|talar)\b",
    "foot": r"\b(hallux|bunion\w*|metatars\w*|foot|feet)\b",
    "cervical": r"\b(cervical|acdf)\b",
    # The thoracic SPINE, not "thoracic outlet syndrome", which shoulder
    # criteria list as something to rule out.
    "thoracic": r"\bthoracic (?:spine|spinal|disc|level|laminectomy|fusion|vertebra\w*|decompression)\b",
    "lumbar": r"\b(lumbar|lumbosacral|sciatica)\b",
}.items()}
SPINE_REGIONS = {"cervical", "thoracic", "lumbar"}
_NEW_RULE = re.compile(r"(?:is|are) (?:considered )?(?:medically necessary|indicated)", re.I)
_RULED_OUT = re.compile(r"\b(excluded|ruled out|rule out|other (?:potential )?(?:causes|sources|"
                        r"patholog\w*)|differential)\b", re.I)
# Regions that share criteria language: ankle criteria talk about footwear.
_REGION_NEIGHBOURS = {"ankle": {"foot"}, "foot": {"ankle"}}
CPT_REGION: dict[str, str] = {
    "27130": "hip", "29914": "hip", "27446": "knee", "27447": "knee", "29880": "knee",
    "29881": "knee", "29888": "knee", "23472": "shoulder", "29827": "shoulder",
    "29806": "shoulder", "27702": "ankle", "28296": "foot", "22551": "cervical",
    "22612": "lumbar", "63030": "lumbar",
}


def regions_named(text: str) -> set[str]:
    return {k for k, rx in _REGIONS.items() if rx.search(text or "")}


def families_named(text: str) -> set[str]:
    low = (text or "").lower()
    return {f for f, ts in PROCEDURE_FAMILY_TERMS.items() if any(t in low for t in ts)}


def other_procedure(quote: str, cpt: str) -> bool:
    """True when the sentence is the rule for some OTHER operation.

    Only a positive naming counts: a sentence that names no operation at all
    ("Failure of at least 6 weeks of conservative care") is not flagged here --
    whether it came from the right section is the section locator's job.
    """
    own = CPT_FAMILY.get(cpt or "")
    if not own:
        return False
    # Names another part of the body and not this one.
    regions = regions_named(quote)
    own_region = CPT_REGION.get(cpt or "")
    if own_region in SPINE_REGIONS:
        # Spine symptoms are described where they are FELT -- "radicular pain
        # to the shoulder girdle", "femoral stretch test", "pain below the
        # knee" -- so for a spine operation only another spinal level counts.
        regions &= SPINE_REGIONS
    regions -= _REGION_NEIGHBOURS.get(own_region, set())
    if _RULED_OUT.search(quote or "") and not _NEW_RULE.search(quote or ""):
        # "Other conditions have been excluded: fracture, ... cervical
        # radiculopathy" is a shoulder criterion that names the neck only as
        # something to rule out -- unless it is itself another operation's
        # rule ("... is considered medically necessary when ...").
        return False
    if regions and own_region and own_region not in regions:
        return True
    named = families_named(quote)
    if not named or own in named:
        return False
    return bool(named - _NEIGHBOURS.get(own, set()))


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
        # How policies actually word the imaging finding, which is usually as
        # the diagnosis the imaging shows rather than as the film itself.
        "osteoarthritis", "degenerative", "arthritic", "bone-on-bone",
        "bone on bone", "unicompartmental", "avascular necrosis", "chondral",
        "meniscal tear", "rotator cuff tear", "stenosis", "herniat",
        "spondylolisthesis", "instability", "malalignment", "deformity",
        "findings", "evidence of",
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


# The section map's topic labels, by denial reason. A criterion the reviewed
# map filed under "imaging" answers an imaging denial whatever words it uses.
_TOPIC_ANSWERS = {
    "conservative_care": {"conservative_care"},
    "imaging": {"imaging"},
    "incomplete_documentation": {"documentation"},
}


def _norm_key(q: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (q or "").lower()).strip()[:80]


def known_criteria(known: dict | None, quote: str) -> str | None:
    """The reviewed topic of this quote, when it is (or contains, or is
    contained in) a criterion from the section map for this case."""
    if not known:
        return None
    k = _norm_key(quote)
    if not k or len(k) < 25:
        return None
    if k in known:
        return known[k]
    for kk, topic in known.items():
        if k in kk or kk in k:
            return topic
    return None


def on_point(quote: str, denial_reason: str, cpt: str = "", known: dict | None = None) -> bool:
    """A rule that answers the reason THIS claim was denied.

    A denial that names a specific deficiency has to be answered on that point.
    A denial that names nothing in particular is answered by the criteria
    themselves. See SPECIFIC_DEFICIENCY. A rule for a different operation
    answers nothing, however well it matches the topic.

    `known` maps normalised criteria from the reviewed section map (see
    build_section_criteria.py) to their topic. A quote that IS one of those
    criteria is a rule by definition -- "Radiographic evidence of moderate/
    severe osteoarthritis (Kellgren-Lawrence Grade 3 or 4)" has no cue word and
    read as "other" until 2026-09-22 -- and its reviewed topic decides whether
    it answers the denial.
    """
    topic = known_criteria(known, quote)
    if topic is not None:
        if cpt and other_procedure(quote, cpt):
            return False
        if denial_reason not in SPECIFIC_DEFICIENCY:
            return True
        return topic in _TOPIC_ANSWERS.get(denial_reason, set()) or _reason_terms_hit(quote, denial_reason)
    if classify(quote) != "rule":
        return False
    if cpt and other_procedure(quote, cpt):
        return False
    if denial_reason not in SPECIFIC_DEFICIENCY:
        return True
    return _reason_terms_hit(quote, denial_reason)


def _reason_terms_hit(quote: str, denial_reason: str) -> bool:
    terms = REASON_TERMS.get(denial_reason or "", [])
    if not terms:
        return True
    low = (quote or "").lower()
    return any(t in low for t in terms)


def assess(quotes: list[str], denial_reason: str, cpt: str = "", known: dict | None = None) -> dict:
    """Score a letter's quotations.

    `grounded` is the endpoint: at least one quotation that is a rule, bears on
    the denial reason, and is not the exclusion. A letter with no quotations is
    not grounded -- quoting nothing is a failure, not a neutral result.
    """
    kinds = ["rule" if known_criteria(known, q) is not None else classify(q) for q in quotes]
    points = [on_point(q, denial_reason, cpt, known) for q in quotes]
    return {
        "n_other_procedure": sum(1 for q in quotes if cpt and other_procedure(q, cpt)),
        "n_quotes": len(quotes),
        "n_on_point": sum(points),
        "n_against_patient": sum(1 for k in kinds if k == "exclusion"),
        "kinds": {k: kinds.count(k) for k in sorted(set(kinds))},
        "grounded": any(points),
        "on_point_quotes": [q for q, p in zip(quotes, points) if p][:5],
    }


# How a denial notice words each reason. Real notices use this language almost
# verbatim, because the plans copy one another.
_NOTICE_PATTERNS = (
    ("conservative_care", re.compile(
        r"conservative (?:treatment|care|management|therapy)|non-?surgical "
        r"(?:treatment|management)|trial of conservative", re.I)),
    ("imaging", re.compile(
        r"imaging (?:findings|studies|results)|radiographic findings|"
        r"films? (?:do not|does not)|x-?ray findings", re.I)),
    ("incomplete_documentation", re.compile(
        r"documentation (?:submitted )?was incomplete|incomplete documentation|"
        r"does not allow a determination|insufficient documentation", re.I)),
    ("not_medically_necessary", re.compile(
        r"criteria for medical necessity|not medically necessary|"
        r"does not meet the plan'?s criteria", re.I)),
)


def reason_from_notice(text: str) -> str:
    """Which denial reason this notice states, so the letter can answer it.

    Checked most specific first: a notice that says both "conservative
    treatment" and "medical necessity" is a conservative-care denial.
    """
    for key, pat in _NOTICE_PATTERNS:
        if pat.search(text or ""):
            return key
    return ""
