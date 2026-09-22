#!/usr/bin/env python3
"""Figures for the paper, from study/stats.json. Static, journal-style.

  Fig. 1  evaluation pipeline (schematic)
  Fig. 2  results: a policy identification by stratum; b letter grounding and
          unverifiable quotation (stratum A); c stratum-C behaviour; d effort

  python3 scripts/study/figures.py  ->  docs/fig1_pipeline.png, docs/fig2_results.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
st = json.loads((ROOT / "study" / "stats.json").read_text())
OUT = ROOT / "docs"

# Fixed categorical order and hues (validated palette; direct labels on every bar).
ARMS = ["ortho-opus", "chatgpt", "claude-free", "gemini"]
LABEL = {"ortho-opus": "OrthoAppeals", "chatgpt": "ChatGPT\n(GPT-5.6)", "claude-free": "Claude\n(Sonnet 5)",
         "gemini": "Gemini\n(3.5 Flash)"}
COLOR = {"ortho-opus": "#2a78d6", "chatgpt": "#eb6834", "claude-free": "#1baf7a", "gemini": "#eda100"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": INK2,
                     "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
                     "axes.spines.top": False, "axes.spines.right": False})


def bars(ax, groups, series, ylabel, ylim=(0, 100), pct=True, title=""):
    """groups: list of (label, {arm: (value, lo, hi)}); series: arms to draw.

    Value labels sit above the upper CI cap; a label that would collide with an
    already-placed neighbour is lifted so every number stays legible."""
    n_g, n_s = len(groups), len(series)
    w = 0.8 / n_s
    placed = []  # (x, y_label) in data units
    step = 7 if pct else 6
    for j, arm in enumerate(series):
        xs, ys, los, his = [], [], [], []
        for i, (_, d) in enumerate(groups):
            if arm not in d:
                continue
            v, lo, hi = d[arm]
            x = i + (j - (n_s - 1) / 2) * w
            xs.append(x); ys.append(v); los.append(max(0.0, v - lo)); his.append(max(0.0, hi - v))
        ax.bar(xs, ys, width=w * 0.92, color=COLOR[arm], label=LABEL[arm].replace("\n", " "),
               linewidth=0, zorder=3)
        ax.errorbar(xs, ys, yerr=[los, his], fmt="none", ecolor=INK2, elinewidth=0.8, capsize=2, zorder=4)
        for x, y, hi_ in zip(xs, ys, his):
            yl = y + hi_ + (1.5 if pct else 1.0)
            for _ in range(4):
                if any(abs(px - x) < 1.6 * w and abs(py - yl) < step * 0.9 for px, py in placed):
                    yl += step
                else:
                    break
            placed.append((x, yl))
            ax.text(x, yl, f"{y:.0f}", ha="center", va="bottom", fontsize=5.6, color=INK, zorder=5)
    ax.set_xticks(range(n_g)); ax.set_xticklabels([g for g, _ in groups], fontsize=6.8)
    ax.tick_params(axis="x", length=0)
    ax.set_ylim(*ylim); ax.set_ylabel(ylabel, fontsize=7.5); ax.yaxis.grid(True, color=GRID, linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, loc="left", fontsize=8.5, fontweight="bold", color=INK)


def wil(d):
    return (100 * d["p"], 100 * d["lo"], 100 * d["hi"])


def fig2():
    ID, LT, EF = st["identification"], st["letters"], st["effort"]
    T1 = st["table1"]["strata"]
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 6.2), dpi=300)
    (a, b), (c, d) = axes

    groups = [(f"A: criteria\npublished\n(n = {T1['in_library']})", {arm: wil(ID[arm]["in_library"]) for arm in ARMS}),
              (f"B: criteria\nvendor-held\n(n = {T1['vendor_held']})", {arm: wil(ID[arm]["vendor_held"]) for arm in ARMS}),
              (f"C: no policy\npublished\n(n = {T1['no_policy']})", {arm: wil(ID[arm]["no_policy"]) for arm in ARMS}),
              (f"All\n(n = {st['n_cases']})", {arm: wil(ID[arm]["all"]) for arm in ARMS})]
    bars(a, groups, ARMS, "Cases (%)", ylim=(0, 118), title="a  Governing policy identified (%)")

    nA = LT["grounded"]["n"]
    groups = [(f"Quotes an\non-point criterion\n(n = {nA})", {arm: wil(LT["grounded"]["arms"][arm]) for arm in ARMS}),
              (f"Any quotation\nnot in the policy\n(n = {nA})", {arm: wil(LT["quote_unverifiable"]["arms"][arm]) for arm in ARMS}),
              (f"Invented policy\nnumber or date\n(n = {LT['invented_identifier']['n']})", {arm: wil(LT["invented_identifier"]["arms"][arm]) for arm in ARMS})]
    bars(b, groups, ARMS, "Letters (%)", ylim=(0, 118), title="b  Appeal letters (%)")

    nC = LT["hallucinated_document_C"]["n"]
    groups = [(f"Cited a document\nthat does not exist\n(n = {nC})", {arm: wil(LT["hallucinated_document_C"]["arms"][arm]) for arm in ARMS}),
              (f"Asked the plan\nfor its criteria\n(n = {nC})", {arm: wil(LT["demands_criteria_C"]["arms"][arm]) for arm in ARMS}),
              (f"Stated the filing\ndeadline (all strata)\n(n = {LT['deadline_stated']['n']})", {arm: wil(LT["deadline_stated"]["arms"][arm]) for arm in ARMS})]
    bars(c, groups, ARMS, "Letters (%)", ylim=(0, 118), title="c  No-policy cases and the deadline (%)")

    # d: effort, median with IQR
    groups = [("Web searches\nper case", {arm: (EF[arm]["searches_median"], EF[arm]["searches_iqr"][0], EF[arm]["searches_iqr"][1]) for arm in ARMS[1:]}),
              ("Page fetches\nper case", {arm: (EF[arm]["fetches_median"], EF[arm]["fetches_iqr"][0], EF[arm]["fetches_iqr"][1]) for arm in ARMS[1:]})]
    bars(d, groups, ARMS[1:], "Median per case (IQR)", ylim=(0, 90), pct=False, title="d  Search effort (OrthoAppeals: 0, directory lookup)")

    handles = [plt.Rectangle((0, 0), 1, 1, color=COLOR[arm]) for arm in ARMS]
    fig.legend(handles, [LABEL[arm].replace("\n", " ") for arm in ARMS], loc="lower center", ncol=4,
               frameon=False, fontsize=8, bbox_to_anchor=(0.5, -0.01))
    fig.tight_layout(rect=(0, 0.04, 1, 1), h_pad=2.0, w_pad=2.0)
    fig.savefig(OUT / "fig2_results.png", bbox_inches="tight")
    plt.close(fig)


def box(ax, x, y, w, h, text, fc="#f4f4f2", ec=INK2, fs=7.5, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.02",
                                fc=fc, ec=ec, lw=0.8))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=INK,
            fontweight="bold" if bold else "normal", wrap=True)


def arrow(ax, x0, y0, x1, y1):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops=dict(arrowstyle="->", color=INK2, lw=0.9))


def fig1():
    T1 = st["table1"]
    fig = plt.figure(figsize=(7.2, 5.0), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 10); ax.set_ylim(0, 7); ax.axis("off")
    BLUE, ORANGE, GREEN, GREY = "#2a78d6", "#eb6834", "#1baf7a", INK2
    # row 1: cases
    box(ax, 0.3, 5.85, 9.4, 0.95,
        f"{st['n_cases']} simulated orthopaedic surgery denials\n"
        f"50 states + DC · {T1['insurers']} insurers · 14 operations · 4 denial reasons · each with a denial notice and a clinical summary\n"
        f"A: criteria published (n = {T1['strata']['in_library']})      B: document public, criteria vendor-held (n = {T1['strata']['vendor_held']})      "
        f"C: no policy published (n = {T1['strata']['no_policy']})",
        fc="#eef3fb", ec=BLUE, fs=6.6)
    # row 2: systems
    box(ax, 0.3, 4.35, 4.5, 1.1,
        "OrthoAppeals\ndirectory lookup -> reviewed criteria for the operation\n-> Claude Opus 5 writer -> code and model checks -> one revision",
        fc="#eef3fb", ec=BLUE, fs=6.4)
    box(ax, 5.2, 4.35, 4.5, 1.1,
        "Free chatbots (API, identical tools and instructions)\nChatGPT (GPT-5.6) · Claude (Sonnet 5) · Gemini (3.5 Flash)\nweb search + page fetch, 120-call budget, then the letter",
        fc="#fbf1ec", ec=ORANGE, fs=6.4)
    arrow(ax, 2.55, 5.85, 2.55, 5.47); arrow(ax, 7.45, 5.85, 7.45, 5.47)
    # row 3: per-case outputs (shared)
    box(ax, 0.3, 3.35, 9.4, 0.6,
        "Per case, every system returns (1) the governing policy it cites and (2) a complete appeal letter",
        fc="#ffffff", ec=GREY, fs=6.6)
    arrow(ax, 2.55, 4.35, 2.55, 3.97); arrow(ax, 7.45, 4.35, 7.45, 3.97)
    # row 4: scoring
    box(ax, 0.3, 1.95, 4.5, 1.0,
        "Policy identification\ncited document vs reviewed answer key: exact URL,\nsame publisher's guideline (address + text), or accepted alternate",
        fc="#f4f4f2", ec=GREY, fs=6.4)
    box(ax, 5.2, 1.95, 4.5, 1.0,
        "Appeal letter, scored by code against the policy text and the notice\ngrounded · unverifiable quotation · invented identifier\ndeadline · route · sendable",
        fc="#f4f4f2", ec=GREY, fs=6.4)
    arrow(ax, 2.55, 3.35, 2.55, 2.97); arrow(ax, 7.45, 3.35, 7.45, 2.97)
    # row 5: answer key + statistics
    box(ax, 0.3, 0.55, 4.5, 1.0,
        "Answer key\nOrthoAppeals' directory, then every stratum-A document read in full;\nmodel-extracted criteria verified verbatim by code;\n17 entries corrected before final scoring",
        fc="#eefaf4", ec=GREEN, fs=6.2)
    box(ax, 5.2, 0.55, 4.5, 1.0,
        "Statistics and audit\nWilson 95% CI · exact McNemar on discordant pairs, Holm-Bonferroni\nbootstrap CI for paired differences · independent audit script\nre-derives every table from letters, transcripts and documents",
        fc="#eefaf4", ec=GREEN, fs=6.2)
    arrow(ax, 2.55, 1.95, 2.55, 1.57); arrow(ax, 7.45, 1.95, 7.45, 1.57)
    ax.text(0.3, 0.2, "Every case is answered by all four systems; every comparison is paired on the same case.",
            fontsize=6.6, color=INK2)
    fig.savefig(OUT / "fig1_pipeline.png")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    fig1(); fig2()
    print("wrote docs/fig1_pipeline.png docs/fig2_results.png")
    sys.exit(0)
