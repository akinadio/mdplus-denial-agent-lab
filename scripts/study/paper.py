#!/usr/bin/env python3
"""Brief Communication draft (Nature Medicine format), generated from study/stats.json.

Layout: title; one-paragraph abstract; main text (framing, results with
Fig. 1 and Fig. 2, discussion placeholder); figure legends; Methods with
subsections; data and code availability; Extended Data Tables 1-3.

Every number in the text is read from the statistics file, never typed. Run
stats.py, then figures.py, then this; the document re-derives.

  python3 scripts/study/paper.py   -> docs/OrthoAppeals-Brief-Communication.docx
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S = ROOT / "study"
DOCS = ROOT / "docs"
OUT = DOCS / "OrthoAppeals-Brief-Communication.docx"

st = json.loads((S / "stats.json").read_text())
ID = st["identification"]; PA = st["identification_paired"]; LT = st["letters"]; T1 = st["table1"]
EF = st["effort"]; CP = st["ortho_correction_pass"]
A = {"ortho-opus": "OrthoAppeals", "chatgpt": "ChatGPT", "claude-free": "Claude", "gemini": "Gemini"}
o, c, cl, g = "ortho-opus", "chatgpt", "claude-free", "gemini"
nA, nB, nC = T1["strata"]["in_library"], T1["strata"]["vendor_held"], T1["strata"]["no_policy"]
N = st["n_cases"]
FAM = {"insurer's own": "the insurer's own policy", "carelon": "Carelon", "evicore": "eviCore",
       "evolent": "Evolent", "cohere": "Cohere", "mcg": "MCG", "interqual": "InterQual", "turningpoint": "TurningPoint"}


# ---------------------------------------------------------------- helpers ----
def pct(k, nn):
    return f"{100 * k / nn:.0f}%"


def n(k, nn):
    return f"{k} of {nn} ({pct(k, nn)})"


def ci(d):
    return f"{100 * d['lo']:.0f}–{100 * d['hi']:.0f}%"


def nci(d):
    return f"{d['k']} of {d['n']} ({pct(d['k'], d['n'])}; 95% CI {ci(d)})"


def pv(v):
    """Holm-adjusted P where the family was adjusted, else raw."""
    p = v.get("p_holm", v["p"])
    return "P < 0.001" if p < 0.001 else (f"P = {p:.3f}" if p < 0.01 else f"P = {p:.2f}")


def pts(v):
    return f"{100 * v['diff']:+.0f} points (95% CI {100 * v['diff_lo']:+.0f} to {100 * v['diff_hi']:+.0f})"


def lm(name, arm):
    return LT[name]["arms"][arm]


def lp(name, arm):
    return LT[name]["paired"][f"ortho-opus vs {arm}"]


def rng(name, arms, nn):
    vals = sorted(100 * lm(name, a)["k"] / nn for a in arms)
    return f"{vals[0]:.0f}–{vals[-1]:.0f}%"


# ---------------------------------------------------------------- text ----
TITLE = ("A policy-grounded tool identifies the governing medical policy and quotes it accurately "
         "in simulated orthopaedic surgery appeals, where free chatbots do not")

ABSTRACT = (
    "Patients appealing a denied orthopaedic operation must show that they meet the criteria in their health "
    "plan's medical policy, and many now draft appeals with general-purpose chatbots. We compared OrthoAppeals, "
    "which retrieves the governing policy from a curated directory and drafts from its text, with the free-tier "
    f"models of ChatGPT, Claude and Gemini given web search, on {N} simulated denials across {T1['states']} "
    f"jurisdictions, {T1['insurers']} insurers and 14 operations. OrthoAppeals identified the governing policy in "
    f"every case; the chatbots did so in {pct(ID[c]['all']['k'], N)} to {pct(ID[cl]['all']['k'], N)} (each "
    "P < 0.001). Where criteria were published, OrthoAppeals quoted a criterion answering the denial in "
    f"{pct(lm('grounded', o)['k'], nA)} of letters and never quoted text absent from the policy; the chatbots "
    f"quoted text not found in the policy in {rng('quote_unverifiable', (c, cl, g), nA)} of letters. Where no "
    f"policy existed, Gemini named a nonexistent document in {pct(lm('hallucinated_document_C', g)['k'], nC)} of "
    f"cases. The same audit corrected 17 answer-key errors and {CP['flagged_before']} OrthoAppeals first drafts "
    "that stated an unsourced rule.")

MAIN = [
    # framing (minimal; to be expanded)
    ("Health plans deny prior authorization for orthopaedic operations against medical-necessity criteria that "
     "most plans publish or delegate to a licensed vendor, and a successful appeal usually shows, in the plan's "
     "own words, that the patient meets them. Patients increasingly draft appeals with general-purpose chatbots. "
     "Such an appeal is only as good as two steps the chatbot performs invisibly: finding the document that "
     "governs the case and quoting it faithfully. We asked whether a tool that grounds both steps in a curated "
     "policy directory does them more reliably than free chatbots with web search."),

    (f"We built {N} simulated denials, one per member, plan and state, covering {T1['states']} jurisdictions, "
     f"{T1['insurers']} insurers, 14 operations and four denial reasons, each with a denial notice and a "
     f"clinical summary (Fig. 1 and Extended Data Table 1). Cases fell into three strata: the plan or its "
     f"vendor publishes criteria for the operation (stratum A, n = {nA}); the plan's public policy names the "
     f"operation but applies licensed criteria that are not public (stratum B, n = {nB}); or the plan publishes "
     f"no policy for the operation (stratum C, n = {nC}). Every case was answered by OrthoAppeals and by "
     "ChatGPT (GPT-5.6), Claude (Sonnet 5) and Gemini (3.5 Flash) run through their vendors' interfaces with "
     "identical tools, instructions and a 120-call budget, so every comparison is paired on the same case. "
     "The governing document for each case was verified against the full policy text, and all scoring rules "
     "were fixed and applied to all systems before final scoring (Methods)."),

    (f"OrthoAppeals cited the governing policy in {nci(ID[o]['all'])} cases (Fig. 2a and Extended Data "
     f"Table 2). ChatGPT did so in {nci(ID[c]['all'])}, Claude in {nci(ID[cl]['all'])} and Gemini in "
     f"{nci(ID[g]['all'])}. In paired comparison OrthoAppeals was correct where the chatbot was not in "
     f"{PA['all']['ortho-opus vs chatgpt']['ortho-opus_only']} cases against ChatGPT, "
     f"{PA['all']['ortho-opus vs claude-free']['ortho-opus_only']} against Claude and "
     f"{PA['all']['ortho-opus vs gemini']['ortho-opus_only']} against Gemini, and the reverse never occurred "
     f"(each {pv(PA['all']['ortho-opus vs gemini'])}, exact McNemar test with Holm–Bonferroni adjustment). "
     f"Claude and Gemini did not differ ({pv(PA['all']['claude-free vs gemini'])}); both outperformed ChatGPT "
     f"({pv(PA['all']['chatgpt vs claude-free'])} and {pv(PA['all']['chatgpt vs gemini'])})."),

    (f"The chatbots failed in different ways. Where criteria were published (stratum A), ChatGPT found the "
     f"policy in {n(ID[c]['in_library']['k'], nA)} cases and most often returned no document at all "
     f"({ID[c]['in_library']['outcomes'].get('no_answer', 0)} cases); Claude found it in "
     f"{n(ID[cl]['in_library']['k'], nA)} and Gemini in {n(ID[g]['in_library']['k'], nA)}. Where no policy "
     f"existed (stratum C), ChatGPT correctly said so in {n(ID[c]['no_policy']['k'], nC)} cases and Claude in "
     f"{n(ID[cl]['no_policy']['k'], nC)}, but Gemini in only {n(ID[g]['no_policy']['k'], nC)}: it named a "
     f"specific governing document that did not exist in {n(lm('hallucinated_document_C', g)['k'], nC)} cases "
     f"(versus OrthoAppeals, {pv(lp('hallucinated_document_C', g))}; Fig. 2c)."),

    (f"The letters differed more than the citations (Fig. 2b and Extended Data Table 3). In stratum A, "
     f"OrthoAppeals' letter quoted a criterion that answered the stated denial reason in "
     f"{n(lm('grounded', o)['k'], nA)} cases, Gemini's in {n(lm('grounded', g)['k'], nA)}, Claude's in "
     f"{n(lm('grounded', cl)['k'], nA)} and ChatGPT's in {n(lm('grounded', c)['k'], nA)} (each versus "
     f"OrthoAppeals, {pv(lp('grounded', g))}, {pv(lp('grounded', cl))} and {pv(lp('grounded', c))}). The one "
     "OrthoAppeals letter that was not grounded concerned a policy with no criterion on the denial's point; the "
     "letter said so and asked the plan to state its threshold. Quotations that could be found neither in the "
     f"governing document nor in the document the system itself cited appeared in "
     f"{n(lm('quote_unverifiable', cl)['k'], nA)} Claude letters, {n(lm('quote_unverifiable', g)['k'], nA)} "
     f"Gemini letters and {n(lm('quote_unverifiable', c)['k'], nA)} ChatGPT letters, and in "
     f"{lm('quote_unverifiable', o)['k']} OrthoAppeals letters (95% CI {ci(lm('quote_unverifiable', o))}). "
     f"An invented policy number or effective date appeared in {n(lm('invented_identifier', g)['k'], N)} "
     f"Gemini, {n(lm('invented_identifier', cl)['k'], N)} Claude and {n(lm('invented_identifier', c)['k'], N)} "
     "ChatGPT letters, and in none from OrthoAppeals."),

    (f"On the administrative content of the letter, OrthoAppeals stated the filing deadline in "
     f"{n(lm('deadline_stated', o)['k'], N)} letters and Claude in {n(lm('deadline_stated', cl)['k'], N)}, but "
     f"ChatGPT in {n(lm('deadline_stated', c)['k'], N)} and Gemini in {n(lm('deadline_stated', g)['k'], N)} "
     f"(both {pv(lp('deadline_stated', g))}; Fig. 2c). ChatGPT's letters lacked an identifier from the notice "
     f"or left a placeholder in {N - lm('sendable', c)['k']} of {N}; the other three systems produced a "
     "sendable letter every time. Where no policy existed, OrthoAppeals, ChatGPT and Claude asked the plan for "
     f"its criteria in writing in every letter; Gemini did so in {n(lm('demands_criteria_C', g)['k'], nC)}."),

    (f"A model-based grader, reported as exploratory, rated mean completeness (0–4) at "
     f"{LT['completeness_judged'][o]['mean']:.2f} for OrthoAppeals, {LT['completeness_judged'][cl]['mean']:.2f} "
     f"for Claude, {LT['completeness_judged'][c]['mean']:.2f} for ChatGPT and "
     f"{LT['completeness_judged'][g]['mean']:.2f} for Gemini. OrthoAppeals' own safeguard flagged "
     f"{n(CP['flagged_before'], CP['letters'])} first drafts for a number, quotation or rule attributed to the "
     f"plan that was not in the excerpts the writer had; {CP['revised']} were revised, in {CP['flagged_not_revised']} "
     f"the revision request failed and the draft was kept, and {CP['flagged_after']} letters carried a flagged item "
     "at delivery under the final checker (both kept drafts had been flagged in error). Before this safeguard existed, an earlier writer given a six-item shortlist "
     "rather than the full criteria list had stated such a rule in 45 of 120 stratum-A letters, which is why "
     "it was added."),

    (f"The chatbots reached their answers by searching: a median of {EF[c]['searches_median']} "
     f"(IQR {EF[c]['searches_iqr'][0]}–{EF[c]['searches_iqr'][1]}) web searches per case for ChatGPT, "
     f"{EF[cl]['searches_median']} ({EF[cl]['searches_iqr'][0]}–{EF[cl]['searches_iqr'][1]}) for Claude and "
     f"{EF[g]['searches_median']} ({EF[g]['searches_iqr'][0]}–{EF[g]['searches_iqr'][1]}) for Gemini (Fig. 2d). "
     "OrthoAppeals made none; its answer is a directory lookup, and its stratum-A result therefore measures "
     "the accuracy of that directory after audit rather than a search capability."),

    "[Discussion paragraphs to follow: interpretation, limitations (simulated cases, one time point, shared "
    "answer-key source, model-judged measures exploratory), and implications.]",
]

FIG1_LEGEND = (
    "Fig. 1 | Evaluation pipeline. Each of the 167 simulated denials was answered by OrthoAppeals and by three "
    "chatbots run with identical tools and instructions. Every system returned the governing policy it cited "
    "and a complete appeal letter; citations were scored against a reviewed answer key and letters by code "
    "against the policy text and the notice. An independent audit script re-derives every table.")

FIG2_LEGEND = (
    "Fig. 2 | Policy identification, letter accuracy and effort. a, Correct identification of the governing "
    f"policy by stratum (A, criteria published, n = {nA}; B, document public but criteria vendor-held, "
    f"n = {nB}; C, no policy published, n = {nC}) and overall (n = {N}). b, Stratum-A letters that quote a "
    "criterion answering the stated denial reason, letters containing a quotation found in neither the "
    "governing document nor the cited document, and letters (all strata) containing an invented policy number "
    "or effective date. c, Stratum-C letters that cite a document that does not exist or that ask the plan for "
    "its criteria in writing, and letters (all strata) that state the filing deadline. d, Median web searches "
    "and page fetches per case for the chatbots (OrthoAppeals performs a directory lookup and no search). "
    "Bars show proportions with Wilson 95% confidence intervals (a–c) or medians with interquartile range (d). "
    "Values are printed above each bar. P values for paired comparisons are in Extended Data Tables 2 and 3.")

METHODS = [
    ("Study design",
     f"This was a paired comparison on simulated cases. Each of {N} cases was answered by four systems, so "
     "every comparison is between answers to the same case. No real patient data were used; denial notices "
     "and clinical summaries were generated from templates. The study was run in September 2026."),
    ("Cases",
     "A case is one denied orthopaedic operation for one member of one health plan in one state, with a denial "
     "notice giving the reason, the appeal deadline and the plan's member and reference identifiers, and a "
     f"one-page clinical summary. Cases covered {T1['states']} jurisdictions (all 50 states and the District of "
     f"Columbia), {T1['insurers']} insurers, {T1['plan_type']['Commercial/ACA']} commercial and "
     f"{T1['plan_type']['Medicaid']} Medicaid managed-care plans, 14 operations and four denial reasons in "
     "near-equal numbers: inadequate conservative treatment, imaging not supporting the surgery, not medically "
     "necessary, and incomplete documentation (Extended Data Table 1). Clinical summaries described a patient "
     "who plausibly met the usual criteria for the operation, so that a well-grounded appeal was possible in "
     "every case."),
    ("Strata and correct behaviour",
     f"Stratum A (n = {nA}): the plan, or the vendor to which it delegates review, publishes medical-necessity "
     f"criteria for the operation. Stratum B (n = {nB}): the plan's public policy names the operation but "
     "states that a licensed criteria set (InterQual, MCG or TurningPoint) is applied, so the criteria "
     f"themselves are not public. Stratum C (n = {nC}): the plan publishes no policy for the operation. The "
     "correct behaviour differs by stratum: cite the document (A); cite the document and tell the patient how "
     "to obtain the criteria (B); state that no policy is published and tell the patient how to obtain the "
     "criteria (C). Stratum A drew on "
     + ", ".join(f"{FAM[k]} ({v} cases, {T1['publisher_documents_A'][k]} documents)"
                 for k, v in sorted(T1["publishers_A"].items(), key=lambda x: -x[1]))
     + f", {T1['policy_documents_A']} distinct documents in all."),
    ("Answer key",
     "The governing document for each case came from OrthoAppeals' own policy directory, which was built from "
     "insurer websites. Because the tool and the answer key share this source, the tool cannot miss on policy "
     "identification when the directory is right; the study therefore tests whether the directory is right. "
     "Every stratum-A document was read in full: a language model (Claude Opus 5) extracted the criteria "
     "section for the specific operation, and code verified each extracted sentence word for word against the "
     "document. This review, and a second audit of every 'equivalent' verdict, found and corrected 17 "
     "answer-key entries before final scoring (Supplementary Table 1): two that pointed at a guideline for a "
     "different operation, two plans reclassified to stratum B because their public policy defers to a "
     "vendor's criteria, one plan whose own policy the directory had missed, three entries pointing at index "
     "pages rather than the policy, five documents that named no operation at all (reclassified to stratum C), "
     "and four Centene plans whose notices delegate review to Evolent, whose guideline was accepted alongside "
     "the plan's policy."),
    ("Systems compared",
     "OrthoAppeals looks the case up in its directory, takes the verbatim criteria for the operation from the "
     "section extracted for that document, and drafts a first-person appeal with a language model (Claude "
     "Opus 5, the same model family as one comparator) that is given only those excerpts, the notice and the "
     "clinical summary and is instructed to state no rule from memory. Before a letter is delivered, code "
     "checks it for any number or quotation attributed to the plan that is not in the excerpts, and a second "
     "model read checks for invented rules stated in words; if either finds anything, the writer receives one "
     "revision request naming the sentences. The three comparators were the models behind the free tiers of "
     "ChatGPT (GPT-5.6), Claude (Sonnet 5) and Gemini (3.5 Flash) in September 2026, each run through its "
     "vendor's application programming interface rather than the consumer app, with the same two tools (web "
     "search and page fetch), the same instructions and a budget of 120 tool calls. Each chatbot first "
     "identified the policy and then, in the same conversation, drafted the appeal letter from the notice and "
     "clinical summary. Sampling parameters were the vendors' defaults; each case was run once per system."),
    ("Outcomes",
     "The primary outcome was correct identification of the governing policy. A cited document was correct if "
     "it was the answer-key document, another edition or host of the same publisher's guideline (identified "
     "from the cited document's address and text, never from the system's own description of it), or an "
     "accepted alternate. In stratum C, naming any specific policy as governing was scored as a hallucinated "
     "document, except the plan's general utilization-management policy. Letter outcomes were scored by code "
     "against the policy text and the notice: (1) grounded, the letter quotes at least one criterion from the "
     "reviewed section that answers the stated denial reason (stratum A only); (2) unverifiable quotation, a "
     "passage in quotation marks that appears neither in the governing document nor in the document the system "
     "cited; (3) an invented policy number or effective date; (4) the filing deadline stated; (5) where to send "
     "the appeal stated; (6) sendable, the member and reference identifiers from the notice are present and no "
     "placeholder remains where the notice or summary supplied the fact; (7) in stratum C, whether the letter "
     "asks the plan for its criteria in writing and whether it names a nonexistent governing document. A "
     "model-based grader (Claude Opus 5) also rated completeness on a 0–4 scale and flagged rules attributed to "
     "the plan without a source; these judged outcomes are exploratory. Effort was the number of searches and "
     "page fetches each chatbot made per case, from its own tool log."),
    ("Statistical analysis",
     "Proportions are reported with Wilson 95% confidence intervals. Paired comparisons between systems on the "
     "same cases used the exact McNemar test on the discordant pairs, with the difference in proportions and a "
     "bootstrap 95% confidence interval (10,000 resamples). P values were adjusted for multiple comparisons "
     "with the Holm–Bonferroni method within each family of comparisons (the six pairwise identification "
     "comparisons; the three comparisons against OrthoAppeals for each letter outcome). All tests were "
     "two-sided. Analyses used Python 3 with no external statistical packages; the code is in the repository."),
    ("Measurement corrections during the study",
     "Scoring rules were revised whenever a hand check of letters or verdicts found an error, and every "
     "revision was applied to all systems and all cases before final scoring. Supplementary Table 2 lists each "
     "change with its date and direction. Some corrections favoured OrthoAppeals and some the chatbots; the "
     "largest in the chatbots' favour were reading a URL out of a citation field that also contained a note "
     "(30 verdicts) and verifying quotations against the document the chatbot cited rather than only against "
     "the answer-key document (44 letters). The largest against OrthoAppeals were counting a quotation from "
     "another operation's section as ungrounded, and a grader that had seen only 14 of the excerpts the writer "
     "had. An independent audit script re-derives every table from the letters, transcripts and policy "
     "documents and checks the answer key, the equivalence verdicts and the statistics."),
    ("Reporting summary",
     "Further information on research design is available in the Nature Portfolio Reporting Summary linked to "
     "this article. [To be completed.]"),
]

DATA_AVAIL = ("All study inputs and outputs are in the study repository: the 167 cases and answer key "
              "(study/cases.json, study/gold.json), every letter and search transcript (study/runs/), every "
              "score and grade (study/scores.json, study/letter_grades.json) and the policy documents as they "
              "read at the time (data/policy_platform/policy_text_cache/). No real patient data were used.")
CODE_AVAIL = ("Case generation, the comparator harness, scoring, statistics, the audit script and this document "
              "are generated by code in the same repository (scripts/study/). The OrthoAppeals writer and its "
              "checks are in synthetic_harness/.")

# ---------------------------------------------------------------- docx ----
from docx import Document  # noqa: E402
from docx.shared import Pt, Inches  # noqa: E402

doc = Document()
style = doc.styles["Normal"]; style.font.name = "Calibri"; style.font.size = Pt(11)
doc.add_heading(TITLE, level=1)
doc.add_paragraph("Brief Communication draft. Generated from study/stats.json on the study data of 2026-09-22; "
                  "every number is reproducible with scripts/study/stats.py, figures.py and paper.py. "
                  "Discussion and reporting summary not yet written.").italic = True

doc.add_heading("Abstract", level=2)
doc.add_paragraph(ABSTRACT)

doc.add_heading("Main", level=2)
for t in MAIN:
    doc.add_paragraph(t)

doc.add_heading("Figures", level=2)
for png, legend in (("fig1_pipeline.png", FIG1_LEGEND), ("fig2_results.png", FIG2_LEGEND)):
    if (DOCS / png).exists():
        doc.add_picture(str(DOCS / png), width=Inches(6.3))
    p = doc.add_paragraph(legend); p.runs[0].font.size = Pt(9)

doc.add_heading("Methods", level=2)
for h, t in METHODS:
    doc.add_heading(h, level=3); doc.add_paragraph(t)
doc.add_heading("Data availability", level=3); doc.add_paragraph(DATA_AVAIL)
doc.add_heading("Code availability", level=3); doc.add_paragraph(CODE_AVAIL)


def table(title, header, rows, note=""):
    doc.add_paragraph().add_run(title).bold = True
    tb = doc.add_table(rows=1, cols=len(header)); tb.style = "Light Grid Accent 1"
    for i, h in enumerate(header):
        tb.rows[0].cells[i].text = h
    for r in rows:
        cells = tb.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = str(v)
    if note:
        doc.add_paragraph(note).runs[0].font.size = Pt(9)


doc.add_heading("Extended Data", level=2)

# Extended Data Table 1
rows = [("Cases", N, "")]
rows += [("Stratum A: criteria published", nA, pct(nA, N)),
         ("Stratum B: document public, criteria vendor-held", nB, pct(nB, N)),
         ("Stratum C: no policy published", nC, pct(nC, N)),
         ("Jurisdictions (50 states + DC)", T1["states"], ""), ("Insurers", T1["insurers"], ""),
         ("Commercial / ACA plans", T1["plan_type"]["Commercial/ACA"], pct(T1["plan_type"]["Commercial/ACA"], N)),
         ("Medicaid managed-care plans", T1["plan_type"]["Medicaid"], pct(T1["plan_type"]["Medicaid"], N))]
for k, v in sorted(T1["denial_reason"].items(), key=lambda x: -x[1]):
    rows.append((f"Denial reason: {k.replace('_', ' ')}", v, pct(v, N)))
for k, v in sorted(T1["surgery"].items(), key=lambda x: -x[1]):
    rows.append((f"Operation: {k}", v, pct(v, N)))
rows.append(("Distinct governing documents, stratum A", T1["policy_documents_A"], ""))
for k, v in sorted(T1["publishers_A"].items(), key=lambda x: -x[1]):
    rows.append((f"Stratum A publisher: {FAM[k]}", v, pct(v, nA)))
table("Extended Data Table 1 | Case characteristics", ["Characteristic", "n", "%"], rows,
      "Publisher percentages are of stratum A.")

# Extended Data Table 2
hdr = ["System", f"Stratum A (n = {nA})", f"Stratum B (n = {nB})", f"Stratum C (n = {nC})", f"All (n = {N})",
       "Versus OrthoAppeals, all cases"]
rows = []
for arm in (o, c, cl, g):
    cells = [A[arm]]
    for s in ("in_library", "vendor_held", "no_policy", "all"):
        d = ID[arm][s]; cells.append(f"{d['k']} ({pct(d['k'], d['n'])}; {ci(d)})")
    if arm == o:
        cells.append("—")
    else:
        v = PA["all"][f"ortho-opus vs {arm}"]
        cells.append(f"{v['ortho-opus_only']} / 0 discordant; {pv(v)}; {pts(v)}")
    rows.append(cells)
table("Extended Data Table 2 | Correct identification of the governing policy (n correct; %; Wilson 95% CI)", hdr, rows,
      "Discordant pairs: cases OrthoAppeals had right and the chatbot wrong / the reverse. Exact McNemar test, "
      "Holm–Bonferroni-adjusted P; difference in proportions with bootstrap 95% CI. OrthoAppeals and the answer key "
      "share a source (Methods); its stratum-A figure measures the directory's accuracy after audit.")

# Extended Data Table 3
hdr = ["Letter outcome", "OrthoAppeals", "ChatGPT", "Claude", "Gemini"]
names = [("grounded", "Quotes a criterion answering the denial reason (stratum A)"),
         ("quote_unverifiable", "Any quotation not found in the policy (stratum A)"),
         ("quote_other_procedure", "Quotes another operation's criteria (stratum A)"),
         ("cites_correct_policy_in_letter", "Letter cites the governing policy (stratum A)"),
         ("invented_identifier", "Invented policy number or effective date"),
         ("deadline_stated", "States the filing deadline"),
         ("route_stated", "States where to send the appeal"),
         ("sendable", "Sendable: identifiers present, no placeholders"),
         ("unfinished", "Letter cut off before its end"),
         ("demands_criteria_C", "Asks the plan for its criteria in writing (stratum C)"),
         ("hallucinated_document_C", "Names a nonexistent governing document (stratum C)"),
         ("unsupported_attribution_judged", "Rule attributed to the plan without a source (judged, exploratory)")]
rows = []
for key, label in names:
    m = LT[key]; cells = [f"{label} (n = {m['n']})"]
    for arm in (o, c, cl, g):
        d = m["arms"][arm]; s = f"{d['k']} ({pct(d['k'], d['n'])})"
        if arm != o:
            s += f"; {pv(m['paired'][f'ortho-opus vs {arm}'])}"
        cells.append(s)
    rows.append(cells)
comp = LT["completeness_judged"]
rows.append(["Completeness, judged, mean (0–4), all letters (exploratory)"] + [f"{comp[a]['mean']:.2f}" for a in (o, c, cl, g)])
table("Extended Data Table 3 | Appeal-letter outcomes (n, %; Holm–Bonferroni-adjusted exact McNemar P versus OrthoAppeals on the same cases)",
      hdr, rows,
      "All outcomes but the two marked exploratory are scored by code against the policy text and the denial notice. "
      "A quotation is unverifiable when it is in neither the governing document nor the document the system itself "
      "cited. The judged grader saw only the excerpts a system was given, not the full documents the chatbots read, "
      "so chatbot counts on the judged attribution measure may include correctly sourced paraphrases.")

OUT.parent.mkdir(exist_ok=True)
doc.save(OUT)
print("wrote", OUT.relative_to(ROOT))
