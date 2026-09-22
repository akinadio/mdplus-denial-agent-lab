#!/usr/bin/env python3
"""Every number in the paper, computed from the study files.

Reads study/cases.json, gold.json, unblinding.json, scores.json,
letter_grades.json and the per-run tool ledgers; writes study/stats.json and
prints the tables. No model calls, no network. Re-run it and the paper's
numbers re-derive; change a grade and they change with it.

Statistics (pure Python, so the file runs anywhere):
  Wilson score interval           for every proportion
  exact McNemar test              paired comparisons on the same case
                                  (two-sided binomial test on the discordant pairs)
  bootstrap percentile interval   for paired differences in proportions (10,000)
"""
from __future__ import annotations

import collections
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S = ROOT / "study"
ARMS = ["ortho-opus", "chatgpt", "claude-free", "gemini"]
sys.path.insert(0, str(ROOT))
from scripts.study.equivalence import _family  # noqa: E402


def _docs_by_family(cases, gold):
    out = {}
    for c in cases:
        if cases[c]["stratum"] != "in_library":
            continue
        g = gold[c]
        fam = _family(g["policy_url"], g.get("policy_title", ""), "", g.get("vendor", "")) or "insurer's own"
        out.setdefault(fam, set()).add(g["policy_url"])
    return out
LABEL = {"ortho-opus": "OrthoAppeals", "chatgpt": "ChatGPT", "claude-free": "Claude", "gemini": "Gemini"}
STRATA = [("in_library", "A: criteria published"), ("vendor_held", "B: criteria held by a vendor"),
          ("no_policy", "C: no policy published")]


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact P for discordant counts b (first only) and c (second only)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def cochran_q(rows: list[list[int]]) -> dict:
    """Cochran's Q across k related binary outcomes (one row per case)."""
    from scipy.stats import chi2
    k = len(rows[0]) if rows else 0
    n = len(rows)
    col = [sum(r[j] for r in rows) for j in range(k)]
    T = sum(col)
    denom = k * T - sum(sum(r) ** 2 for r in rows)
    if n == 0 or denom == 0:
        return {"n": n, "k": k, "q": 0.0, "df": k - 1, "p": 1.0}
    q = (k - 1) * (k * sum(c * c for c in col) - T * T) / denom
    return {"n": n, "k": k, "q": q, "df": k - 1, "p": float(chi2.sf(q, k - 1))}


def friedman(cols: dict) -> dict:
    """Friedman test across related samples; cols = {arm: [values per case]}."""
    from scipy.stats import friedmanchisquare
    arms = list(cols)
    try:
        st_, p_ = friedmanchisquare(*[cols[a] for a in arms])
    except ValueError:
        st_, p_ = 0.0, 1.0
    return {"n": len(cols[arms[0]]), "k": len(arms), "chi2": float(st_), "df": len(arms) - 1, "p": float(p_)}


def wilcoxon_pairs(cols: dict, reps: int = 10000) -> dict:
    """Pairwise Wilcoxon signed-rank tests with Holm adjustment; bootstrap CI for the paired mean difference."""
    from scipy.stats import wilcoxon
    arms = list(cols)
    out = {}
    for i, a in enumerate(arms):
        for b in arms[i + 1:]:
            x, y = cols[a], cols[b]
            d = [u - v for u, v in zip(x, y)]
            if all(v == 0 for v in d):
                p_ = 1.0
            else:
                p_ = float(wilcoxon(x, y, zero_method="wilcox").pvalue)
            m, lo, hi = boot_diff(x, y, reps=reps)
            xs, ys = sorted(x), sorted(y)
            out[f"{a} vs {b}"] = {"n": len(x), "p": p_, "diff": m, "diff_lo": lo, "diff_hi": hi,
                                 f"{a}_median": xs[len(xs) // 2], f"{b}_median": ys[len(ys) // 2]}
    _holm(out)
    return out


def _holm(d: dict):
    items = sorted(d.items(), key=lambda kv: kv[1]["p"])
    m = len(items)
    running = 0.0
    for i, (k, v) in enumerate(items):
        running = max(running, min(1.0, (m - i) * v["p"]))
        v["p_holm"] = running


def contingency(table: list[list[int]]) -> dict:
    """Chi-square test of independence (Fisher's exact test for a 2x2)."""
    from scipy.stats import chi2_contingency, fisher_exact
    rows = [r for r in table if sum(r) > 0]
    cols_keep = [j for j in range(len(rows[0])) if sum(r[j] for r in rows) > 0] if rows else []
    rows = [[r[j] for j in cols_keep] for r in rows]
    if len(rows) < 2 or len(rows[0]) < 2:
        return {"test": "none", "p": 1.0}
    if len(rows) == 2 and len(rows[0]) == 2:
        return {"test": "Fisher exact", "p": float(fisher_exact(rows)[1])}
    st_, p_, df, _ = chi2_contingency(rows)
    return {"test": "chi-square", "chi2": float(st_), "df": int(df), "p": float(p_)}


def boot_diff(a: list[int], b: list[int], reps: int = 10000, seed: int = 20260922):
    """Percentile CI for mean(a) - mean(b) over paired cases."""
    rng = random.Random(seed)
    n = len(a)
    if n == 0:
        return (0.0, 0.0, 0.0)
    diffs = []
    for _ in range(reps):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(a[i] - b[i] for i in idx) / n)
    diffs.sort()
    return (sum(a) / n - sum(b) / n, diffs[int(0.025 * reps)], diffs[int(0.975 * reps) - 1])


def fmt_p(p: float) -> str:
    if p < 0.001:
        return "P < .001"
    return f"P = {p:.3f}" if p < 0.01 else f"P = {p:.2f}"


def pct(k, n):
    return f"{k}/{n} ({100 * k / n:.0f}%)" if n else "—"


def main() -> int:
    cases = {c["case_id"]: c for c in json.loads((S / "cases.json").read_text())["cases"]}
    gold = {g["case_id"]: g for g in json.loads((S / "gold.json").read_text())["entries"]}
    key = json.loads((S / "unblinding.json").read_text())
    scores = json.loads((S / "scores.json").read_text())
    grades = json.loads((S / "letter_grades.json").read_text())

    # run id by (case, arm)
    rid = {(v["case_id"], v["system"]): r for r, v in key.items()}
    out = {"n_cases": len(cases), "arms": ARMS}

    # ---- Table 1 ------------------------------------------------------------
    t1 = {
        "strata": {s: sum(1 for c in cases.values() if c["stratum"] == s) for s, _ in STRATA},
        "states": len({c["state"] for c in cases.values()}),
        "insurers": len({c["payer"] for c in cases.values()}),
        "plan_type": dict(collections.Counter(c["plan_type"] for c in cases.values())),
        "denial_reason": dict(collections.Counter(c["denial_reason"] for c in cases.values())),
        "surgery": dict(collections.Counter(f"{c['surgery']} ({c['cpt']})" for c in cases.values())),
        "policy_documents_A": len({gold[c]["policy_url"] for c in cases if cases[c]["stratum"] == "in_library"}),
        # Publisher family of each stratum-A governing document, by the same rule the
        # scorer uses (URL, title and the directory's vendor note); "" = insurer's own.
        "publishers_A": dict(collections.Counter(
            _family(gold[c]["policy_url"], gold[c].get("policy_title", ""), "", gold[c].get("vendor", ""))
            or "insurer's own" for c in cases if cases[c]["stratum"] == "in_library")),
        "publisher_documents_A": {fam: len(urls) for fam, urls in sorted(_docs_by_family(cases, gold).items())},
    }
    out["table1"] = t1

    # ---- policy identification ---------------------------------------------
    ident = {}
    for arm in ARMS:
        ident[arm] = {}
        for s, _ in STRATA + [("all", "all")]:
            ids = [c for c in cases if s == "all" or cases[c]["stratum"] == s]
            vals = [int(bool(scores[rid[(c, arm)]]["correct"])) for c in ids]
            k, n = sum(vals), len(vals)
            p, lo, hi = wilson(k, n)
            outc = collections.Counter(scores[rid[(c, arm)]]["outcome"] for c in ids)
            ident[arm][s] = {"k": k, "n": n, "p": p, "lo": lo, "hi": hi, "outcomes": dict(outc)}
    out["identification"] = ident

    # paired comparisons
    def paired(metric, ids, a1, a2):
        v1 = [metric(c, a1) for c in ids]
        v2 = [metric(c, a2) for c in ids]
        b = sum(1 for x, y in zip(v1, v2) if x and not y)
        c_ = sum(1 for x, y in zip(v1, v2) if y and not x)
        d, lo, hi = boot_diff(v1, v2)
        return {"n": len(ids), f"{a1}_only": b, f"{a2}_only": c_, "p": mcnemar_exact(b, c_),
                "diff": d, "diff_lo": lo, "diff_hi": hi}

    corr = lambda c, a: int(bool(scores[rid[(c, a)]]["correct"]))  # noqa: E731
    cmp = {}
    for s, _ in STRATA + [("all", "all")]:
        ids = [c for c in cases if s == "all" or cases[c]["stratum"] == s]
        cmp[s] = {}
        for a in ARMS[1:]:
            cmp[s][f"ortho-opus vs {a}"] = paired(corr, ids, "ortho-opus", a)
        for i, a in enumerate(ARMS[1:]):
            for b in ARMS[2 + i:]:
                cmp[s][f"{a} vs {b}"] = paired(corr, ids, a, b)
    # Holm-Bonferroni within each family of comparisons (the six pairwise
    # tests on one stratum; the three chatbot-vs-OrthoAppeals tests on one
    # letter outcome), as in Vishwanath et al., Nat Med 2026.
    def holm(d: dict):
        items = sorted(d.items(), key=lambda kv: kv[1]["p"])
        m = len(items)
        running = 0.0
        for i, (k, v) in enumerate(items):
            adj = min(1.0, (m - i) * v["p"])
            running = max(running, adj)
            v["p_holm"] = running
    for s in cmp:
        holm(cmp[s])
    out["identification_paired"] = cmp
    out["identification_omnibus"] = {}
    for s, _ in STRATA + [("all", "all")]:
        ids = [c for c in cases if s == "all" or cases[c]["stratum"] == s]
        out["identification_omnibus"][s] = cochran_q([[corr(c, a) for a in ARMS] for c in ids])

    # ---- letters -------------------------------------------------------------
    def G(c, a):
        return grades.get(rid[(c, a)], {})

    letter_metrics = {
        # stratum A only
        "grounded": ("A", lambda c, a: int(bool(G(c, a).get("grounded_in_case")))),
        "quote_unverifiable": ("A", lambda c, a: int(bool(G(c, a).get("quote_not_in_policy")))),
        "quote_other_procedure": ("A", lambda c, a: int(bool(G(c, a).get("quotes_other_procedure")))),
        "cites_correct_policy_in_letter": ("A", lambda c, a: int(bool(G(c, a).get("cites_correct_policy")))),
        # all strata
        "sendable": ("all", lambda c, a: int(bool(G(c, a).get("sendable")))),
        "deadline_stated": ("all", lambda c, a: int(bool(G(c, a).get("deadline_correct")))),
        "route_stated": ("all", lambda c, a: int(bool(G(c, a).get("route_given")))),
        "invented_identifier": ("all", lambda c, a: int(bool(G(c, a).get("invented_identifier")))),
        "unfinished": ("all", lambda c, a: int(bool(G(c, a).get("unfinished")))),
        "unsupported_attribution_judged": ("all", lambda c, a: int(bool(G(c, a).get("unsupported_attribution")))),
        # stratum C
        "demands_criteria_C": ("C", lambda c, a: int(bool(G(c, a).get("demands_criteria")))),
        "hallucinated_document_C": ("C", lambda c, a: int(scores[rid[(c, a)]]["outcome"] == "hallucinated_document")),
    }
    stratum_of = {"A": "in_library", "B": "vendor_held", "C": "no_policy"}
    letters = {}
    for name, (scope, fn) in letter_metrics.items():
        ids = [c for c in cases if scope == "all" or cases[c]["stratum"] == stratum_of[scope]]
        letters[name] = {"scope": scope, "n": len(ids), "arms": {}, "paired": {}}
        for a in ARMS:
            vals = [fn(c, a) for c in ids]
            k = sum(vals)
            p, lo, hi = wilson(k, len(vals))
            letters[name]["arms"][a] = {"k": k, "n": len(vals), "p": p, "lo": lo, "hi": hi}
        for i, a in enumerate(ARMS):
            for b in ARMS[i + 1:]:
                letters[name]["paired"][f"{a} vs {b}"] = paired(fn, ids, a, b)
        holm(letters[name]["paired"])
        letters[name]["cochran_q"] = cochran_q([[fn(c, a) for a in ARMS] for c in ids])
    # completeness (0-4), judged
    comp = {}
    for a in ARMS:
        vals = [G(c, a).get("completeness") for c in cases if isinstance(G(c, a).get("completeness"), (int, float))]
        comp[a] = {"n": len(vals), "mean": sum(vals) / len(vals) if vals else None,
                   "dist": dict(collections.Counter(vals))}
    letters["completeness_judged"] = comp
    out["letters"] = letters

    # ---- OrthoAppeals' own correction pass -----------------------------------
    # "before" and "revised" are what the writer recorded at drafting time;
    # "after" is re-checked here with the current checker, so a later fix to
    # the checker (the 'three (3) months' case) is reflected.
    sys.path.insert(0, str(ROOT))
    from synthetic_harness.letter_checks import unsourced_requirements
    from synthetic_harness.quote_check import quoted_passages, in_text
    rev = collections.Counter()
    for c in cases:
        L = json.loads((S / "runs" / rid[(c, "ortho-opus")] / "letter.json").read_text())
        rev["letters"] += 1
        rev["flagged_before"] += int(bool(L.get("unsourced_requirements_before")))
        rev["revised"] += int(bool(L.get("revised_for_unsourced")))
        if L.get("unsourced_requirements_before") and not L.get("revised_for_unsourced"):
            rev["flagged_not_revised"] += 1   # revision request failed or was rejected (letter kept as drafted)
        ex = (L.get("evidence") or {}).get("quotes") or []
        facts = [cases[c]["letter_text"], cases[c]["chart_summary"]]
        after = unsourced_requirements(L["letter_markdown"], ex, facts)["count"]
        after += sum(1 for q in quoted_passages(L["letter_markdown"]) if not in_text(q, "\n".join(ex + facts)))
        rev["flagged_after"] += int(after > 0)
    out["ortho_correction_pass"] = dict(rev)

    # ---- effort ---------------------------------------------------------------
    eff = {}
    for a in ARMS[1:]:
        srch, fetch = [], []
        for c in cases:
            p = S / "runs" / rid[(c, a)] / "tools.jsonl"
            if not p.exists():
                continue
            n_s = n_f = 0
            for line in p.read_text().splitlines():
                try:
                    t = json.loads(line)
                except ValueError:
                    continue
                nm = t.get("action") or t.get("tool") or t.get("name") or ""
                n_s += nm == "web_search"
                n_f += nm == "http_fetch"
            srch.append(n_s)
            fetch.append(n_f)
        srch.sort(); fetch.sort()
        med = lambda xs: xs[len(xs) // 2] if xs else None  # noqa: E731
        iqr = lambda xs: (xs[len(xs) // 4], xs[3 * len(xs) // 4]) if xs else None  # noqa: E731
        eff[a] = {"n": len(srch), "searches_median": med(srch), "searches_iqr": iqr(srch),
                  "fetches_median": med(fetch), "fetches_iqr": iqr(fetch)}
    out["effort"] = eff

    # ---- ordinal and count outcomes: Friedman + pairwise Wilcoxon -------------
    ids_all = list(cases)
    comp_cols = {a: [G(c, a).get("completeness") if isinstance(G(c, a).get("completeness"), (int, float)) else 0
                     for c in ids_all] for a in ARMS}
    out["completeness_tests"] = {"friedman": friedman(comp_cols), "pairwise": wilcoxon_pairs(comp_cols)}
    eff_cols = {"searches": {}, "fetches": {}}
    for a in ARMS[1:]:
        for c in ids_all:
            p = S / "runs" / rid[(c, a)] / "tools.jsonl"
            n_s = n_f = 0
            if p.exists():
                for line in p.read_text().splitlines():
                    try:
                        t = json.loads(line)
                    except ValueError:
                        continue
                    nm = t.get("action") or t.get("tool") or t.get("name") or ""
                    n_s += nm == "web_search"; n_f += nm == "http_fetch"
            eff_cols["searches"].setdefault(a, []).append(n_s)
            eff_cols["fetches"].setdefault(a, []).append(n_f)
    out["effort_tests"] = {k: {"friedman": friedman(v), "pairwise": wilcoxon_pairs(v)} for k, v in eff_cols.items()}

    # ---- subgroup tests within each system ------------------------------------
    sub = {}
    strata_keys = [s for s, _ in STRATA]
    plan_types = sorted({cases[c]["plan_type"] for c in cases})
    reasons = sorted({cases[c]["denial_reason"] for c in cases})
    for a in ARMS:
        sub[a] = {}
        # identification by stratum (3 x 2)
        tab = [[sum(corr(c, a) for c in cases if cases[c]["stratum"] == s),
                sum(1 - corr(c, a) for c in cases if cases[c]["stratum"] == s)] for s in strata_keys]
        sub[a]["identification_by_stratum"] = dict(contingency(tab), table=dict(zip(strata_keys, tab)))
        # identification by plan type (2 x 2)
        tab = [[sum(corr(c, a) for c in cases if cases[c]["plan_type"] == t),
                sum(1 - corr(c, a) for c in cases if cases[c]["plan_type"] == t)] for t in plan_types]
        sub[a]["identification_by_plan_type"] = dict(contingency(tab), table=dict(zip(plan_types, tab)))
        # grounded letter by denial reason, stratum A (4 x 2)
        gA = letter_metrics["grounded"][1]
        idsA = [c for c in cases if cases[c]["stratum"] == "in_library"]
        tab = [[sum(gA(c, a) for c in idsA if cases[c]["denial_reason"] == r),
                sum(1 - gA(c, a) for c in idsA if cases[c]["denial_reason"] == r)] for r in reasons]
        sub[a]["grounded_by_denial_reason"] = dict(contingency(tab), table=dict(zip(reasons, tab)))
    for key in ("identification_by_stratum", "identification_by_plan_type", "grounded_by_denial_reason"):
        _holm({a: sub[a][key] for a in ARMS})
    out["subgroup_tests"] = sub

    (S / "stats.json").write_text(json.dumps(out, indent=1))

    # ---- print ----------------------------------------------------------------
    print(f"N = {len(cases)} cases; strata {t1['strata']}; {t1['states']} states; {t1['insurers']} insurers")
    print("\nPOLICY IDENTIFICATION (correct / n, Wilson 95% CI)")
    for arm in ARMS:
        row = "  ".join(f"{s[:6]:6s} {ident[arm][s]['k']:3d}/{ident[arm][s]['n']:3d} "
                        f"[{100*ident[arm][s]['lo']:.0f}–{100*ident[arm][s]['hi']:.0f}]"
                        for s, _ in STRATA + [("all", "all")])
        print(f"  {LABEL[arm]:13s} {row}")
    print("\nPAIRED (all 167): discordant pairs, exact McNemar")
    for k, v in cmp["all"].items():
        a1, a2 = k.split(" vs ")
        print(f"  {k:28s} {a1} only={v[a1+'_only']:3d}  {a2} only={v[a2+'_only']:3d}  {fmt_p(v['p'])}  "
              f"diff {100*v['diff']:+.0f} pts [{100*v['diff_lo']:+.0f}, {100*v['diff_hi']:+.0f}]")
    print("\nLETTERS")
    for name, m in letters.items():
        if name == "completeness_judged":
            continue
        print(f"  {name} (stratum {m['scope']}, n={m['n']}): " +
              "; ".join(f"{LABEL[a]} {m['arms'][a]['k']}" for a in ARMS) +
              "  | vs Ortho: " + ", ".join(f"{LABEL[a]} {fmt_p(m['paired']['ortho-opus vs '+a]['p'])}" for a in ARMS[1:]))
    print("  completeness (judged, 0-4): " + "; ".join(f"{LABEL[a]} {comp[a]['mean']:.2f}" for a in ARMS))
    print(f"\nOrthoAppeals correction pass: {out['ortho_correction_pass']}")
    print("\nEFFORT (median searches / fetches per case):")
    for a, e in eff.items():
        print(f"  {LABEL[a]:8s} searches {e['searches_median']} {e['searches_iqr']}  fetches {e['fetches_median']} {e['fetches_iqr']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
