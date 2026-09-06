#!/bin/bash
# The OrthoAppeals validation study, end to end. One script, four steps.
#
#   bash ~/mdplus-denial-agent-lab/STUDY.command check     free: is the pipeline sound?
#   bash ~/mdplus-denial-agent-lab/STUDY.command fixes     free: read the policies, rebuild app data
#   bash ~/mdplus-denial-agent-lab/STUDY.command retrieve  paid: phase 1, which policy governs (ChatGPT + OrthoAppeals)
#   bash ~/mdplus-denial-agent-lab/STUDY.command letters   paid: phase 2, draft and grade the appeal letters
#   bash ~/mdplus-denial-agent-lab/STUDY.command all       check, then everything above in order
#
# Runs on your Mac because payer sites, OpenAI and Brave are not reachable from
# Claude's sandboxes. Keys are read from .env and openai.env, both gitignored.
# Every paid step is preceded by the free check, and stops if it fails.
set -u
cd "$(dirname "$0")" || exit 1
export PYTHONPATH="$PWD:$PWD/scripts"
set -a
[ -f openai.env ] && . ./openai.env
[ -f .env ] && . ./.env
set +a
S=scripts/study
P=scripts/policy_platform
step=${1:-help}

check() {
  echo "== check: the pipeline, with no API calls =="
  python3 $S/dryrun.py || { echo; echo "Not sound. Nothing was spent."; exit 1; }
}

fixes() {
  echo "== fixes 1/4  reading every policy document and keeping its criteria verbatim =="
  python3 $P/build_criteria_library.py || exit 1
  echo; echo "== fixes 2/4  reading the rows that hide a document behind an abstaining status =="
  python3 $P/audit_hidden_documents.py --apply || exit 1
  echo; echo "== fixes 3/4  rebuilding the app's generated data and the shipped build =="
  python3 scripts/build_coverage_js.py && python3 scripts/build_submit_js.py && python3 scripts/build_demo.py || exit 1
  echo; echo "== fixes 4/4  re-checking =="
  python3 $S/dryrun.py || exit 1
}

retrieve() {
  case "${OPENAI_API_KEY:-}" in ""|PASTE*|sk-your-key*) echo "OPENAI_API_KEY is missing from openai.env"; exit 1;; esac
  python3 -m pip install -q -U openai 2>/dev/null
  echo "== retrieve: preflight, one search =="
  python3 - <<'PF' || { echo "Search backend is not answering. Fix the Brave key or its spend cap first."; exit 1; }
import sys, pathlib; sys.path.insert(0, str(pathlib.Path.cwd() / "scripts"))
from policy_eval.webtools import search
r = search("UnitedHealthcare surgery of the knee medical policy", count=3)
if r.get("error") or not r.get("result_count"): print("  ", r.get("error") or "zero results"); sys.exit(1)
print(f"  ok, {r['result_count']} results")
PF
  # A failed run leaves result.json behind and --resume would treat it as done.
  python3 - <<'PY'
import json, glob, shutil, pathlib
n = 0
for f in glob.glob("study/runs/*/result.json"):
    if {"error", "skipped"} & set(json.load(open(f))): shutil.rmtree(pathlib.Path(f).parent); n += 1
print(f"  cleared {n} failed run(s); {len(glob.glob('study/runs/*/result.json'))} kept")
PY
  echo; echo "== retrieve: OrthoAppeals arm (local, seconds) =="
  python3 $S/retrieve.py --systems ortho-sonnet --resume || exit 1
  echo; echo "== retrieve: ChatGPT arm, smoke test on one letter =="
  python3 $S/retrieve.py --systems chatgpt --limit 1 --resume || exit 1
  echo; echo "== retrieve: ChatGPT arm, all letters (real web tools, minutes per letter) =="
  python3 $S/retrieve.py --systems chatgpt --resume || exit 1
  echo; python3 $S/score.py && echo && python3 $S/analyze.py
}

letters() {
  echo "== letters: both arms draft from their own phase-1 answer =="
  python3 $S/draft_letters.py --systems all --resume || exit 1
  echo; echo "== letters: grading blind =="
  python3 $S/grade_letters.py --resume || exit 1
  echo; python3 $S/analyze_letters.py
}

case "$step" in
  check)    check ;;
  fixes)    check; fixes ;;
  retrieve) check; retrieve ;;
  letters)  check; letters ;;
  all)      check; fixes; retrieve; letters ;;
  *)        sed -n '2,10p' "$0" ;;
esac
