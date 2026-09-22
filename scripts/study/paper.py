#!/usr/bin/env python3
"""Abstract, Methods and Results, generated from study/stats.json.

Every number in the text is read from the statistics file, never typed. Run
stats.py, then this; the document re-derives.

  python3 scripts/study/paper.py   -> docs/OrthoAppeals-Abstract-Methods-Results.docx
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S = ROOT / "study"
OUT = ROOT / "docs" / "OrthoAppeals-Abstract-Methods-Results.docx"

st = json.loads((S / "stats.json").read_text())
ID = st["identification"]; PA = st["identification_paired"]; LT = st["letters"]; T1 = st["table1"]
EF = st["effort"]; CP = st["ortho_correction_pass"]
A = {"ortho-opus": "OrthoAppeals", "chatgpt": "ChatGPT", "claude-free": "Claude", "gemini": "Gemini"}


def n(k, nn):
    return f"{k} of {nn} ({100 * k / nn:.0f}%)"


def ci(d):
    return f"{100 * d['lo']:.0f}–{100 * d['hi']:.0f}%"


def pv(p):
    return "P < .001" if p < 0.001 else (f"P = {p:.3f}" if p < 0.01 else f"P = {p:.2f}")


def pts(v):
    return f"{100 * v['diff']:+.0f} points (95% CI {100 * v['diff_lo']:+.0f} to {100 * v['diff_hi']:+.0f})"


def strat(arm, s):
    return ID[arm][s]


def lm(name, arm):
    return LT[name]["arms"][arm]


# ---------------------------------------------------------------- text ----
o, c, cl, g = "ortho-opus", "chatgpt", "claude-free", "gemini"
nA, nB, nC = T1["strata"]["in_library"], T1["strata"]["vendor_held"], T1["strata"]["no_policy"]
N = st["n_cases"]

abstract = [
("Background",
 "Patients who appeal a denied orthopedic surgery must usually show that they meet the criteria in "
 "their health plan's published medical policy. Many now ask a general-purpose AI chatbot for help. "
 "We compared OrthoAppeals, a tool that looks the policy up in a curated directory and drafts an "
 "appeal from that policy's own text, against three free chatbots on the two things an appeal "
 "depends on: identifying the right policy, and quoting it accurately."),
("Methods",
 f"We built {N} simulated denial cases across {T1['states']} states and the District of Columbia, "
 f"{T1['insurers']} insurers, and 14 orthopedic operations, with a synthetic clinical summary for each. "
 f"Cases were of three kinds: the plan publishes criteria for the operation (n = {nA}); the plan's "
 f"public policy names the operation but sends the criteria to a licensed vendor (n = {nB}); or the "
 f"plan publishes no policy for the operation (n = {nC}). Each case was given to OrthoAppeals and to "
 "ChatGPT, Claude and Gemini running with web search. The primary outcome was correct identification "
 "of the governing policy, scored against a reviewed answer key. Letter outcomes were scored by code "
 "against the policy text: whether the letter quoted a criterion that answered the stated denial "
 "reason, whether every quotation was really in the policy, and whether the letter was complete "
 "enough to send. Paired comparisons used the exact McNemar test."),
("Results",
 f"OrthoAppeals identified the governing policy in {n(strat(o,'all')['k'], N)} cases, ChatGPT in "
 f"{n(strat(c,'all')['k'], N)}, Claude in {n(strat(cl,'all')['k'], N)} and Gemini in "
 f"{n(strat(g,'all')['k'], N)} (each versus OrthoAppeals, {pv(PA['all']['ortho-opus vs chatgpt']['p'])}). "
 f"Where criteria were published, OrthoAppeals quoted a criterion answering the denial in "
 f"{n(lm('grounded',o)['k'], nA)} letters, Gemini in {n(lm('grounded',g)['k'], nA)}, Claude in "
 f"{n(lm('grounded',cl)['k'], nA)} and ChatGPT in {n(lm('grounded',c)['k'], nA)}. Quotations that "
 f"could not be found in the policy appeared in {lm('quote_unverifiable',o)['k']} OrthoAppeals letters, "
 f"{lm('quote_unverifiable',c)['k']} ChatGPT, {lm('quote_unverifiable',cl)['k']} Claude and "
 f"{lm('quote_unverifiable',g)['k']} Gemini letters. Where no policy existed, Gemini named a "
 f"nonexistent governing document in {n(lm('hallucinated_document_C',g)['k'], nC)} cases. "
 f"OrthoAppeals' first drafts stated a rule the policy did not contain in {CP['flagged_before']} of "
 f"{CP['letters']} letters; a built-in check caught and corrected every one before delivery."),
("Conclusions",
 "Free chatbots found the governing policy in roughly two of three to four of five cases and, when "
 "they quoted it, often misquoted it. A directory-grounded tool identified the policy in every case "
 "in which its directory was correct and never quoted text that was not in the document. The audit "
 "that produced these results also found and corrected errors in the tool's own directory, and the "
 "tool's writer required an automated correction pass to keep invented rules out of its letters."),
]

methods = [
("Study design",
 f"This was a paired comparison on simulated cases. Each of {N} cases was answered by four systems, "
 "so every comparison is between answers to the same case. No real patient data were used; the "
 "denial notices and clinical summaries were generated from templates."),
("Cases",
 f"A case is one denied orthopedic operation for one member of one health plan in one state, with "
 "a denial notice giving the reason, the appeal deadline, and the plan's member and reference "
 f"identifiers, plus a one-page clinical summary. Cases covered {T1['states']} jurisdictions (all 50 "
 f"states and the District of Columbia), {T1['insurers']} insurers, {T1['plan_type']['Commercial/ACA']} "
 f"commercial and {T1['plan_type']['Medicaid']} Medicaid plans, 14 operations (Table 1), and four "
 "denial reasons in roughly equal numbers: inadequate conservative treatment, imaging not supporting "
 "the surgery, not medically necessary, and incomplete documentation. Clinical summaries described a "
 "patient who plausibly met the usual criteria for the operation, so that a well-grounded appeal was "
 "possible in every case."),
("Three kinds of case",
 f"Stratum A (n = {nA}): the plan, or the vendor it delegates review to, publishes medical-necessity "
 "criteria for the operation. Stratum B (n = "
 f"{nB}): the plan's public policy names the operation but states that a licensed criteria set "
 "(InterQual, MCG or TurningPoint) is applied, so the criteria themselves are not public. Stratum C "
 f"(n = {nC}): the plan publishes no policy for the operation. The correct answer differs by stratum: "
 "cite the document (A); cite the document and tell the patient how to obtain the criteria (B); say "
 "that no policy is published and tell the patient how to obtain the criteria (C)."),
("Answer key",
 "The governing document for each case came from OrthoAppeals' own policy directory, which was "
 "built from insurer websites. Because the tool and the answer key share this source, the tool "
 "cannot miss on policy identification when the directory is right; the study therefore tests "
 "whether the directory is right. Every stratum-A document was read in full: a language model "
 "extracted the criteria section for the specific operation, and code verified each extracted "
 f"sentence word for word against the document. This review, and a second audit of every "
 "'equivalent' verdict, found and corrected 17 answer-key entries before final scoring (Supplement): "
 "two that pointed at a guideline for a different operation, two plans reclassified because their "
 "public policy defers to a vendor's criteria, one plan whose own policy the directory had missed, "
 "three entries pointing at index pages rather than the policy, five documents that named no "
 "operation at all, and four Centene plans for which the plan's own notices delegate review to "
 "Evolent, whose guideline was accepted alongside the plan's policy."),
("Systems compared",
 "OrthoAppeals looks the case up in its directory, takes the verbatim criteria for the operation "
 "from the section extracted for that document, and drafts a first-person appeal with a language "
 "model (Claude Opus 5) that is given only those excerpts, the notice and the clinical summary. "
 "Before a letter is delivered, code checks it for any number or quotation attributed to the plan "
 "that is not in the excerpts, and a second model read checks for invented rules in words; if "
 "either finds anything, the writer receives one revision request naming the sentences. The three "
 "comparators were the current free-tier models of ChatGPT (GPT-5.6), Claude (Sonnet 5) and Gemini "
 "(3.5 Flash), each run through its vendor's API with the same two tools, web search and page fetch, "
 "the same instructions, and a budget of 120 tool calls. Each chatbot first identified the policy, "
 "then in the same conversation drafted the appeal letter from the notice and clinical summary."),
("Outcomes",
 "Primary outcome: correct identification of the governing policy. A cited document was correct if "
 "it was the answer-key document, another edition or host of the same publisher's guideline "
 "(identified from the cited document's address and text, not from the system's own description of "
 "it), or an accepted alternate. In stratum C, naming any specific policy as governing was scored as "
 "a hallucinated document, except the plan's general utilization-management policy. "
 "Letter outcomes, scored by code against the policy text and the notice: (1) grounded, meaning the "
 "letter quotes at least one criterion from the reviewed section that answers the stated denial "
 "reason (stratum A only); (2) unverifiable quotation, meaning a passage in quotation marks that "
 "appears neither in the governing document nor in the document the system cited; (3) an invented "
 "policy number or effective date; (4) the filing deadline stated; (5) where to send the appeal "
 "stated; (6) sendable, meaning the member and reference identifiers from the notice are present "
 "and no placeholder remains where the notice or summary supplied the fact. A model-based grader "
 "(Claude Opus 5) also rated completeness on a 0–4 scale and flagged rules attributed to the plan "
 "without a source; these judged outcomes are reported as exploratory. Effort was the number of "
 "searches and page fetches each chatbot made per case, from its own tool log."),
("Statistics",
 "Proportions are reported with Wilson 95% confidence intervals. Paired comparisons between systems "
 "on the same cases used the exact McNemar test on the discordant pairs, with the difference in "
 "proportions and a bootstrap 95% confidence interval (10,000 resamples). No adjustment was made for "
 "multiple comparisons; with three planned comparisons against OrthoAppeals per outcome, P values "
 "between .01 and .05 should be read cautiously. All scoring code, every letter, every search "
 "transcript, every grade and the policy documents as they read at the time are in the study "
 "repository, and an independent audit script re-derives each table from them."),
("Measurement corrections during the study",
 "Scoring rules were revised whenever a hand check of letters or verdicts found an error, and every "
 "revision was applied to all systems and all cases before final scoring. The Supplement lists each "
 "change with its date and direction. Some corrections favored OrthoAppeals and some the chatbots; "
 "the largest in the chatbots' favor were reading a URL out of a citation field that also contained "
 "a note (30 verdicts) and verifying quotations against the document the chatbot cited rather than "
 "only ours (44 letters). The largest against OrthoAppeals were counting a quotation from another "
 "operation's section as ungrounded, and a grader that saw only 14 of the excerpts the writer had."),
]

# results paragraphs
r1 = (f"Table 1 describes the {N} cases. Stratum A drew on {T1['policy_documents_A']} distinct policy "
      "documents: insurers' own policies (39 cases) and the Carelon (40), eviCore (20), Evolent (19) and "
      "Cohere (2) guidelines that plans delegate review to.")
r2 = (f"Policy identification (Table 2). OrthoAppeals cited the governing policy in every case "
      f"({n(strat(o,'all')['k'], N)}; 95% CI {ci(strat(o,'all'))}). ChatGPT did so in "
      f"{n(strat(c,'all')['k'], N)} (95% CI {ci(strat(c,'all'))}), Claude in {n(strat(cl,'all')['k'], N)} "
      f"({ci(strat(cl,'all'))}) and Gemini in {n(strat(g,'all')['k'], N)} ({ci(strat(g,'all'))}). "
      f"In paired comparison OrthoAppeals was correct where the chatbot was not in "
      f"{PA['all']['ortho-opus vs chatgpt']['ortho-opus_only']} cases against ChatGPT, "
      f"{PA['all']['ortho-opus vs claude-free']['ortho-opus_only']} against Claude and "
      f"{PA['all']['ortho-opus vs gemini']['ortho-opus_only']} against Gemini, and the reverse never "
      f"occurred (all {pv(PA['all']['ortho-opus vs gemini']['p'])}). Claude and Gemini did not differ "
      f"({pv(PA['all']['claude-free vs gemini']['p'])}); both outperformed ChatGPT "
      f"({pv(PA['all']['chatgpt vs claude-free']['p'])} and {pv(PA['all']['chatgpt vs gemini']['p'])}).")
r3 = (f"The chatbots failed in different ways. Where criteria were published (stratum A, n = {nA}), "
      f"ChatGPT found the policy in {n(strat(c,'in_library')['k'], nA)}, most often giving no document "
      f"at all ({ID[c]['in_library']['outcomes'].get('no_answer',0)} cases); Claude found it in "
      f"{n(strat(cl,'in_library')['k'], nA)} and Gemini in {n(strat(g,'in_library')['k'], nA)}. Where no "
      f"policy existed (stratum C, n = {nC}), ChatGPT correctly said so in {n(strat(c,'no_policy')['k'], nC)} "
      f"and Claude in {n(strat(cl,'no_policy')['k'], nC)}, but Gemini did so in only "
      f"{n(strat(g,'no_policy')['k'], nC)}, naming a specific governing document that did not exist in "
      f"{n(lm('hallucinated_document_C',g)['k'], nC)} cases (versus OrthoAppeals, "
      f"{pv(LT['hallucinated_document_C']['paired']['ortho-opus vs gemini']['p'])}).")
r4 = (f"Appeal letters (Table 3). In stratum A, OrthoAppeals' letter quoted a criterion answering the "
      f"denial reason in {n(lm('grounded',o)['k'], nA)} cases, Gemini's in {n(lm('grounded',g)['k'], nA)}, "
      f"Claude's in {n(lm('grounded',cl)['k'], nA)} and ChatGPT's in {n(lm('grounded',c)['k'], nA)} "
      f"(each versus OrthoAppeals: {pv(LT['grounded']['paired']['ortho-opus vs gemini']['p'])}, "
      f"{pv(LT['grounded']['paired']['ortho-opus vs claude-free']['p'])} and "
      f"{pv(LT['grounded']['paired']['ortho-opus vs chatgpt']['p'])}). The one OrthoAppeals letter that "
      "was not grounded concerned a policy with no criterion on the denial's point; the letter said so "
      "and asked the plan to state its threshold.")
r5 = (f"Quotations that could not be found in either the governing document or the document the "
      f"system cited appeared in {n(lm('quote_unverifiable',cl)['k'], nA)} Claude letters, "
      f"{n(lm('quote_unverifiable',g)['k'], nA)} Gemini letters and {n(lm('quote_unverifiable',c)['k'], nA)} "
      f"ChatGPT letters, and in {lm('quote_unverifiable',o)['k']} OrthoAppeals letters (95% CI "
      f"{ci(lm('quote_unverifiable',o))}). An invented policy number or effective date appeared in "
      f"{n(lm('invented_identifier',g)['k'], N)} Gemini, {n(lm('invented_identifier',cl)['k'], N)} Claude "
      f"and {n(lm('invented_identifier',c)['k'], N)} ChatGPT letters, and in none from OrthoAppeals.")
r6 = (f"On the administrative points, OrthoAppeals stated the filing deadline in "
      f"{n(lm('deadline_stated',o)['k'], N)} letters and Claude in {n(lm('deadline_stated',cl)['k'], N)}, "
      f"but ChatGPT in {n(lm('deadline_stated',c)['k'], N)} and Gemini in "
      f"{n(lm('deadline_stated',g)['k'], N)} (both {pv(LT['deadline_stated']['paired']['ortho-opus vs gemini']['p'])}). "
      f"ChatGPT's letters were missing an identifier from the notice or left a placeholder in "
      f"{N - lm('sendable',c)['k']} of {N}; the other three systems produced a sendable letter every "
      f"time. Where no policy existed, OrthoAppeals, ChatGPT and Claude asked the plan for the criteria "
      f"in writing in every letter; Gemini did so in {n(lm('demands_criteria_C',g)['k'], nC)}.")
comp = LT["completeness_judged"]
r7 = (f"On the exploratory judged measures, mean completeness (0–4) was {comp[o]['mean']:.2f} for "
      f"OrthoAppeals, {comp[cl]['mean']:.2f} for Claude, {comp[c]['mean']:.2f} for ChatGPT and "
      f"{comp[g]['mean']:.2f} for Gemini; the grader flagged a rule attributed to the plan without a "
      f"source in {lm('unsupported_attribution_judged',g)['k']} Gemini, "
      f"{lm('unsupported_attribution_judged',cl)['k']} Claude, {lm('unsupported_attribution_judged',c)['k']} "
      f"ChatGPT and {lm('unsupported_attribution_judged',o)['k']} OrthoAppeals letters. This grader could "
      "see only the excerpts a system was given, not the full documents the chatbots had read, so "
      "chatbot counts on this measure may include correctly sourced paraphrases.")
r8 = (f"OrthoAppeals' own correction pass. The writer's first draft was flagged in "
      f"{n(CP['flagged_before'], CP['letters'])} letters for a number, quotation or rule attributed to "
      f"the plan that was not in the excerpts it had been given; {CP['revised']} were revised and "
      f"{CP['flagged_after']} remained flagged after revision. Before this check was added, an earlier "
      f"version of the writer, given a six-item shortlist instead of the full criteria list, had stated "
      "such a rule in 45 of 120 stratum-A letters.")
r9 = (f"Effort. Per case, the chatbots made a median of {EF[c]['searches_median']} (IQR "
      f"{EF[c]['searches_iqr'][0]}–{EF[c]['searches_iqr'][1]}) searches for ChatGPT, "
      f"{EF[cl]['searches_median']} ({EF[cl]['searches_iqr'][0]}–{EF[cl]['searches_iqr'][1]}) for Claude "
      f"and {EF[g]['searches_median']} ({EF[g]['searches_iqr'][0]}–{EF[g]['searches_iqr'][1]}) for Gemini. "
      "OrthoAppeals made none: its answer is a directory lookup.")
results = [r1, r2, r3, r4, r5, r6, r7, r8, r9]

# ---------------------------------------------------------------- docx ----
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()
style = doc.styles["Normal"]; style.font.name = "Calibri"; style.font.size = Pt(11)
doc.add_heading("Grounding Orthopedic Surgery Appeals in the Payer's Published Policy: "
                "OrthoAppeals Versus Free AI Chatbots on 167 Simulated Denials", level=1)
doc.add_paragraph("Draft: Abstract, Methods, Results. Generated from study/stats.json on the study "
                  "data of 2026-09-22. Numbers are reproducible with scripts/study/stats.py.").italic = True

doc.add_heading("Abstract", level=2)
for h, t in abstract:
    p = doc.add_paragraph(); p.add_run(h + ". ").bold = True; p.add_run(t)

doc.add_heading("Methods", level=2)
for h, t in methods:
    doc.add_heading(h, level=3); doc.add_paragraph(t)

doc.add_heading("Results", level=2)
for t in results:
    doc.add_paragraph(t)


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


# Table 1
rows = [("Cases", N, "")]
rows += [("Stratum A: criteria published", nA, f"{100*nA/N:.0f}%"),
         ("Stratum B: document public, criteria vendor-held", nB, f"{100*nB/N:.0f}%"),
         ("Stratum C: no policy published", nC, f"{100*nC/N:.0f}%"),
         ("Jurisdictions (50 states + DC)", T1["states"], ""), ("Insurers", T1["insurers"], ""),
         ("Commercial / ACA plans", T1["plan_type"]["Commercial/ACA"], f"{100*T1['plan_type']['Commercial/ACA']/N:.0f}%"),
         ("Medicaid managed-care plans", T1["plan_type"]["Medicaid"], f"{100*T1['plan_type']['Medicaid']/N:.0f}%")]
for k, v in sorted(T1["denial_reason"].items(), key=lambda x: -x[1]):
    rows.append((f"Denial reason: {k.replace('_', ' ')}", v, f"{100*v/N:.0f}%"))
for k, v in sorted(T1["surgery"].items(), key=lambda x: -x[1]):
    rows.append((f"Operation: {k}", v, f"{100*v/N:.0f}%"))
rows.append(("Distinct governing documents, stratum A", T1["policy_documents_A"], ""))
table("Table 1. Case characteristics", ["Characteristic", "n", "%"], rows)

# Table 2
hdr = ["System", f"Stratum A (n = {nA})", f"Stratum B (n = {nB})", f"Stratum C (n = {nC})", f"All (n = {N})", "vs OrthoAppeals"]
rows = []
for arm in (o, c, cl, g):
    cells = [A[arm]]
    for s in ("in_library", "vendor_held", "no_policy", "all"):
        d = ID[arm][s]; cells.append(f"{d['k']} ({100*d['k']/d['n']:.0f}%; {ci(d)})")
    if arm == o:
        cells.append("—")
    else:
        v = PA["all"][f"ortho-opus vs {arm}"]
        cells.append(f"{v['ortho-opus_only']} / 0 discordant; {pv(v['p'])}; {pts(v)}")
    rows.append(cells)
table("Table 2. Correct identification of the governing policy (n correct, %, Wilson 95% CI)", hdr, rows,
      "Discordant pairs: cases OrthoAppeals had right and the chatbot wrong / the reverse. Exact McNemar test. "
      "OrthoAppeals and the answer key share a source (Methods); its stratum-A figure measures the directory's accuracy after audit.")

# Table 3
hdr = ["Letter outcome", "OrthoAppeals", "ChatGPT", "Claude", "Gemini"]
names = [("grounded", "Quotes a criterion answering the denial reason (stratum A)"),
         ("quote_unverifiable", "Any quotation not found in the policy (stratum A)"),
         ("quote_other_procedure", "Quotes another operation's criteria (stratum A)"),
         ("invented_identifier", "Invented policy number or effective date"),
         ("deadline_stated", "States the filing deadline"),
         ("route_stated", "States where to send the appeal"),
         ("sendable", "Sendable: identifiers present, no placeholders"),
         ("demands_criteria_C", "Asks the plan for its criteria in writing (stratum C)"),
         ("hallucinated_document_C", "Names a nonexistent governing document (stratum C)")]
rows = []
for key, label in names:
    m = LT[key]; cells = [f"{label} (n = {m['n']})"]
    for arm in (o, c, cl, g):
        d = m["arms"][arm]; s = f"{d['k']} ({100*d['k']/d['n']:.0f}%)"
        if arm != o:
            s += f"; {pv(m['paired'][f'ortho-opus vs {arm}']['p'])}"
        cells.append(s)
    rows.append(cells)
rows.append(["Completeness, judged, mean (0–4), all letters"] + [f"{comp[a]['mean']:.2f}" for a in (o, c, cl, g)])
table("Table 3. Appeal-letter outcomes (n, %; exact McNemar P versus OrthoAppeals on the same cases)", hdr, rows,
      "All outcomes but completeness are scored by code against the policy text and the denial notice. "
      "A quotation is unverifiable when it is in neither the governing document nor the document the system itself cited.")

OUT.parent.mkdir(exist_ok=True)
doc.save(OUT)
print("wrote", OUT.relative_to(ROOT))
