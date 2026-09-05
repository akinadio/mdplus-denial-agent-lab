#!/bin/bash
# OrthoAppeals PoC phase 2: draft the appeal letters, then grade them blind.
# Run phase 1 (RUN_CHATGPT.command) first -- this reads its results.
#   bash ~/mdplus-denial-agent-lab/RUN_LETTERS.command
set -u
cd "$(dirname "$0")" || exit 1
export PYTHONPATH="$PWD:$PWD/scripts"
set -a
[ -f openai.env ] && . ./openai.env
[ -f .env ] && . ./.env
set +a

echo "== drafting letters (both arms, from each arm's own answer) =="
python3 scripts/study/run_letters_poc.py --systems all --resume || exit 1

echo
echo "== grading blind =="
python3 scripts/study/grade_letters_poc.py --resume || exit 1

echo
python3 scripts/study/analyze_letters_poc.py
echo
echo "Done. Paste everything from LETTER QUALITY down back to Claude."
