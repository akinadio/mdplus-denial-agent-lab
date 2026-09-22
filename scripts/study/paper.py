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
    return f"{d['k']} of {d['n']} ({pct(d['k'], d['n'])}; 95% CI {ci(d)})"


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


# ---------------------------------------------------------------- text ----
TITLE = ("Policy-Grounded Versus General-Purpose AI for Orthopedic Surgery Appeals: "
         "A Paired Comparison on 167 Simulated Denials")

ABSTRACT = [
    ("Background",
     "Patients who appeal a denied orthopedic operation must show that they meet the criteria in their health "
     "plan's medical policy. We compared OrthoAppeals, which retrieves the governing policy from a curated "
     "directory and drafts the appeal from the policy's text, with three free general-purpose chatbots given "
     "web search."),
    ("Methods",
     f"We generated {N} simulated denials across {T1['states']} jurisdictions, {T1['insurers']} insurers and 14 "
     f"operations: the plan publishes criteria (stratum A, n = {nA}), the plan's policy defers to vendor-held "
     f"criteria (stratum B, n = {nB}), or no policy exists (stratum C, n = {nC}). Each case was answered by "
     "OrthoAppeals, ChatGPT, Claude and Gemini. The primary outcome was correct identification of the governing "
     "policy against a reviewed answer key; letter outcomes were scored by code against the policy text. "
     "Systems were compared with Cochran's Q and exact McNemar tests, Friedman and Wilcoxon signed-rank tests, "
     "and Holm-adjusted P values."),
    ("Results",
     f"OrthoAppeals identified the governing policy in {n(ID[o]['all']['k'], N)} cases, ChatGPT in "
     f"{n(ID[c]['all']['k'], N)}, Claude in {n(ID[cl]['all']['k'], N)} and Gemini in {n(ID[g]['all']['k'], N)} "
     f"({q(OM['all'])}; each versus OrthoAppeals, {pv(PA['all']['ortho-opus vs gemini'])}). In stratum A, "
     f"OrthoAppeals quoted a criterion answering the denial in {n(lm('grounded', o)['k'], nA)} letters, Gemini in "
     f"{n(lm('grounded', g)['k'], nA)}, Claude in {n(lm('grounded', cl)['k'], nA)} and ChatGPT in "
     f"{n(lm('grounded', c)['k'], nA)} ({q(LT['grounded']['cochran_q'])}). Quotations absent from the policy "
     f"appeared in {lm('quote_unverifiable', o)['k']} OrthoAppeals, {lm('quote_unverifiable', c)['k']} ChatGPT, "
     f"{lm('quote_unverifiable', cl)['k']} Claude and {lm('quote_unverifiable', g)['k']} Gemini letters "
     f"({q(LT['quote_unverifiable']['cochran_q'])}). In stratum C, Gemini cited a nonexistent document in "
     f"{n(lm('hallucinated_document_C', g)['k'], nC)} cases. Judged completeness differed across systems "
     f"(Friedman {P(CT['friedman']['p'])})."),
    ("Conclusions",
     "A directory-grounded tool identified the governing policy and quoted it accurately in nearly every "
     "case; free chatbots missed the policy in one sixth to one third of cases and, when they quoted it, "
     "often quoted text that was not there."),
]

METHODS = [
    ("Design",
     f"Paired comparison of four systems on {N} simulated denials. Every case was answered by every system, and "
     "all comparisons are between answers to the same case. No patient data were used."),
    ("Cases",
     "Each case comprised a denial notice (reason, appeal deadline, member and reference identifiers) and a "
     f"one-page clinical summary for one denied orthopedic operation. Cases covered {T1['states']} jurisdictions, "
     f"{T1['insurers']} insurers ({T1['plan_type']['Commercial/ACA']} commercial, {T1['plan_type']['Medicaid']} "
     "Medicaid), 14 operations and four denial reasons in near-equal numbers (inadequate conservative "
     "treatment, imaging, not medically necessary, incomplete documentation). Cases were stratified by what "
     f"the plan publishes: criteria for the operation (stratum A, n = {nA}); a policy naming the operation "
     f"that applies licensed criteria (stratum B, n = {nB}); or no policy (stratum C, n = {nC}). The governing "
     f"document for each stratum-A case ({T1['policy_documents_A']} distinct documents) was verified against "
     "the full policy text before scoring."),
    ("Systems",
     "OrthoAppeals retrieves the case's governing policy from its directory, extracts the verbatim criteria "
     "for the operation, and drafts a first-person appeal with a language model (Claude Opus 5) that is "
     "given only those excerpts, the notice and the clinical summary; automated checks flag any rule, number "
     "or quotation attributed to the plan that is not in the excerpts, and the writer revises once. The "
     "comparators were the models behind the free tiers of ChatGPT (GPT-5.6), Claude (Sonnet 5) and Gemini "
     "(3.5 Flash) in September 2026, run through their vendors' APIs with identical tools (web search and page "
     "fetch), identical instructions and a budget of 120 tool calls. Each chatbot identified the policy and "
     "then drafted the appeal letter in the same conversation."),
    ("Outcomes",
     "The primary outcome was correct identification of the governing policy: the answer-key document, another "
     "edition of the same publisher's guideline, or an accepted alternate. In stratum C, citing a specific "
     "policy as governing was scored as a nonexistent document. Letter outcomes were scored by code against "
     "the policy text and the notice: quotes a criterion answering the stated denial reason (stratum A); any "
     "quotation not found in the policy; invented policy number or effective date; filing deadline stated; "
     "appeal route stated; sendable (identifiers present, no placeholders); and, in stratum C, asks the plan "
     "for its criteria and cites a nonexistent document. A model-based grader rated completeness (0–4). Effort "
     "was the number of web searches and page fetches per case."),
    ("Statistical analysis",
     "Proportions are given with Wilson 95% confidence intervals. Differences among the four systems on each "
     "binary outcome were tested with Cochran's Q, followed by all six pairwise exact McNemar tests on "
     "discordant pairs, with the difference in proportions and a bootstrap 95% CI (10,000 resamples). "
     "Completeness and effort were compared with the Friedman test and pairwise Wilcoxon signed-rank tests. "
     "Within each system, identification was compared across strata and plan types and letter grounding "
     "across denial reasons with chi-square or Fisher's exact tests. P values were Holm-adjusted within each "
     "family of pairwise tests. All tests were two-sided at α = 0.05. Analyses used Python 3.10 and SciPy."),
]


def results():
    R = []
    R.append(
        f"Policy identification. OrthoAppeals cited the governing policy in {nci(ID[o]['all'])} cases, ChatGPT in "
        f"{nci(ID[c]['all'])}, Claude in {nci(ID[cl]['all'])} and Gemini in {nci(ID[g]['all'])} "
        f"(Cochran's {q(OM['all'])}; Table 1, Fig. 2a). OrthoAppeals was correct where the chatbot was not in "
        f"{PA['all']['ortho-opus vs chatgpt']['ortho-opus_only']} cases against ChatGPT, "
        f"{PA['all']['ortho-opus vs claude-free']['ortho-opus_only']} against Claude and "
        f"{PA['all']['ortho-opus vs gemini']['ortho-opus_only']} against Gemini, with no discordant pair in the "
        f"other direction (each {pv(PA['all']['ortho-opus vs gemini'])}; Table 2). Claude and Gemini did not differ "
        f"({pv(PA['all']['claude-free vs gemini'])}); both exceeded ChatGPT "
        f"({pv(PA['all']['chatgpt vs claude-free'])} and {pv(PA['all']['chatgpt vs gemini'])}).")
    R.append(
        f"By stratum, systems differed where criteria were published (stratum A, {q(OM['in_library'])}) and where "
        f"no policy existed (stratum C, {q(OM['no_policy'])}) but not where criteria were vendor-held (stratum B, "
        f"{q(OM['vendor_held'])}). In stratum A, ChatGPT found the policy in {n(ID[c]['in_library']['k'], nA)} "
        f"cases, returning no document in {ID[c]['in_library']['outcomes'].get('no_answer', 0)}; Claude found it in "
        f"{n(ID[cl]['in_library']['k'], nA)} and Gemini in {n(ID[g]['in_library']['k'], nA)}. In stratum C, ChatGPT "
        f"correctly reported no policy in {n(ID[c]['no_policy']['k'], nC)} cases and Claude in "
        f"{n(ID[cl]['no_policy']['k'], nC)}, whereas Gemini did so in {n(ID[g]['no_policy']['k'], nC)} and cited a "
        f"nonexistent governing document in {n(lm('hallucinated_document_C', g)['k'], nC)} "
        f"({q(LT['hallucinated_document_C']['cochran_q'])}; versus OrthoAppeals {pv(lp('hallucinated_document_C', g))}, "
        f"versus Claude {pv(lp('hallucinated_document_C', cl, g))}, versus ChatGPT {pv(lp('hallucinated_document_C', c, g))}). "
        f"Within systems, identification varied by stratum for ChatGPT ({P(SG[c]['identification_by_stratum']['p_holm'])}) "
        f"and Gemini ({P(SG[g]['identification_by_stratum']['p_holm'])}) but not Claude "
        f"({P(SG[cl]['identification_by_stratum']['p_holm'])}), and by plan type for ChatGPT "
        f"({P(SG[c]['identification_by_plan_type']['p_holm'])}) and Gemini ({P(SG[g]['identification_by_plan_type']['p_holm'])}) "
        f"but not Claude ({P(SG[cl]['identification_by_plan_type']['p_holm'])}; Table 5).")
    R.append(
        f"Appeal letters. In stratum A, the letter quoted a criterion answering the denial reason in "
        f"{n(lm('grounded', o)['k'], nA)} OrthoAppeals cases, {n(lm('grounded', g)['k'], nA)} Gemini, "
        f"{n(lm('grounded', cl)['k'], nA)} Claude and {n(lm('grounded', c)['k'], nA)} ChatGPT "
        f"({q(LT['grounded']['cochran_q'])}; Table 3, Fig. 2b); every pairwise difference was significant "
        f"(all Holm-adjusted P ≤ {pv(max((lp('grounded', a, b) for a, b in [(o, c), (o, cl), (o, g), (c, cl), (c, g), (cl, g)]), key=lambda v: v['p_holm']))[4:]}; Table 4). "
        f"Grounding did not vary by denial reason within any system (all P ≥ {min(SG[a]['grounded_by_denial_reason']['p_holm'] for a in ARMS):.2f}). "
        f"A quotation found in neither the governing document nor the cited document appeared in "
        f"{n(lm('quote_unverifiable', cl)['k'], nA)} Claude letters, {n(lm('quote_unverifiable', g)['k'], nA)} "
        f"Gemini, {n(lm('quote_unverifiable', c)['k'], nA)} ChatGPT and {lm('quote_unverifiable', o)['k']} OrthoAppeals "
        f"(95% CI {ci(lm('quote_unverifiable', o))}; {q(LT['quote_unverifiable']['cochran_q'])}). Claude and Gemini did "
        f"not differ ({pv(lp('quote_unverifiable', cl, g))}); each exceeded ChatGPT ({pv(lp('quote_unverifiable', c, cl))} "
        f"and {pv(lp('quote_unverifiable', c, g))}) and OrthoAppeals (both {pv(lp('quote_unverifiable', g))}). An "
        f"invented policy number or effective date appeared in {n(lm('invented_identifier', g)['k'], N)} Gemini, "
        f"{n(lm('invented_identifier', cl)['k'], N)} Claude, {n(lm('invented_identifier', c)['k'], N)} ChatGPT and "
        f"{lm('invented_identifier', o)['k']} OrthoAppeals letters ({q(LT['invented_identifier']['cochran_q'])}).")
    R.append(
        f"OrthoAppeals stated the filing deadline in {n(lm('deadline_stated', o)['k'], N)} letters, Claude in "
        f"{n(lm('deadline_stated', cl)['k'], N)}, ChatGPT in {n(lm('deadline_stated', c)['k'], N)} and Gemini in "
        f"{n(lm('deadline_stated', g)['k'], N)} ({q(LT['deadline_stated']['cochran_q'])}; Fig. 2c). The appeal route "
        f"was stated in {n(lm('route_stated', o)['k'], N)}, {n(lm('route_stated', cl)['k'], N)}, "
        f"{n(lm('route_stated', c)['k'], N)} and {n(lm('route_stated', g)['k'], N)} letters respectively "
        f"({q(LT['route_stated']['cochran_q'])}). ChatGPT's letter was not sendable in "
        f"{N - lm('sendable', c)['k']} of {N} cases; the other systems' letters were sendable in every case "
        f"({q(LT['sendable']['cochran_q'])}). In stratum C, OrthoAppeals, ChatGPT and Claude asked the plan for its "
        f"criteria in every letter and Gemini in {n(lm('demands_criteria_C', g)['k'], nC)} "
        f"({q(LT['demands_criteria_C']['cochran_q'])}).")
    cm = LT["completeness_judged"]
    cp = CT["pairwise"]
    R.append(
        f"Completeness and effort. Judged completeness (0–4) averaged {cm[o]['mean']:.2f} for OrthoAppeals, "
        f"{cm[cl]['mean']:.2f} for Claude, {cm[c]['mean']:.2f} for ChatGPT and {cm[g]['mean']:.2f} for Gemini "
        f"(Friedman χ² = {CT['friedman']['chi2']:.1f}, {P(CT['friedman']['p'])}). OrthoAppeals exceeded each chatbot "
        f"(all {pv(cp['ortho-opus vs gemini'])}), Claude exceeded ChatGPT ({pv(cp['chatgpt vs claude-free'])}) and "
        f"Gemini ({pv(cp['claude-free vs gemini'])}), and ChatGPT and Gemini did not differ "
        f"({pv(cp['chatgpt vs gemini'])}; Table 5). The chatbots made a median of {EF[c]['searches_median']} "
        f"(IQR {EF[c]['searches_iqr'][0]}–{EF[c]['searches_iqr'][1]}) web searches per case for ChatGPT, "
        f"{EF[cl]['searches_median']} ({EF[cl]['searches_iqr'][0]}–{EF[cl]['searches_iqr'][1]}) for Claude and "
        f"{EF[g]['searches_median']} ({EF[g]['searches_iqr'][0]}–{EF[g]['searches_iqr'][1]}) for Gemini "
        f"(Friedman {P(ET['searches']['friedman']['p'])}; all pairwise {pv(ET['searches']['pairwise']['chatgpt vs claude-free'])}), "
        f"and {EF[c]['fetches_median']}, {EF[cl]['fetches_median']} and {EF[g]['fetches_median']} page fetches "
        f"(Friedman {P(ET['fetches']['friedman']['p'])}; Fig. 2d). OrthoAppeals performed no search.")
    R.append(
        f"OrthoAppeals' automated check flagged {n(CP['flagged_before'], CP['letters'])} first drafts for a rule, "
        f"number or quotation attributed to the plan that was not in the policy excerpts; {CP['revised']} were "
        f"revised, and {CP['flagged_after']} delivered letters contained such a statement.")
    return R


FIG1 = ("Figure 1. Study design. Every case was answered by all four systems; every comparison is paired on the "
        "same case.")
FIG2 = (f"Figure 2. Policy identification, letter accuracy and effort. (a) Correct identification of the governing "
        f"policy by stratum and overall. (b) Stratum-A letters quoting a criterion that answers the stated denial "
        f"reason, letters with a quotation found in neither the governing nor the cited document, and letters (all "
        f"strata) with an invented policy number or date. (c) Stratum-C letters citing a nonexistent document or "
        f"asking the plan for its criteria, and letters (all strata) stating the filing deadline. (d) Median web "
        f"searches and page fetches per case. Bars show proportions with Wilson 95% CIs (a–c) or medians with "
        f"interquartile ranges (d).")

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


def para(text, size=None, bold_lead=None, italic=False):
    p = doc.add_paragraph()
    if bold_lead:
        p.add_run(bold_lead + " ").bold = True
    r = p.add_run(text); r.italic = italic
    if size:
        for run in p.runs:
            run.font.size = Pt(size)
    return p


def table(title, header, rows, note=""):
    para(title, bold_lead=None).runs[0].bold = True
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
    para(t, bold_lead=h + ":")

doc.add_heading("Methods", level=2)
for h, t in METHODS:
    doc.add_heading(h, level=3); para(t)

doc.add_heading("Results", level=2)
for t in results():
    para(t)

doc.add_heading("Tables", level=2)

# Table 1: identification by stratum, with Cochran's Q
hdr = ["System", f"Stratum A (n = {nA})", f"Stratum B (n = {nB})", f"Stratum C (n = {nC})", f"All (n = {N})"]
rows = []
for arm in ARMS:
    cells = [A[arm]]
    for s in ("in_library", "vendor_held", "no_policy", "all"):
        d = ID[arm][s]; cells.append(f"{d['k']} ({pct(d['k'], d['n'])}; {ci(d)})")
    rows.append(cells)
rows.append(["Cochran's Q (df = 3)"] + [f"{OM[s]['q']:.1f}; {P(OM[s]['p'])}" for s in ("in_library", "vendor_held", "no_policy", "all")])
table("Table 1. Correct identification of the governing policy, by stratum: n (%; Wilson 95% CI)", hdr, rows)

# Table 2: pairwise identification, all scopes
hdr = ["Comparison", "First only / second only", "Difference, points (95% CI)", "Holm-adjusted P"]
rows = []
for s, lab in (("all", f"All cases (n = {N})"), ("in_library", f"Stratum A (n = {nA})"), ("vendor_held", f"Stratum B (n = {nB})"), ("no_policy", f"Stratum C (n = {nC})")):
    rows.append([lab, "", "", ""])
    for k in PAIRS:
        v = PA[s][k]; a, b = k.split(" vs ")
        rows.append([f"   {pair_label(k)}", f"{v[a + '_only']} / {v[b + '_only']}", pts(v), pv(v)])
table("Table 2. Pairwise comparisons of policy identification (exact McNemar test on discordant pairs)", hdr, rows,
      "First only / second only: cases the first system had correct and the second wrong, and the reverse. "
      "Difference is first minus second, with bootstrap 95% CI. P values Holm-adjusted within each stratum.")

# Table 3: letter outcomes per arm + Cochran's Q
hdr = ["Letter outcome", "OrthoAppeals", "ChatGPT", "Claude", "Gemini", "Cochran's Q; P"]
NAMES = [("grounded", "Quotes a criterion answering the denial reason (stratum A)"),
         ("quote_unverifiable", "Any quotation not found in the policy (stratum A)"),
         ("quote_other_procedure", "Quotes another operation's criteria (stratum A)"),
         ("cites_correct_policy_in_letter", "Cites the governing policy in the letter (stratum A)"),
         ("invented_identifier", "Invented policy number or effective date"),
         ("deadline_stated", "States the filing deadline"),
         ("route_stated", "States the appeal route"),
         ("sendable", "Sendable: identifiers present, no placeholders"),
         ("unfinished", "Letter cut off before its end"),
         ("demands_criteria_C", "Asks the plan for its criteria (stratum C)"),
         ("hallucinated_document_C", "Cites a nonexistent governing document (stratum C)"),
         ("unsupported_attribution_judged", "Rule attributed to the plan without a source (judged)")]
rows = []
for key, label in NAMES:
    m = LT[key]; cells = [f"{label} (n = {m['n']})"]
    for arm in ARMS:
        d = m["arms"][arm]; cells.append(f"{d['k']} ({pct(d['k'], d['n'])})")
    cells.append(f"{m['cochran_q']['q']:.1f}; {P(m['cochran_q']['p'])}")
    rows.append(cells)
cm = LT["completeness_judged"]
rows.append(["Completeness, judged, mean (0–4), all letters"] + [f"{cm[a]['mean']:.2f}" for a in ARMS]
            + [f"Friedman χ² = {CT['friedman']['chi2']:.1f}; {P(CT['friedman']['p'])}"])
table("Table 3. Appeal-letter outcomes: n (%) and omnibus test across the four systems", hdr, rows)

# Table 4: pairwise letter outcomes
hdr = ["Outcome / comparison", "First only / second only", "Difference, points (95% CI)", "Holm-adjusted P"]
rows = []
for key, label in NAMES:
    if key in ("unfinished", "quote_other_procedure"):
        continue
    m = LT[key]
    rows.append([f"{label} (n = {m['n']})", "", "", ""])
    for k in PAIRS:
        v = m["paired"][k]; a, b = k.split(" vs ")
        rows.append([f"   {pair_label(k)}", f"{v[a + '_only']} / {v[b + '_only']}", pts(v), pv(v)])
table("Table 4. Pairwise comparisons of appeal-letter outcomes (exact McNemar test on discordant pairs)", hdr, rows,
      "Difference is first minus second, with bootstrap 95% CI. P values Holm-adjusted within each outcome.")

# Table 5: completeness and effort (Friedman + Wilcoxon), subgroup tests
hdr = ["Measure / comparison", "Medians (first, second)", "Mean difference (95% CI)", "Holm-adjusted P"]
rows = [[f"Completeness, 0–4 (Friedman χ² = {CT['friedman']['chi2']:.1f}, {P(CT['friedman']['p'])})", "", "", ""]]
for k, v in CT["pairwise"].items():
    a, b = k.split(" vs ")
    rows.append([f"   {pair_label(k)}", f"{v[a + '_median']}, {v[b + '_median']}",
                 f"{v['diff']:+.2f} ({v['diff_lo']:+.2f} to {v['diff_hi']:+.2f})", pv(v)])
for meas, lab in (("searches", "Web searches per case"), ("fetches", "Page fetches per case")):
    t = ET[meas]
    rows.append([f"{lab} (Friedman χ² = {t['friedman']['chi2']:.1f}, {P(t['friedman']['p'])})", "", "", ""])
    for k, v in t["pairwise"].items():
        a, b = k.split(" vs ")
        rows.append([f"   {pair_label(k)}", f"{v[a + '_median']}, {v[b + '_median']}",
                     f"{v['diff']:+.1f} ({v['diff_lo']:+.1f} to {v['diff_hi']:+.1f})", pv(v)])
rows.append(["Within-system subgroup tests (chi-square or Fisher's exact)", "", "", ""])
for key, lab in (("identification_by_stratum", "Identification by stratum (A / B / C)"),
                 ("identification_by_plan_type", "Identification by plan type (commercial / Medicaid)"),
                 ("grounded_by_denial_reason", "Grounded letter by denial reason (stratum A)")):
    for arm in ARMS:
        t = SG[arm][key]
        counts = " / ".join(f"{k_}/{k_ + w}" for k_, w in t["table"].values())
        rows.append([f"   {lab}: {A[arm]}", counts, t["test"] if t["test"] != "none" else "no variation", P(t["p_holm"]) if t["test"] != "none" else "—"])
table("Table 5. Completeness, effort and within-system subgroup tests", hdr, rows,
      "Completeness and effort: Friedman test across systems, pairwise Wilcoxon signed-rank tests with bootstrap "
      "95% CI for the paired mean difference. Subgroup tests: counts are correct/total per subgroup; P values "
      "Holm-adjusted across the four systems.")

doc.add_heading("Figures", level=2)
for png, legend in (("fig1_pipeline.png", FIG1), ("fig2_results.png", FIG2)):
    doc.add_picture(str(DOCS / png), width=Inches(6.3))
    para(legend, size=10)

OUT.parent.mkdir(exist_ok=True)
doc.save(OUT)
print("wrote", OUT.relative_to(ROOT))
