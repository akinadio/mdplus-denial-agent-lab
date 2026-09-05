#!/bin/bash
# OrthoAppeals PoC -- ChatGPT arm.
# The two OrthoAppeals arms are already scored and stored. This runs the
# comparison arm, which only your Mac can do: api.openai.com is blocked from
# Claude's sandbox, so the key never leaves this machine.
#
# Run it with:   bash ~/mdplus-denial-agent-lab/RUN_CHATGPT.command
# Your key is read from openai.env, which is gitignored.

set -u
cd "$(dirname "$0")" || exit 1
export PYTHONPATH="$PWD:$PWD/scripts"

if [ ! -f openai.env ]; then
  echo "openai.env is missing. Put OPENAI_API_KEY=\"sk-...\" in it and re-run."
  exit 1
fi
set -a
. ./openai.env
# .env holds ANTHROPIC_API_KEY and WEB_SEARCH_API_KEY; the preflight below
# needs the search key in the environment, not just inside run_poc.py.
[ -f .env ] && . ./.env
set +a

case "${OPENAI_API_KEY:-}" in
  ""|PASTE*|sk-your-key*) echo "OPENAI_API_KEY still looks like a placeholder."; exit 1;;
esac
echo "key loaded (${#OPENAI_API_KEY} chars)"

echo
echo "== installing/updating the OpenAI SDK (Responses API needed) =="
python3 -m pip install -q -U openai 2>/dev/null || { echo "pip install failed"; exit 1; }

# A failed run still leaves a result.json behind, and --resume treats that as
# done -- which silently re-reports yesterday's error against today's fix.
# Clear the failures first; completed runs are never touched.
echo
echo "== clearing failed runs (completed runs are kept) =="
python3 - <<'PY'
import json, glob, shutil, pathlib
n = 0
for f in glob.glob("study/poc_runs/*/result.json"):
    r = json.load(open(f))
    if "error" in r or "skipped" in r:
        shutil.rmtree(pathlib.Path(f).parent); n += 1
print(f"  cleared {n} failed run(s); {len(glob.glob('study/poc_runs/*/result.json'))} good runs kept")
PY

# Check the search budget BEFORE spending 20 minutes of model time. The last
# run died on a $5 monthly cap partway through and scored the rest blind.
echo
echo "== preflight: is the search backend answering? =="
python3 - <<'PF' || { echo; echo "Fix the search key or budget first. Nothing else was run."; exit 1; }
import sys, pathlib
sys.path.insert(0, str(pathlib.Path.cwd() / "scripts"))
from policy_eval.webtools import search
r = search("UnitedHealthcare surgery of the knee medical policy", count=3)
err = r.get("error")
if err:
    print("  SEARCH IS DOWN:", str(err)[:200]); sys.exit(1)
if not r.get("result_count"):
    print("  search returned zero results with no error -- stopping anyway"); sys.exit(1)
print(f"  ok, {r['result_count']} results")
PF

echo
echo "== smoke test: one letter =="
python3 scripts/study/run_poc.py --systems chatgpt --limit 1 --resume
python3 - <<'PY' || { echo; echo "Stopping before the full run. Send Claude the error above."; exit 1; }
import json, glob, sys
m = json.load(open("study/poc_unblinding.json"))
bad = []
for f in glob.glob("study/poc_runs/*/result.json"):
    r = json.load(open(f))
    if m.get(r.get("run_id"), {}).get("system") == "chatgpt" and ("error" in r or "skipped" in r):
        bad.append(r.get("error") or r.get("skipped"))
if bad:
    print("\nSMOKE TEST FAILED:\n  " + bad[0]); sys.exit(1)
print("\nsmoke test passed")
PY

echo
echo "== full run: 60 letters, ChatGPT arm =="
echo "   (real web tools, so budget a few minutes per letter)"
python3 scripts/study/run_poc.py --systems chatgpt --resume

echo
echo "== scoring all three arms =="
python3 scripts/study/score_poc.py
echo
python3 scripts/study/analyze_poc.py
echo
echo "Done. Paste everything from ACCURACY down back to Claude."
