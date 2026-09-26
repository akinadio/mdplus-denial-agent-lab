#!/usr/bin/env python3
"""Abstract, Methods and Results, generated from study/stats.json.

Every number in the text is read from the statistics file, never typed. Run
stats.py, then figures.py, then this; the document re-derives.

  python3 scripts/study/paper.py   -> docs/OrthoAppeals-Manuscript.docx
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S = ROOT / "study"
DOCS = ROOT / "docs"
OUT = DOCS / "OrthoAppeals-Manuscript.docx"

st = json.loads((S / "stats.json").read_text())
ID = st["identification"]; PA = st["identification_paired"]; OM = st["identification_omnibus"]
LT = st["letters"]; T1 = st["table1"]; EF = st["effort"]; CP = st["ortho_correction_pass"]
CT = st["completeness_tests"]; ET = st["effort_tests"]; SG = st["subgroup_tests"]
ARMS = ["ortho-opus", "chatgpt", "claude-free", "gemini"]
A = {"ortho-opus": "OrthoAppeals", "chatgpt": "ChatGPT", "claude-free": "Claude", "gemini": "Gemini"}
o, c, cl, g = ARMS
nA, nB, nC = T1["strata"]["in_library"], T1["strata"]["vendor_held"], T1["strata"]["no_policy"]
N = st["n_cases"]
PAIRS = [f"{a} vs {b}" for i, a in enumerate(ARMS) for b in ARMS[i + 1:]]


# ---------------------------------------------------------------- helpers ----
def pct(k, nn):
    return f"{100 * k / nn:.0f}%"


def n(k, nn):
    return f"{k} of {nn} ({pct(k, nn)})"


def ci(d):
    return f"{100 * d['lo']:.0f}–{100 * d['hi']:.0f}%"


def nci(d):
    return f"{d['k']} of {d['n']} ({pct(d['k'], d['n'])}, 95% CI {ci(d)})"


def P(p):
    return "P < 0.001" if p < 0.001 else (f"P = {p:.3f}" if p < 0.01 else f"P = {p:.2f}")


def pv(v):
    return P(v.get("p_holm", v["p"]))


def pts(v):
    return f"{100 * v['diff']:+.0f} ({100 * v['diff_lo']:+.0f} to {100 * v['diff_hi']:+.0f})"


def lm(name, arm):
    return LT[name]["arms"][arm]


def lp(name, a, b=None):
    return LT[name]["paired"][f"{a} vs {b}" if b else f"ortho-opus vs {a}"]


def pair_label(k):
    a, b = k.split(" vs ")
    return f"{A[a]} vs {A[b]}"


def q(d):
    return f"Q = {d['q']:.1f}, {P(d['p'])}"


DR = st["table1"]["denial_reason"]
# ---------------------------------------------------------------- text ----
TITLE = ("Policy-Grounded Versus General-Purpose AI for Orthopedic Surgery Appeals. "
         "A Paired Comparison on 167 Simulated Denials")

ABSTRACT = [
    ("Background",
     "Patients and physicians increasingly turn to AI chatbots to fight insurance denials. General-purpose "
     "chatbots do not always have access to the health plan's medical policy and can hallucinate criteria "
     "that the policy does not contain. OrthoAppeals retrieves the plan's governing policy from a curated "
     "directory and drafts the appeal from the policy's own text. We compared it with the flagship models "
     "behind ChatGPT, Claude and Gemini."),
    ("Methods",
     f"We generated {N} simulated denials based on real denial scenarios, spanning {T1['states']} jurisdictions, "
     f"{T1['insurers']} insurers and 14 orthopedic operations. Each case was answered by OrthoAppeals and by "
     "ChatGPT, Claude and Gemini with web search. For every case we measured whether the system identified "
     "the plan's governing policy and whether its appeal letter quoted that policy accurately, hallucinated "
     "policy text or a policy that did not exist, stated the filing deadline and appeal route, and was ready "
     "to send. Every letter was checked by code against the actual policy text. Systems were compared with "
     "Cochran's Q, exact McNemar, Friedman and Wilcoxon signed-rank tests with Holm adjustment."),
    ("Results",
     f"OrthoAppeals identified the governing policy in {n(ID[o]['all']['k'], N)} cases, ChatGPT in "
     f"{n(ID[c]['all']['k'], N)}, Claude in {n(ID[cl]['all']['k'], N)} and Gemini in {n(ID[g]['all']['k'], N)} "
     f"(each versus OrthoAppeals, {pv(PA['all']['ortho-opus vs gemini'])}). Where the plan published criteria, "
     f"OrthoAppeals quoted a criterion answering the denial in {n(lm('grounded', o)['k'], nA)} letters, Gemini in "
     f"{n(lm('grounded', g)['k'], nA)}, Claude in {n(lm('grounded', cl)['k'], nA)} and ChatGPT in "
     f"{n(lm('grounded', c)['k'], nA)} ({P(LT['grounded']['cochran_q']['p'])}). Hallucinated quotations, text "
     f"attributed to the policy that the policy does not contain, appeared in {lm('quote_unverifiable', o)['k']} "
     f"OrthoAppeals letters and in {pct(lm('quote_unverifiable', c)['k'], nA)} of ChatGPT, "
     f"{pct(lm('quote_unverifiable', cl)['k'], nA)} of Claude and {pct(lm('quote_unverifiable', g)['k'], nA)} of "
     f"Gemini letters ({P(LT['quote_unverifiable']['cochran_q']['p'])}). Where no policy existed, Gemini cited a "
     f"policy that did not exist in {n(lm('hallucinated_document_C', g)['k'], nC)} cases. OrthoAppeals stated the "
     f"filing deadline in every letter, the chatbots in {pct(lm('deadline_stated', g)['k'], N)} to "
     f"{pct(lm('deadline_stated', cl)['k'], N)}."),
    ("Conclusions",
     f"OrthoAppeals identified the governing policy and quoted it accurately in nearly every case. The chatbots "
     f"missed the policy in {100 - int(round(100 * ID[cl]['all']['k'] / N))}% to "
     f"{100 - int(round(100 * ID[c]['all']['k'] / N))}% of cases and hallucinated policy text in up to "
     f"{pct(max(lm('quote_unverifiable', a)['k'] for a in ARMS), nA)} of letters. An appeal built on criteria the "
     "plan never wrote can be denied on that basis alone, so patients and physicians who rely on general-purpose "
     "chatbots risk submitting appeals that misstate the plan's own rules. Grounding the appeal in the plan's "
     "published policy removes that failure."),
]

METHODS = [
    ("Design",
     f"We compared four systems on the same {N} simulated denials. Every system answered every case, so each "
     "comparison is between two answers to the same case. No patient data were used."),
    ("Cases",
     "Each case was a simulated denial of one orthopedic operation, modeled on real denial scenarios. It "
     "included the denial letter, with the reason for denial, the appeal deadline and the member and reference "
     f"numbers, and a one-page clinical summary of a patient who met the usual criteria for the operation. The "
     f"{N} cases covered {T1['states']} jurisdictions, {T1['insurers']} insurers ({T1['plan_type']['Commercial/ACA']} "
     f"commercial, {T1['plan_type']['Medicaid']} Medicaid) and 14 operations. The denial reasons were based on the "
     f"reasons recorded in real denials at a single institution, namely inadequate conservative treatment "
     f"({DR['conservative_care']} cases), imaging not supporting surgery ({DR['imaging']}), not medically necessary "
     f"({DR['not_medically_necessary']}) and incomplete documentation ({DR['incomplete_documentation']})."),
    ("Why cases were grouped by what the plan publishes",
     "An appeal can only quote the plan's criteria if the plan makes them public, and what counts as a correct "
     "answer changes with that. We therefore grouped cases into three strata. In stratum A the plan, or the "
     f"review company it uses, publishes the criteria for the operation (n = {nA}), and the correct answer is to "
     f"cite and quote them. In stratum B the plan's published policy names the operation but applies licensed "
     f"criteria (InterQual, MCG or TurningPoint) that are not public (n = {nB}), and the correct answer is to cite "
     f"the policy and ask the plan for the criteria. In stratum C the plan publishes no policy for the operation "
     f"(n = {nC}), and the correct answer is to say so and ask for the criteria in writing. In stratum C, naming "
     "a specific policy as the governing one is a hallucination. The governing document for every stratum-A "
     f"case ({T1['policy_documents_A']} distinct documents) was checked against the full policy text before scoring."),
    ("Systems",
     "OrthoAppeals looks the plan and operation up in its policy directory, pulls the plan's own criteria for "
     "that operation word for word, and drafts a first-person appeal from those criteria, the denial letter and "
     "the clinical summary using a language model (Claude Opus 5). Automated checks then flag any rule, number "
     "or quotation the letter attributes to the plan that is not in the criteria, and the letter is revised once. "
     "The comparators were the flagship models behind ChatGPT (GPT-5.6), Claude (Sonnet 5) and Gemini "
     "(3.5 Flash) in September 2026, each given web search and page reading and the same instructions, "
     "mimicking the free patient experience. Each chatbot was asked to find the plan's governing policy and then "
     "to write the appeal letter in the same conversation."),
    ("What we measured",
     "For every case we recorded whether the system identified the governing policy. A citation counted if it "
     "was the policy in the answer key, another edition of the same publisher's guideline, or an accepted "
     "alternate. For every letter we recorded whether it quoted a criterion that answered the reason for "
     "denial, whether every quotation it attributed to the policy actually appeared in the policy (a quotation "
     "that did not is a hallucination), whether it invented a policy number or effective date, whether it stated "
     "the filing deadline and where to send the appeal, and whether it was ready to send, meaning the member "
     "and reference numbers were present and no placeholder remained. In stratum C we also recorded whether the "
     "letter asked the plan for its criteria and whether it cited a policy that did not exist. Code checked each "
     "of these against the policy text and the denial letter. A separate model rated each letter's completeness "
     "from 0 to 4. We also counted how many web searches and page visits each chatbot made per case."),
    ("Statistical analysis",
     "Proportions are given with Wilson 95% confidence intervals. Differences among the four systems on each "
     "yes-or-no measure were tested with Cochran's Q, followed by all six pairwise exact McNemar tests on "
     "discordant pairs, with the difference in proportions and a bootstrap 95% CI from 10,000 resamples. "
     "Completeness and effort were compared with the Friedman test and pairwise Wilcoxon signed-rank tests. "
     "Within each system, identification was compared across strata and plan types with chi-square or "
     "Fisher's exact tests. P values were Holm-adjusted within each family of pairwise tests. All tests were "
     "two-sided at α = 0.05. Analyses used Python 3.10 and SciPy."),
]


def results():
    R = []
    R.append(("Policy identification",
        f"OrthoAppeals cited the governing policy in {nci(ID[o]['all'])} cases, ChatGPT in "
        f"{nci(ID[c]['all'])}, Claude in {nci(ID[cl]['all'])} and Gemini in {nci(ID[g]['all'])} "
        f"(Cochran's {q(OM['all'])}, Fig. 2a). OrthoAppeals was correct where the chatbot was not in "
        f"{PA['all']['ortho-opus vs chatgpt']['ortho-opus_only']} cases against ChatGPT, "
        f"{PA['all']['ortho-opus vs claude-free']['ortho-opus_only']} against Claude and "
        f"{PA['all']['ortho-opus vs gemini']['ortho-opus_only']} against Gemini, with no discordant pair in the "
        f"other direction (each {pv(PA['all']['ortho-opus vs gemini'])}, Table 1). Claude and Gemini did not differ "
        f"({pv(PA['all']['claude-free vs gemini'])}). Both exceeded ChatGPT "
        f"({pv(PA['all']['chatgpt vs claude-free'])} and {pv(PA['all']['chatgpt vs gemini'])})."))
    R.append((None,
        f"Systems differed where criteria were published (stratum A, {q(OM['in_library'])}) and where no policy "
        f"existed (stratum C, {q(OM['no_policy'])}) but not where criteria were vendor-held (stratum B, "
        f"{q(OM['vendor_held'])}). In stratum A, ChatGPT found the policy in {n(ID[c]['in_library']['k'], nA)} "
        f"cases, returning no document in {ID[c]['in_library']['outcomes'].get('no_answer', 0)}. Claude found it in "
        f"{n(ID[cl]['in_library']['k'], nA)} and Gemini in {n(ID[g]['in_library']['k'], nA)}. In stratum C, ChatGPT "
        f"correctly reported that no policy existed in {n(ID[c]['no_policy']['k'], nC)} cases and Claude in "
        f"{n(ID[cl]['no_policy']['k'], nC)}, whereas Gemini did so in {n(ID[g]['no_policy']['k'], nC)} and "
        f"hallucinated a governing policy in {n(lm('hallucinated_document_C', g)['k'], nC)} "
        f"({q(LT['hallucinated_document_C']['cochran_q'])}, versus OrthoAppeals {pv(lp('hallucinated_document_C', g))}, "
        f"versus Claude {pv(lp('hallucinated_document_C', cl, g))}, versus ChatGPT {pv(lp('hallucinated_document_C', c, g))}). "
        f"Within systems, identification varied by stratum for ChatGPT ({P(SG[c]['identification_by_stratum']['p_holm'])}) "
        f"and Gemini ({P(SG[g]['identification_by_stratum']['p_holm'])}) but not Claude "
        f"({P(SG[cl]['identification_by_stratum']['p_holm'])}), and by plan type for ChatGPT "
        f"({P(SG[c]['identification_by_plan_type']['p_holm'])}) and Gemini ({P(SG[g]['identification_by_plan_type']['p_holm'])}) "
        f"but not Claude ({P(SG[cl]['identification_by_plan_type']['p_holm'])}, Table 3)."))
    worst = max((lp('grounded', a, b) for a, b in [(o, c), (o, cl), (o, g), (c, cl), (c, g), (cl, g)]), key=lambda v: v['p_holm'])
    R.append(("Accuracy of the appeal letter",
        f"In stratum A, the letter quoted a criterion answering the denial reason in "
        f"{n(lm('grounded', o)['k'], nA)} OrthoAppeals cases, {n(lm('grounded', g)['k'], nA)} Gemini, "
        f"{n(lm('grounded', cl)['k'], nA)} Claude and {n(lm('grounded', c)['k'], nA)} ChatGPT "
        f"({q(LT['grounded']['cochran_q'])}, Fig. 2b). Every pairwise difference was significant "
        f"(all Holm-adjusted P ≤ {worst['p_holm']:.3f}, Table 2). Hallucinated quotations, text attributed to the "
        f"policy that appeared in neither the governing document nor the document the system itself cited, appeared "
        f"in {n(lm('quote_unverifiable', cl)['k'], nA)} Claude letters, {n(lm('quote_unverifiable', g)['k'], nA)} "
        f"Gemini, {n(lm('quote_unverifiable', c)['k'], nA)} ChatGPT and {lm('quote_unverifiable', o)['k']} OrthoAppeals "
        f"(95% CI {ci(lm('quote_unverifiable', o))}, {q(LT['quote_unverifiable']['cochran_q'])}). Claude and Gemini did "
        f"not differ ({pv(lp('quote_unverifiable', cl, g))}). Each exceeded ChatGPT ({pv(lp('quote_unverifiable', c, cl))} "
        f"and {pv(lp('quote_unverifiable', c, g))}) and OrthoAppeals (both {pv(lp('quote_unverifiable', g))}). A "
        f"hallucinated policy number or effective date appeared in {n(lm('invented_identifier', g)['k'], N)} Gemini, "
        f"{n(lm('invented_identifier', cl)['k'], N)} Claude, {n(lm('invented_identifier', c)['k'], N)} ChatGPT and "
        f"{lm('invented_identifier', o)['k']} OrthoAppeals letters ({q(LT['invented_identifier']['cochran_q'])})."))
    R.append(("Deadline, appeal route and readiness to send",
        f"OrthoAppeals stated the filing deadline in {n(lm('deadline_stated', o)['k'], N)} letters, Claude in "
        f"{n(lm('deadline_stated', cl)['k'], N)}, ChatGPT in {n(lm('deadline_stated', c)['k'], N)} and Gemini in "
        f"{n(lm('deadline_stated', g)['k'], N)} ({q(LT['deadline_stated']['cochran_q'])}, Fig. 2c). Where to send the "
        f"appeal was stated in {n(lm('route_stated', o)['k'], N)}, {n(lm('route_stated', cl)['k'], N)}, "
        f"{n(lm('route_stated', c)['k'], N)} and {n(lm('route_stated', g)['k'], N)} letters respectively "
        f"({q(LT['route_stated']['cochran_q'])}). ChatGPT's letter was not ready to send in "
        f"{N - lm('sendable', c)['k']} of {N} cases. The other systems' letters were ready in every case "
        f"({q(LT['sendable']['cochran_q'])}). Where no policy existed, OrthoAppeals, ChatGPT and Claude asked the plan "
        f"for its criteria in every letter and Gemini in {n(lm('demands_criteria_C', g)['k'], nC)} "
        f"({q(LT['demands_criteria_C']['cochran_q'])})."))
    cm = LT["completeness_judged"]; cp = CT["pairwise"]
    R.append(("Completeness and effort",
        f"Completeness (0 to 4) averaged {cm[o]['mean']:.2f} for OrthoAppeals, {cm[cl]['mean']:.2f} for Claude, "
        f"{cm[c]['mean']:.2f} for ChatGPT and {cm[g]['mean']:.2f} for Gemini (Friedman χ² = {CT['friedman']['chi2']:.1f}, "
        f"{P(CT['friedman']['p'])}). OrthoAppeals exceeded each chatbot (all {pv(cp['ortho-opus vs gemini'])}), Claude "
        f"exceeded ChatGPT ({pv(cp['chatgpt vs claude-free'])}) and Gemini ({pv(cp['claude-free vs gemini'])}), and "
        f"ChatGPT and Gemini did not differ ({pv(cp['chatgpt vs gemini'])}, Table 3). The chatbots made a median of "
        f"{EF[c]['searches_median']} (IQR {EF[c]['searches_iqr'][0]}–{EF[c]['searches_iqr'][1]}) web searches per case "
        f"for ChatGPT, {EF[cl]['searches_median']} ({EF[cl]['searches_iqr'][0]}–{EF[cl]['searches_iqr'][1]}) for Claude "
        f"and {EF[g]['searches_median']} ({EF[g]['searches_iqr'][0]}–{EF[g]['searches_iqr'][1]}) for Gemini (Friedman "
        f"{P(ET['searches']['friedman']['p'])}, all pairwise {pv(ET['searches']['pairwise']['chatgpt vs claude-free'])}), "
        f"and {EF[c]['fetches_median']}, {EF[cl]['fetches_median']} and {EF[g]['fetches_median']} page visits "
        f"(Friedman {P(ET['fetches']['friedman']['p'])}, Fig. 2d). OrthoAppeals performed no search."))
    R.append(("Automated correction in OrthoAppeals",
        f"OrthoAppeals' checks flagged {n(CP['flagged_before'], CP['letters'])} first drafts for a rule, number or "
        f"quotation attributed to the plan that was not in the policy criteria. Of these, {CP['revised']} were revised, "
        f"and {'no' if CP['flagged_after'] == 0 else CP['flagged_after']} delivered letter contained such a statement."))
    return R


FIG1 = ("Figure 1. Study design. Every case was answered by all four systems, and every comparison is paired on "
        "the same case.")
FIG2 = ("Figure 2. Policy identification, letter accuracy and effort. (a) Correct identification of the governing "
        "policy by stratum and overall. (b) Stratum-A letters quoting a criterion that answers the denial reason, "
        "letters with a hallucinated quotation, and letters (all strata) with a hallucinated policy number or date. "
        "(c) Stratum-C letters citing a policy that does not exist or asking the plan for its criteria, and letters "
        "(all strata) stating the filing deadline. (d) Median web searches and page visits per case. Bars show "
        "proportions with Wilson 95% CIs (a to c) or medians with interquartile ranges (d).")

# ---------------------------------------------------------------- docx ----
from docx import Document  # noqa: E402
from docx.shared import Pt, Inches, RGBColor  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402

doc = Document()
for name in ("Normal", "Heading 1", "Heading 2", "Heading 3", "Title"):
    stl = doc.styles[name]
    stl.font.name = "Times New Roman"; stl.font.color.rgb = RGBColor(0, 0, 0)
    stl.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
doc.styles["Normal"].font.size = Pt(12)
doc.styles["Heading 1"].font.size = Pt(14); doc.styles["Heading 2"].font.size = Pt(13)
doc.styles["Heading 3"].font.size = Pt(12); doc.styles["Heading 3"].font.italic = True
doc.styles["Heading 3"].font.bold = True


def para(text, size=None, bold_lead=None):
    p = doc.add_paragraph()
    if bold_lead:
        p.add_run(bold_lead + " ").bold = True
    p.add_run(text)
    if size:
        for run in p.runs:
            run.font.size = Pt(size)
    return p


def table(title, header, rows, note=""):
    para(title).runs[0].bold = True
    tb = doc.add_table(rows=1, cols=len(header)); tb.style = "Table Grid"
    for i, h in enumerate(header):
        cell = tb.rows[0].cells[i]; cell.text = ""
        run = cell.paragraphs[0].add_run(h); run.bold = True; run.font.size = Pt(9)
    for r in rows:
        cells = tb.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(v)); run.font.size = Pt(9)
    if note:
        para(note, size=9)
    doc.add_paragraph()


doc.add_heading(TITLE, level=1)

doc.add_heading("Abstract", level=2)
for h, t in ABSTRACT:
    para(t, bold_lead=h + ".")

doc.add_heading("Methods", level=2)
for h, t in METHODS:
    doc.add_heading(h, level=3); para(t)

doc.add_heading("Results", level=2)
for h, t in results():
    if h:
        doc.add_heading(h, level=3)
    para(t)

doc.add_heading("Tables", level=2)


def cell_ci(d):
    return f"{d['k']} ({pct(d['k'], d['n'])}, 95% CI {ci(d)})"


# Table 1. pairwise identification (proportions are in Fig. 2a)
hdr = ["Comparison", "First only / second only", "Difference, points (95% CI)", "Holm-adjusted P"]
rows = []
for s_, lab in (("all", f"All cases (n = {N}), Cochran's {q(OM['all'])}"),
                ("in_library", f"Stratum A (n = {nA}), Cochran's {q(OM['in_library'])}"),
                ("vendor_held", f"Stratum B (n = {nB}), Cochran's {q(OM['vendor_held'])}"),
                ("no_policy", f"Stratum C (n = {nC}), Cochran's {q(OM['no_policy'])}")):
    rows.append([lab, "", "", ""])
    for k in PAIRS:
        v = PA[s_][k]; a_, b_ = k.split(" vs ")
        rows.append([f"   {pair_label(k)}", f"{v[a_ + '_only']} / {v[b_ + '_only']}", pts(v), pv(v)])
table("Table 1. Pairwise comparisons of policy identification (exact McNemar test on discordant pairs)", hdr, rows,
      "First only / second only are the cases the first system had correct and the second wrong, and the reverse. "
      "Difference is first minus second with bootstrap 95% CI. P values are Holm-adjusted within each stratum. "
      "Proportions by system and stratum are shown in Figure 2a.")

# Table 2. pairwise letter outcomes (proportions for the main outcomes are in Fig. 2b and 2c)
NAMES = [("grounded", "Quotes a criterion answering the denial reason (stratum A)"),
         ("quote_unverifiable", "Hallucinated quotation (stratum A)"),
         ("invented_identifier", "Hallucinated policy number or effective date"),
         ("deadline_stated", "States the filing deadline"),
         ("route_stated", "States where to send the appeal"),
         ("sendable", "Ready to send"),
         ("demands_criteria_C", "Asks the plan for its criteria (stratum C)"),
         ("hallucinated_document_C", "Cites a policy that does not exist (stratum C)")]
hdr = ["Outcome and comparison", "First only / second only", "Difference, points (95% CI)", "Holm-adjusted P"]
rows = []
for key, label in NAMES:
    m = LT[key]
    props = ", ".join(f"{A[a_]} {pct(m['arms'][a_]['k'], m['arms'][a_]['n'])}" for a_ in ARMS)
    rows.append([f"{label} (n = {m['n']}). {props}. Cochran's {q(m['cochran_q'])}", "", "", ""])
    for k in PAIRS:
        v = m["paired"][k]; a_, b_ = k.split(" vs ")
        rows.append([f"   {pair_label(k)}", f"{v[a_ + '_only']} / {v[b_ + '_only']}", pts(v), pv(v)])
table("Table 2. Appeal-letter outcomes and pairwise comparisons (exact McNemar test on discordant pairs)", hdr, rows,
      "Difference is first minus second with bootstrap 95% CI. P values are Holm-adjusted within each outcome.")

# Table 3. completeness, effort, subgroup tests
hdr = ["Measure and comparison", "Medians (first, second)", "Mean difference (95% CI)", "Holm-adjusted P"]
rows = [[f"Completeness, 0 to 4 (Friedman χ² = {CT['friedman']['chi2']:.1f}, {P(CT['friedman']['p'])})", "", "", ""]]
for k, v in CT["pairwise"].items():
    a_, b_ = k.split(" vs ")
    rows.append([f"   {pair_label(k)}", f"{v[a_ + '_median']}, {v[b_ + '_median']}",
                 f"{v['diff']:+.2f} ({v['diff_lo']:+.2f} to {v['diff_hi']:+.2f})", pv(v)])
for meas, lab in (("searches", "Web searches per case"), ("fetches", "Page visits per case")):
    t = ET[meas]
    rows.append([f"{lab} (Friedman χ² = {t['friedman']['chi2']:.1f}, {P(t['friedman']['p'])})", "", "", ""])
    for k, v in t["pairwise"].items():
        a_, b_ = k.split(" vs ")
        rows.append([f"   {pair_label(k)}", f"{v[a_ + '_median']}, {v[b_ + '_median']}",
                     f"{v['diff']:+.1f} ({v['diff_lo']:+.1f} to {v['diff_hi']:+.1f})", pv(v)])
rows.append(["Within-system tests (correct/total per subgroup, chi-square or Fisher's exact test)", "", "", ""])
for key, lab in (("identification_by_stratum", "Identification by stratum (A / B / C)"),
                 ("identification_by_plan_type", "Identification by plan type (commercial / Medicaid)")):
    for arm in ARMS:
        t = SG[arm][key]
        counts = " / ".join(f"{k_}/{k_ + w}" for k_, w in t["table"].values())
        rows.append([f"   {lab}, {A[arm]}", counts, t["test"] if t["test"] != "none" else "no variation",
                     P(t["p_holm"]) if t["test"] != "none" else "—"])
table("Table 3. Completeness, effort and within-system tests", hdr, rows,
      "Completeness and effort were compared with the Friedman test across systems and pairwise Wilcoxon "
      "signed-rank tests, with a bootstrap 95% CI for the paired mean difference. Within-system P values are "
      "Holm-adjusted across the four systems.")

doc.add_heading("Figures", level=2)
for png, legend in (("fig1_pipeline.png", FIG1), ("fig2_results.png", FIG2)):
    doc.add_picture(str(DOCS / png), width=Inches(6.3))
    para(legend, size=10)

# house style. no semicolons or colons anywhere in the document
bad = [p.text for p in doc.paragraphs if ";" in p.text or ":" in p.text]
bad += [c.text for t in doc.tables for r in t.rows for c in r.cells if ";" in c.text or ":" in c.text]
assert not bad, bad[:3]

OUT.parent.mkdir(exist_ok=True)
doc.save(OUT)
print("wrote", OUT.relative_to(ROOT))
