#!/usr/bin/env python3
"""Figures for the paper, from study/stats.json. Black and white, serif.

  Fig. 1  study design (schematic)
  Fig. 2  results: a policy identification by stratum; b letter grounding and
          unverifiable quotation (stratum A); c stratum-C behaviour and the
          deadline; d search effort

  python3 scripts/study/figures.py  ->  docs/fig1_pipeline.png, docs/fig2_results.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
st = json.loads((ROOT / "study" / "stats.json").read_text())
OUT = ROOT / "docs"

ARMS = ["ortho-opus", "chatgpt", "claude-free", "gemini"]
LABEL = {"ortho-opus": "OrthoAppeals", "chatgpt": "ChatGPT", "claude-free": "Claude", "gemini": "Gemini"}
# Fig. 2: colour, fixed order (palette validated for colour-vision deficiency; every bar is also labelled).
FILL = {"ortho-opus": "#2a78d6", "chatgpt": "#eb6834", "claude-free": "#1baf7a", "gemini": "#eda100"}
plt.rcParams.update({"font.family": "serif",
                     "font.serif": ["Times New Roman", "Times", "Liberation Serif", "Nimbus Roman", "DejaVu Serif"],
                     "font.size": 8, "axes.edgecolor": "black", "axes.labelcolor": "black",
                     "xtick.color": "black", "ytick.color": "black", "text.color": "black",
                     "axes.spines.top": False, "axes.spines.right": False})


def bars(ax, groups, series, ylabel, ylim=(0, 100), pct=True, title=""):
    """groups: list of (label, {arm: (value, lo, hi)}); series: arms to draw."""
    n_g, n_s = len(groups), len(series)
    w = 0.8 / n_s
    placed = []
    step = 7 if pct else 6
    for j, arm in enumerate(series):
        xs, ys, los, his, lab = [], [], [], [], []
        for i, (_, d) in enumerate(groups):
            if arm not in d:
                continue
            v, lo, hi = d[arm][:3]
            x = i + (j - (n_s - 1) / 2) * w
            xs.append(x); ys.append(v); los.append(max(0.0, v - lo)); his.append(max(0.0, hi - v))
            lab.append(d[arm][3] if len(d[arm]) > 3 else f"{v:.0f}")
        ax.bar(xs, ys, width=w * 0.92, color=FILL[arm], edgecolor="black", linewidth=0.6,
               label=LABEL[arm], zorder=3)
        ax.errorbar(xs, ys, yerr=[los, his], fmt="none", ecolor="black", elinewidth=0.7, capsize=2, zorder=4)
        for x, y, hi_, t in zip(xs, ys, his, lab):
            yl = y + hi_ + (1.5 if pct else 1.0)
            for _ in range(4):
                if any(abs(px - x) < 1.6 * w and abs(py - yl) < step * 0.9 for px, py in placed):
                    yl += step
                else:
                    break
            placed.append((x, yl))
            ax.text(x, yl, t, ha="center", va="bottom", fontsize=6.5, zorder=5)
    ax.set_xticks(range(n_g)); ax.set_xticklabels([g for g, _ in groups], fontsize=7.5)
    ax.tick_params(axis="x", length=0)
    ax.set_ylim(*ylim); ax.set_ylabel(ylabel, fontsize=8)
    ax.yaxis.grid(True, color="#d9d9d9", linewidth=0.5, zorder=0); ax.set_axisbelow(True)
    if title:
        ax.set_title(title, loc="left", fontsize=9, fontweight="bold")


def wil(d):
    return (100 * d["p"], 100 * d["lo"], 100 * d["hi"])


def fig2():
    ID, LT, EF = st["identification"], st["letters"], st["effort"]
    T1 = st["table1"]["strata"]
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 6.4), dpi=300)
    (a, b), (c, d) = axes

    groups = [(f"A, criteria\npublished\n(n = {T1['in_library']})", {arm: wil(ID[arm]["in_library"]) for arm in ARMS}),
              (f"B, criteria\nvendor-held\n(n = {T1['vendor_held']})", {arm: wil(ID[arm]["vendor_held"]) for arm in ARMS}),
              (f"C, no policy\npublished\n(n = {T1['no_policy']})", {arm: wil(ID[arm]["no_policy"]) for arm in ARMS}),
              (f"All\n(n = {st['n_cases']})", {arm: wil(ID[arm]["all"]) for arm in ARMS})]
    bars(a, groups, ARMS, "Cases (%)", ylim=(0, 118), title="a  Governing policy identified")

    nA = LT["grounded"]["n"]
    groups = [(f"Quotes an\non-point criterion\n(n = {nA})", {arm: wil(LT["grounded"]["arms"][arm]) for arm in ARMS}),
              (f"Hallucinated\nquotation\n(n = {nA})", {arm: wil(LT["quote_unverifiable"]["arms"][arm]) for arm in ARMS}),
              (f"Hallucinated policy\nnumber or date\n(n = {LT['invented_identifier']['n']})", {arm: wil(LT["invented_identifier"]["arms"][arm]) for arm in ARMS})]
    bars(b, groups, ARMS, "Letters (%)", ylim=(0, 118), title="b  Appeal letters")

    nC = LT["hallucinated_document_C"]["n"]
    groups = [(f"Cited a policy\nthat does not exist\n(n = {nC})", {arm: wil(LT["hallucinated_document_C"]["arms"][arm]) for arm in ARMS}),
              (f"Asked the plan\nfor its criteria\n(n = {nC})", {arm: wil(LT["demands_criteria_C"]["arms"][arm]) for arm in ARMS}),
              (f"Stated the filing\ndeadline (all strata)\n(n = {LT['deadline_stated']['n']})", {arm: wil(LT["deadline_stated"]["arms"][arm]) for arm in ARMS})]
    bars(c, groups, ARMS, "Letters (%)", ylim=(0, 118), title="c  No-policy cases and the deadline")

    # d: effort, median with IQR; OrthoAppeals is 0 by design (footnote)
    def eff(arm, k):
        if arm == "ortho-opus":
            return (0, 0, 0, "0*")
        return (EF[arm][f"{k}_median"], EF[arm][f"{k}_iqr"][0], EF[arm][f"{k}_iqr"][1])
    groups = [("Web searches\nper case", {arm: eff(arm, "searches") for arm in ARMS}),
              ("Page visits\nper case", {arm: eff(arm, "fetches") for arm in ARMS})]
    bars(d, groups, ARMS, "Median per case (IQR)", ylim=(0, 90), pct=False, title="d  Search effort")

    handles = [Rectangle((0, 0), 1, 1, facecolor=FILL[arm], edgecolor="black", linewidth=0.6) for arm in ARMS]
    fig.legend(handles, [LABEL[arm] for arm in ARMS], loc="lower center", ncol=4, frameon=False,
               fontsize=8, bbox_to_anchor=(0.5, 0.02))
    fig.text(0.02, 0.0, "*OrthoAppeals retrieves the policy from its directory and performs no web search.",
             fontsize=7, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.05, 1, 1), h_pad=2.0, w_pad=2.0)
    fig.savefig(OUT / "fig2_results.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def box(ax, x, y, w, h, title, body="", fs=7.5):
    ax.add_patch(Rectangle((x, y), w, h, fc="white", ec="black", lw=0.8))
    if body:
        ax.text(x + w / 2, y + h - 0.22, title, ha="center", va="center", fontsize=fs + 0.5, fontweight="bold")
        ax.text(x + w / 2, y + (h - 0.3) / 2, body, ha="center", va="center", fontsize=fs, linespacing=1.3)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center", fontsize=fs + 0.5, fontweight="bold")


def arrow(ax, x0, y0, x1, y1):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="-|>", color="black", lw=0.8, shrinkA=0, shrinkB=0))


def fig1():
    T1 = st["table1"]
    fig = plt.figure(figsize=(6.5, 4.6), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 10); ax.set_ylim(0, 7.2); ax.axis("off")
    L, R, W = 0.4, 5.3, 4.3          # left column x, right column x, column width
    FULL = R + W - L
    # 1 cases
    box(ax, L, 6.0, FULL, 1.0, f"{st['n_cases']} simulated denials",
        f"{T1['states']} jurisdictions  ·  {T1['insurers']} insurers  ·  14 operations\n"
        f"Stratum A, criteria published (n = {T1['strata']['in_library']})  ·  "
        f"Stratum B, criteria vendor-held (n = {T1['strata']['vendor_held']})  ·  "
        f"Stratum C, no policy (n = {T1['strata']['no_policy']})")
    # 2 systems
    box(ax, L, 4.35, W, 1.15, "OrthoAppeals",
        "Directory lookup → policy criteria\n→ drafting model → automated checks")
    box(ax, R, 4.35, W, 1.15, "ChatGPT · Claude · Gemini",
        "Web search and page fetch\nIdentical instructions and tool budget")
    arrow(ax, L + W / 2, 6.0, L + W / 2, 5.5); arrow(ax, R + W / 2, 6.0, R + W / 2, 5.5)
    # 3 outputs
    box(ax, L, 3.3, FULL, 0.6, "Per case: the cited governing policy and a complete appeal letter")
    arrow(ax, L + W / 2, 4.35, L + W / 2, 3.9); arrow(ax, R + W / 2, 4.35, R + W / 2, 3.9)
    # 4 scoring
    box(ax, L, 1.7, W, 1.15, "Policy identification",
        "Cited document compared with the\nreviewed answer key")
    box(ax, R, 1.7, W, 1.15, "Appeal letter",
        "Scored by code against the policy text\nand the denial notice")
    arrow(ax, L + W / 2, 3.3, L + W / 2, 2.85); arrow(ax, R + W / 2, 3.3, R + W / 2, 2.85)
    # 5 analysis
    box(ax, L, 0.4, FULL, 0.85, "Paired analysis on the same cases",
        "Cochran's Q and exact McNemar tests  ·  Friedman and Wilcoxon signed-rank tests  ·  Holm adjustment")
    arrow(ax, L + W / 2, 1.7, L + W / 2, 1.25); arrow(ax, R + W / 2, 1.7, R + W / 2, 1.25)
    fig.savefig(OUT / "fig1_pipeline.png", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    fig1(); fig2()
    print("wrote docs/fig1_pipeline.png docs/fig2_results.png")
    sys.exit(0)
