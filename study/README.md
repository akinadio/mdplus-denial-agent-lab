# The validation study

Does OrthoAppeals find the right policy and write a usable appeal more often
than a free chatbot? Two arms, one case set, two phases.

**Arms.** ChatGPT (GPT-5.6 Luna, the free-tier model, with real web search and
fetch) and OrthoAppeals (the production path on Sonnet). One OrthoAppeals arm:
retrieval is a directory lookup with no model call, so two models would return
identical rows.

**Cases.** Synthetic denial letters, each with a chart summary in the shape of
a prior-auth packet, in three strata:

| stratum | the payer... | correct behavior |
|---|---|---|
| `in_library` | publishes the policy, with criteria | cite the document |
| `vendor_held` | publishes the policy, but its criteria live in InterQual/MCG | cite the document AND route for the criteria |
| `no_policy` | publishes nothing for this code | say so, and route for the criteria |

The pilot is 30 / 15 / 15. The full run changes `WANT` in `build_cases.py`.

**Phase 1, retrieval.** Which document governs this denial? Scored against the
document, not the URL string: the same guideline number from the same
publisher, or a document that names the code and states criteria for it, is
correct (`equivalence.py`). That is what makes our own arm falsifiable -- the
gold key comes from the directory the tool reads.

**Phase 2, letters.** Each arm drafts the appeal from its own phase-1 answer,
with the identical chart. A blinded grader scores each letter; every quotation
is checked mechanically against the fetched policy text (`quote_check.py`),
because a quote is either in the document or it is not.

## Running it

```
bash STUDY.command check      # free, one second: is the pipeline sound?
bash STUDY.command fixes      # free: read the policies, rebuild the app data
bash STUDY.command retrieve   # paid: phase 1
bash STUDY.command letters    # paid: phase 2
```

Every paid step runs `check` first and stops if it fails. Nothing is spent on
a pipeline the dry run has not passed -- every bug the first pilot found the
expensive way is a check in `dryrun.py` now.

## Files

| file | what |
|---|---|
| `cases.json` | what the arms see: letters, charts, no answers |
| `gold.json` | what the graders see |
| `unblinding.json` | run id -> (case, system); `score.py` never reads it |
| `runs/r-*/` | one directory per run: `result.json`, `tools.jsonl`, `letter.json` |
| `scores.json`, `letter_grades.json` | phase 1 and phase 2 grades, blind |
| `_superseded/` | parked runs and the retired v1 pipeline; gitignored |

## Before a number goes anywhere

- A Claude model grading letters a Claude model wrote is not a neutral judge.
  Read a blinded random sample by hand first.
- One letter was refused by OpenAI's moderation. Decide up front whether a
  refusal is `no_answer` (what the patient experiences) or excluded.
- The search budget: ~16 searches per letter. 400 letters needs ~6,300.
