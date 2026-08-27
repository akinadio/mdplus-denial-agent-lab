# The validation study — how to run it

Protocol: four arms (GPT flagship, Gemini flagship, Claude flagship, OrthoAppeals
production), 200 synthetic denial letters, primary endpoint citation validity
(exists / right payer / right code / current — all four must pass).

## Pipeline

```bash
python3 scripts/study/build_cases.py          # 200 cases, 120/40/40, deterministic
export STUDY_BLIND_SALT="<random string, keep out of the repo>"
export ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GOOGLE_API_KEY=...
python3 scripts/study/run_arms.py --arms all --limit 5    # pilot first
python3 scripts/study/run_arms.py --arms all --resume     # full run
python3 scripts/study/score.py                # offline pass, blinded
# ...live-fetch pass + human pass on every run scored needs_human...
python3 scripts/study/analyze.py              # unblind, McNemar, Bonferroni
```

## What lives where

| File | Who may read it |
|---|---|
| `cases_v1.json` | the arms. Denial letters only — carries no titles, no URLs; a test proves it. |
| `gold_key_v1.json` | graders only. One verified document per case, pinned to the directory. |
| `runs/run-*/` | blinded outputs. The id encodes the arm only through a salted hash. |
| `unblinding_map.json` | analyze.py only, after scoring closes. score.py provably never reads it. |

## Two honesty rules, before anyone quotes a number

**The OrthoAppeals arm's offline score is circular by construction.** Cases are
drawn from combinations where the directory holds a verified document, and the
production tool answers from that same directory — so its offline score of
100% is a consistency check, not a finding. The number that counts for
OrthoAppeals comes only after (a) the live-fetch scoring pass confirms every
cited URL still resolves to the current edition on the study date, and (b) the
protocol's independent human pass confirms the gold key against the payers'
own sites. The general-model arms have no such circularity: their citations
are scored against ground truth they never saw.

**A directory correction invalidates the case set.** `test_study.py` pins every
gold entry to the current directory row; if a URL is replaced or a status is
downgraded after cases are built, the tests fail until `build_cases.py` is
re-run — a study scored against a key we no longer believe is worse than no
study.

## Still needed before the real run

API keys as server secrets (never in chat or the repo); a decision on which
exact flagship model IDs the three general arms pin (they are recorded into
every result file); the research coordinator for the human pass; and the
live-fetch scoring mode, which is deliberately unimplemented until the study
actually runs.
