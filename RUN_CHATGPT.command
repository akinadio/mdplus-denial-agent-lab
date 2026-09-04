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
set -a; . ./openai.env; set +a

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
