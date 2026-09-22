#!/usr/bin/env python3
"""Independent audit of the study's files. Read-only; prints PASS/FAIL lines.

Every check here re-derives something by a DIFFERENT route than the script
that produced it, so an error in score.py, grade_letters.py or stats.py
cannot hide behind itself:

  1  structure      every case has every arm once; every run parses; every
                    letter is graded, and the grade is of the letter on disk
  2  answer key     every governing document is on disk, names the operation,
                    and (stratum A) has reviewed criteria; alternates readable
  3  identification every chatbot 'correct' that is not the exact URL must
                    share the reviewed criteria of the governing document, or
                    be an accepted alternate; every 'wrong' is re-read
  4  letters        mechanical fields recomputed from the letters and compared
                    to the stored grades; OrthoAppeals letters re-checked for
                    unsourced rules and quotes outside the excerpts
  5  statistics     the test functions against known values

  python3 scripts/study/audit.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "study")]
S = ROOT / "study"
fails = 0


def check(ok, what, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {what}" + (f"\n          {detail}" if detail and not ok else ""))
    fails += not ok


def main() -> int:
    from synthetic_harness.policy_text import _key
    from synthetic_harness.quote_check import _norm, quoted_passages, in_text
    from synthetic_harness.letter_checks import unsourced_requirements
    import score as SC
    import grade_letters as GL
    import stats as ST

    cases = {c["case_id"]: c for c in json.loads((S / "cases.json").read_text())["cases"]}
    gold = {g["case_id"]: g for g in json.loads((S / "gold.json").read_text())["entries"]}
    key = json.loads((S / "unblinding.json").read_text())
    scores = json.loads((S / "scores.json").read_text())
    grades = json.loads((S / "letter_grades.json").read_text())
    secmap = json.loads((ROOT / "data/policy_platform/section_criteria.json").read_text())
    ARMS = ["ortho-opus", "chatgpt", "claude-free", "gemini"]

    def text(u):
        p = _key(u)
        return (json.loads(p.read_text()).get("text") or "") if p.exists() else None

    print("[1] structure")
    per = {}
    for r, v in key.items():
        per.setdefault(v["case_id"], []).append(v["system"])
    check(len(cases) == 167 and set(cases) == set(gold), "167 cases, answer key covers each exactly")
    check(all(sorted(a for a in per[c] if a != "ortho-sonnet") == sorted(ARMS) for c in cases),
          "every case has each of the four arms exactly once")
    bad = []
    for r, v in key.items():
        if v["system"] == "ortho-sonnet":
            continue
        try:
            res = json.loads((S / "runs" / r / "result.json").read_text())
            L = json.loads((S / "runs" / r / "letter.json").read_text())
        except Exception as e:  # noqa: BLE001
            bad.append((r, str(e)[:40])); continue
        if res.get("error") or L.get("error") or not L.get("letter_markdown"):
            bad.append((r, "error or empty letter"))
        g = grades.get(r) or {}
        sha = hashlib.sha256((L.get("letter_markdown") or "").encode()).hexdigest()[:16]
        if g.get("outcome") != "graded" or g.get("letter_sha") != sha or g.get("case_id") != v["case_id"]:
            bad.append((r, "grade missing, stale, or for another case"))
        if r not in scores:
            bad.append((r, "not scored"))
    check(not bad, "668 runs parse, have a letter, are scored, and are graded as they stand", str(bad[:3]))

    print("[2] answer key")
    bad = []
    from synthetic_harness.policy_text import PROCEDURE_TERMS
    for c, g in gold.items():
        st = cases[c]["stratum"]
        if st == "no_policy":
            if g.get("policy_url"):
                bad.append((c, "no-policy case has a document"))
            continue
        t = text(g["policy_url"])
        if not t:
            bad.append((c, "governing document not on disk")); continue
        terms = [g["cpt"]] + PROCEDURE_TERMS.get(g["cpt"], [])
        if not any(x.lower() in t.lower() for x in terms):
            bad.append((c, "document names neither the code nor the operation"))
        if st == "in_library":
            m = secmap.get(f"{g['policy_url']}||{g['cpt']}")
            if not m or not m.get("covered") or not m.get("criteria"):
                bad.append((c, "no reviewed criteria for this document and operation"))
        for alt in g.get("accepted_alternates") or []:
            if not text(alt["policy_url"]):
                bad.append((c, "alternate document not on disk"))
    check(not bad, "every governing document is on disk, names the operation, and has reviewed criteria", str(bad[:4]))

    print("[3] identification")
    n_eq = n_bad = n_alt = 0; bad = []
    for r, v in key.items():
        if v["system"].startswith("ortho"):
            continue
        g = gold[v["case_id"]]
        if g["stratum"] != "in_library":
            continue
        s = scores[r]
        if s["outcome"] != "correct" or s.get("match") == "exact":
            continue
        if s.get("match") == "alternate":
            n_alt += 1; continue
        n_eq += 1
        ans = json.loads((S / "runs" / r / "result.json").read_text()).get("answer") or {}
        u = SC.cited_url(ans)
        ct = text(u)
        crit = [x["text"] for x in (secmap.get(f"{g['policy_url']}||{g['cpt']}") or {}).get("criteria", [])]
        if ct is None:
            bad.append((r, "cited document not on disk")); continue
        nt = _norm(ct)
        hits = sum(1 for x in crit if len(_norm(x)) > 30 and _norm(x)[:120] in nt)
        ids = s.get("why", "").startswith("same guideline number") or "redirect" in s.get("why", "")
        if hits == 0 and not ids:
            n_bad += 1; bad.append((r, v["system"], g["payer"][:20], g["cpt"], u[-50:]))
    check(n_bad == 0, f"{n_eq} 'equivalent' verdicts share the governing document's reviewed criteria "
                      f"or its guideline number ({n_alt} via accepted alternates)", str(bad[:4]))
    # every stratum-A chatbot verdict re-derived from the answer files
    mism = []
    for r, v in key.items():
        if v["system"].startswith("ortho"):
            continue
        ans = json.loads((S / "runs" / r / "result.json").read_text()).get("answer") or {}
        new = SC.score(ans, gold[v["case_id"]])
        if new["outcome"] != scores[r]["outcome"]:
            mism.append((r, scores[r]["outcome"], new["outcome"]))
    check(not mism, "re-scoring every chatbot answer reproduces scores.json", str(mism[:4]))

    print("[4] letters")
    mism = []; ortho_bad = []
    for r, v in key.items():
        if v["system"] == "ortho-sonnet":
            continue
        L = json.loads((S / "runs" / r / "letter.json").read_text())
        c = cases[v["case_id"]]
        fresh = GL.mechanical(L["letter_markdown"], c, GL._with_cited(r, gold[v["case_id"]]))
        g = grades[r]
        for k in ("quote_not_in_policy", "deadline_correct", "route_given", "sendable",
                  "invented_identifier", "grounded_in_case", "quotes_other_procedure"):
            if k in fresh and bool(fresh[k]) != bool(g.get(k)):
                mism.append((r, k, g.get(k), fresh[k]))
        if v["system"] == "ortho-opus":
            ex = (L.get("evidence") or {}).get("quotes") or []
            facts = [c["letter_text"], c["chart_summary"]]
            n = unsourced_requirements(L["letter_markdown"], ex, facts)["count"]
            n += sum(1 for q in quoted_passages(L["letter_markdown"]) if not in_text(q, "\n".join(ex + facts)))
            if n or "audit" not in L:
                ortho_bad.append((r, n, "audit" in L))
    check(not mism, "mechanical fields recomputed from every letter match the stored grades", str(mism[:4]))
    check(not ortho_bad, "every OrthoAppeals letter is from the checked writer, with no unsourced rule or quote",
          str(ortho_bad[:4]))

    print("[5] statistics")
    check(abs(ST.mcnemar_exact(5, 0) - 0.0625) < 1e-9 and abs(ST.mcnemar_exact(10, 0) - 2 / 1024) < 1e-9
          and abs(ST.mcnemar_exact(3, 3) - 1.0) < 1e-9, "exact McNemar matches the binomial by hand")
    p, lo, hi = ST.wilson(0, 120)
    check(lo == 0.0 and abs(hi - 0.0311) < 0.001, "Wilson interval for 0/120 is [0, 3.1%]")
    p, lo, hi = ST.wilson(60, 120)
    check(abs(lo - 0.413) < 0.002 and abs(hi - 0.587) < 0.002, "Wilson interval for 60/120 is [41.3%, 58.7%]")

    print(f"\n{'ALL CHECKS PASSED' if not fails else str(fails) + ' CHECK(S) FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
