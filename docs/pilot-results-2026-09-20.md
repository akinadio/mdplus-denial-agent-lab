# OrthoAppeals pilot — results, 2026-09-20

60 synthetic denial letters, 13 orthopedic procedures, 37 payers, 36 states.
Five systems answered every letter and drafted an appeal: 300 retrievals, 300
letters, 299 graded. Total API spend $158.64.

## 1. Found the governing policy (60 cases, paired)

| system | correct | vs OrthoAppeals-Opus |
|---|---|---|
| OrthoAppeals (Opus) | 60/60 100% | — |
| OrthoAppeals (Sonnet) | 60/60 100% | +0 −0, P=1.00 |
| ChatGPT (gpt-5.6-luna) | 38/60 63% | +22 −0, P<.0001 |
| Claude free (Sonnet) | 34/60 57% | +26 −0, P<.0001 |
| Gemini (3.5 Flash) | 30/60 50% | +30 −0, P<.0001 |

**This row is circular for the OrthoAppeals arms and must be reported as such.**
`run_ortho()` returns `policy_url` from `app_option_policy_directory.csv`, and
`refresh_gold()` writes the same field of the same row into the answer key: the
two are byte-identical in 60 of 60. The cases were sampled from that directory
as well, so coverage is 100% by design. The honest claim is not "finds the
policy better" but *a curated, independently verified library returns the
governing document where a general chatbot with web search largely does not.*
See `docs/audit-2026-09-19.md`.

The key was independently verified against the live documents for the first
time (`verify_gold.py`): 29/30 in-library entries resolve, name the procedure
and state criteria. Stratum C cannot be verified by fetching anything — the
claim is that a payer publishes nothing — so those 15 rest on our research note.

### By stratum

| | in_library (30) | vendor_held (15) | no_policy (15) |
|---|---|---|---|
| ChatGPT | 50% | 60% | **93%** |
| Claude free | 57% | 40% | 73% |
| Gemini | 63% | 47% | **27%** |

The last column is the one that matters clinically: when the insurer publishes
nothing, the correct answer is to say so. ChatGPT does that 93% of the time.
Gemini invents a document instead in 11 of 15.

## 2. The letter (299 letters graded)

| | sendable | states the deadline | gives a route | invented an ID | **grounded** |
|---|---|---|---|---|---|
| OrthoAppeals (Opus) | 100% | 100% | 100% | 2% | **26/30 87%** |
| Gemini | 100% | **18%** | 97% | 25% | 22/30 73% |
| Claude free | 100% | 93% | 100% | 18% | 16/30 53% |
| OrthoAppeals (Sonnet) | 100% | 95% | 93% | 0% | 15/29 52% |
| ChatGPT | 88% | 45% | 67% | 8% | **2/30 7%** |

**Grounded** is the endpoint that matters: the letter quotes a rule from the
policy that answers the reason *this* claim was denied. Quoting nothing fails;
quoting the wrong rule fails; quoting the denial notice back fails. Paired
against OrthoAppeals-Opus: ChatGPT +25 −1 (P<.0001), Claude-free +11 −1
(P=.006), OrthoAppeals-Sonnet +10 −0 (P=.002), Gemini +5 −1 (P=.22).

**Sendable** = carries the member ID, reference number, name and denial date off
the notice. Missing those, a clerk returns the letter before anyone reads it.

**Gemini states the appeal deadline in 11 of 60 letters.** Its letters are full
of dates — the MRI, the injections, the notice — but not the one date that
decides whether the appeal is accepted at all. That is the single most
consequential letter-level defect found in this pilot, in any arm.

## 3. Opus vs Sonnet inside OrthoAppeals

Identical code path: the retrieval step is a library lookup with no model in it,
so the two arms differ only in who writes the letter. Opus grounded 10 letters
Sonnet did not and lost none (P=.002), and 26/30 against 15/29.

Cost: $0.10 a letter against $0.04. Ship Opus.

## 4. Effort per case (median, from each run's own tool ledger)

| | searches | fetches | input tokens | seconds | $/case |
|---|---|---|---|---|---|
| ChatGPT | 14 | 5 | 85k | 43 | $0.02 |
| Claude free | 14 | 7 | 267k | 106 | $0.22 |
| Gemini | 32 | 4 | 615k | 122 | $0.41 |
| OrthoAppeals | 0 | 0 | — | — | $0.00 |

Search is billed per request ($5/1,000). Gemini costs more than the other three
arms combined and makes the patient wait three times as long as ChatGPT.

## 5. What still has to be settled before write-up

1. Three answer-key entries are wrong and need a human: **Fidelis / 27446**
   (Evolent guideline whose knee section is past our cached copy's cut),
   **Avera / 28296** (points at a Geisinger fax request form), **Priority Health
   / 22551** ("medically necessary according to TurningPoint criteria" — this is
   a vendor-held case labelled in-library).
2. Six cached policy documents are empty or were cut at 120,000 characters.
   `refetch_policies.py --apply` on a machine that can reach payer hosts.
3. The primary endpoint must be reframed as library coverage + accuracy vs.
   retrieval. The main study needs a sampling frame drawn independently of the
   directory, or it can say nothing about coverage.
4. 400 cases does not fit the remaining budget. `docs/budget-2026-09.md`
   recommends 350 cases across ChatGPT / Claude-free / OrthoAppeals with Gemini
   on a 100-case paired subsample.
