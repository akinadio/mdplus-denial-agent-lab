#!/usr/bin/env python3
"""Does a better model write a better appeal letter, or does a shorter list?

53% of OrthoAppeals letters quote a rule that answers the denial. In most of
the other 14 the answering criterion WAS among the ~12 sentences the writer was
handed, and it picked something else. Two explanations, and they call for
opposite fixes:

  the writer is not good enough at choosing  -> a stronger model helps
  the writer is being asked to choose from too much -> a shorter, ordered list
                                                       helps, and the model is
                                                       not the problem

This runs the same 30 in-library cases under each condition and scores them
with the frozen grounding metric, so the question is settled by measurement
rather than by which explanation sounds better.

Letters are written to study/ab/<condition>/ and never touch study/runs, so the
main pipeline's letters and grades are left alone.

  python3 scripts/study/ab_letters.py --conditions baseline,shortlist,opus
  python3 scripts/study/ab_letters.py --conditions opus --workers 5
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "study"))

STUDY = ROOT / "study"
RUNS = STUDY / "runs"
AB = STUDY / "ab"

# (model, shortlist on). The OrthoAppeals retrieval step is a library lookup --
# no model is involved -- so an "opus" build differs from a "sonnet" build ONLY
# in who writes the letter. That makes this a clean test of the writer.
CONDITIONS = {
    "baseline":  ("claude-sonnet-5", "0"),
    "shortlist": ("claude-sonnet-5", "1"),
    "opus":      ("claude-opus-5",   "0"),
    "opus+list": ("claude-opus-5",   "1"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", default="baseline,shortlist,opus")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    import spend
    from draft_letters import letter_ortho, _load_env_files
    from synthetic_harness.quote_check import quoted_passages, in_text
    from synthetic_harness.quote_relevance import assess
    _load_env_files()

    cases = {c["case_id"]: c for c in json.loads((STUDY / "cases.json").read_text())["cases"]}
    gold = {g["case_id"]: g for g in json.loads((STUDY / "gold.json").read_text())["entries"]}
    key = json.loads((STUDY / "unblinding.json").read_text())
    work = [(rid, info["case_id"]) for rid, info in sorted(key.items())
            if info["system"].startswith("ortho")
            and gold[info["case_id"]]["stratum"] == "in_library"
            and (RUNS / rid / "result.json").exists()]
    if a.limit:
        work = work[:a.limit]

    names = [c.strip() for c in a.conditions.split(",")]
    for c in names:
        if c not in CONDITIONS:
            raise SystemExit(f"unknown condition {c!r}; have {list(CONDITIONS)}")
    est = {"claude-sonnet-5": 0.04, "claude-opus-5": 0.10}
    print(f"  {len(work)} cases x {len(names)} conditions ~= "
          f"${sum(est[CONDITIONS[c][0]] * len(work) for c in names):.2f}\n")

    results = {}
    for cond in names:
        model, shortlist = CONDITIONS[cond]
        os.environ["MDPLUS_CRITERIA_SHORTLIST"] = shortlist
        out_dir = AB / cond
        out_dir.mkdir(parents=True, exist_ok=True)
        lock = threading.Lock()
        done = [0]

        def one(item, model=model, out_dir=out_dir):
            rid, cid = item
            f = out_dir / f"{rid}.json"
            if f.exists() and not json.loads(f.read_text()).get("error"):
                return
            res = json.loads((RUNS / rid / "result.json").read_text())
            try:
                lt = letter_ortho(cases[cid], res, model)
            except Exception as exc:  # noqa: BLE001
                lt = {"error": f"{type(exc).__name__}: {exc}"}
            if lt.get("usage"):
                spend.record("letters-ab", lt.get("model", model), lt["usage"], rid)
            lt["case_id"] = cid
            f.write_text(json.dumps(lt, indent=1))
            with lock:
                done[0] += 1
                if done[0] % 10 == 0:
                    print(f"    {cond}: {done[0]}/{len(work)}", flush=True)

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
            list(pool.map(one, work))

        n = gr = zero = 0
        for rid, cid in work:
            f = out_dir / f"{rid}.json"
            if not f.exists():
                continue
            lt = json.loads(f.read_text())
            if lt.get("error"):
                continue
            qs = [q for q in quoted_passages(lt.get("letter_markdown") or "")
                  if not in_text(q, cases[cid]["letter_text"])]
            n += 1
            gr += bool(assess(qs, cases[cid]["denial_reason"])["grounded"])
            zero += (len(qs) == 0)
        results[cond] = (n, gr, zero, round(time.time() - t0))
        print(f"  {cond:10s} done in {results[cond][3]}s\n")

    print(f"\n{'condition':12s} {'model':16s} {'list':5s} {'n':>3s} {'GROUNDED':>12s} {'no policy quote':>16s}")
    for cond in names:
        n, gr, zero, _ = results[cond]
        model, sl = CONDITIONS[cond]
        print(f"{cond:12s} {model:16s} {'on' if sl == '1' else 'off':5s} {n:>3d} "
              f"{gr:>5d} ({gr/max(n,1):>4.0%}) {zero:>14d}")
    print("\nbaseline is the pipeline as it stands (53% when last measured).")
    spend.report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
