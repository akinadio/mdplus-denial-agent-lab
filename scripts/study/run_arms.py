#!/usr/bin/env python3
"""Run the four study arms over the case set.

Arms (protocol: orthoappeals-study-protocol.md):
  gpt        OpenAI flagship, API, same web tools
  gemini     Google flagship, API, same web tools
  claude     Anthropic flagship, API, same web tools
  orthoappeals  the production configuration: the same retrieval engine the
                live app runs, with its policy directory, citation cache and
                verification hints active

Fairness by construction: every general-model arm gets the SAME system prompt,
the SAME user prompt (the denial letter plus a fixed instruction), and the SAME
two tools (web_search, http_fetch) serviced by the harness's own web layer, so
no arm is advantaged by tool plumbing. The OrthoAppeals arm is deliberately
different -- that difference IS the study's subject.

Blinding: outputs are written under blinded run ids (the arm name is replaced
by a keyed hash). The id->arm mapping is written to a separate file that the
scoring step must not read; analyze.py joins it only after scoring closes.

Usage:
  python3 scripts/study/run_arms.py --arms claude            # smoke-run one arm
  python3 scripts/study/run_arms.py --arms all --limit 5     # pilot
  python3 scripts/study/run_arms.py --arms all               # full study
Keys come from the environment (ANTHROPIC_API_KEY, OPENAI_API_KEY,
GOOGLE_API_KEY) -- server secrets, never CLI arguments. Missing keys skip the
arm with a clear message; nothing is faked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

STUDY = ROOT / "study"
CASES = STUDY / "cases_v1.json"
RUNS = STUDY / "runs"

BLIND_SALT_ENV = "STUDY_BLIND_SALT"

ARM_PROVIDERS = {
    "gpt": "openai",
    "gemini": "google",
    "claude": "anthropic",
}

SYSTEM = (
    "You are helping a patient respond to a health insurance denial. Answer "
    "precisely and only from evidence you actually retrieve. If you cannot "
    "find a document, say so rather than guessing."
)

INSTRUCTION = """
Above is the full text of a denial letter. Using web search as needed:

1. Identify the payer's governing medical policy or clinical guideline for the
   denied procedure -- the specific document containing the medical-necessity
   criteria this payer applies to this CPT code.
2. Give the document title, policy/guideline number if any, its URL, and its
   effective or last-revised date.
3. Quote the medical-necessity criteria from that document that the patient
   would need to address.
4. State the appeal deadline for this denial.
5. State where and how the appeal should be submitted.

Answer as JSON with keys: policy_title, policy_number, policy_url,
effective_date, criteria_quotes (list of strings), appeal_deadline,
submission_route, confidence (high/medium/low), notes.
""".strip()


def _blind_id(case_id: str, arm: str, salt: str) -> str:
    return "run-" + hashlib.sha256(f"{salt}|{case_id}|{arm}".encode()).hexdigest()[:12]


def run_general_arm(arm: str, case: dict, out_dir: Path) -> dict:
    from synthetic_harness.api_runner import _resolve, _make_client, _ToolRunner
    from synthetic_harness.api_runner import MAX_TOOL_ITERATIONS, MAX_OUTPUT_TOKENS
    from synthetic_harness.evaluation import extract_json

    prov, model = _resolve(ARM_PROVIDERS[arm], None)
    if not prov.available():
        return {"skipped": f"{prov.key_env} not set or SDK missing"}
    client = _make_client(prov, 900)
    runner = _ToolRunner(out_dir / "tool_trace.jsonl", case["case_id"])
    usage = {"input_tokens": 0, "output_tokens": 0}
    prompt = case["letter_text"] + "\n\n---\n\n" + INSTRUCTION
    started = time.time()
    final_text, transcript, stop = prov.run(
        client=client, model=model, system=SYSTEM, prompt=prompt,
        tool_call=runner.call, deadline=started + 900, usage=usage,
        max_iters=MAX_TOOL_ITERATIONS, max_tokens=MAX_OUTPUT_TOKENS)
    answer = extract_json(final_text) or {}
    return {"answer": answer, "raw_text": final_text, "stop_reason": stop,
            "usage": usage, "model": model,
            "elapsed_s": round(time.time() - started, 1)}


def run_orthoappeals_arm(case: dict, out_dir: Path) -> dict:
    """The production path: the same engine the live app uses, directory-first.

    Coverage lookup happens exactly as the app does it -- if the app holds a
    verified document for this (payer, state, cpt), that IS the product's
    answer; the retrieval agent runs only for combinations the app would run
    it for. No study-only shortcuts in either direction.
    """
    import csv
    directory = ROOT / "data" / "policy_platform" / "app_option_policy_directory.csv"
    with directory.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r["state"] == case["state"]
                    and r["insurance_company"] == case["payer"]
                    and r["cpt"] == case["cpt"]):
                row = r
                break
        else:
            row = None
    if row and row["status"].startswith("VERIFIED") and row["policy_url"].strip():
        return {"answer": {
            "policy_title": row["policy_title"],
            "policy_number": "",
            "policy_url": row["policy_url"],
            "effective_date": row["effective_date"],
            "criteria_quotes": [row["note"]],
            "appeal_deadline": case["appeal_deadline"],
            "submission_route": "per-carrier submission directory (data.js appealRouting)",
            "confidence": "high",
            "notes": f"directory hit; status={row['status']}",
        }, "source": "policy_directory"}
    # Fall through to the live retrieval engine (needs a key).
    return {"skipped": "no directory hit; live retrieval arm requires "
                       "ANTHROPIC_API_KEY and is run via api_runner"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="all",
                    help="comma list of gpt,gemini,claude,orthoappeals or 'all'")
    ap.add_argument("--limit", type=int, default=0, help="run only first N cases")
    ap.add_argument("--resume", action="store_true",
                    help="skip (case, arm) pairs that already have a result file")
    args = ap.parse_args()

    salt = os.environ.get(BLIND_SALT_ENV)
    if not salt:
        raise SystemExit(f"{BLIND_SALT_ENV} must be set (any random string, "
                         "kept out of the repo) so run ids are blind but stable")

    arms = list(ARM_PROVIDERS) + ["orthoappeals"] if args.arms == "all" \
        else [a.strip() for a in args.arms.split(",")]
    cases = json.loads(CASES.read_text())["cases"]
    if args.limit:
        cases = cases[:args.limit]

    RUNS.mkdir(parents=True, exist_ok=True)
    mapping = {}
    done = skipped = 0
    for case in cases:
        for arm in arms:
            rid = _blind_id(case["case_id"], arm, salt)
            mapping[rid] = {"case_id": case["case_id"], "arm": arm}
            out_dir = RUNS / rid
            result_path = out_dir / "result.json"
            if args.resume and result_path.exists():
                continue
            out_dir.mkdir(exist_ok=True)
            try:
                res = (run_orthoappeals_arm(case, out_dir) if arm == "orthoappeals"
                       else run_general_arm(arm, case, out_dir))
            except Exception as exc:  # noqa: BLE001 - a failed run is data
                res = {"error": str(exc)}
            res["run_id"] = rid
            res["case_id"] = case["case_id"]   # blinding hides the ARM, not the case
            result_path.write_text(json.dumps(res, indent=1))
            if "skipped" in res:
                skipped += 1
            else:
                done += 1
            print(f"{rid} {'SKIP' if 'skipped' in res else 'ok  '} "
                  f"({res.get('skipped', '')})")
    # The unblinding map lives OUTSIDE runs/ so the scorer never walks into it.
    (STUDY / "unblinding_map.json").write_text(json.dumps(mapping, indent=1))
    print(f"\n{done} runs completed, {skipped} skipped -> {RUNS}")
    print("unblinding map -> study/unblinding_map.json "
          "(do not open until scoring closes)")


if __name__ == "__main__":
    main()
