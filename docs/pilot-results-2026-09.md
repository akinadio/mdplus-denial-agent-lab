# OrthoAppeals pilot: 60 denied cases, two questions

For Dr. Kassam. September 2026.

**What we compared.** ChatGPT (GPT-5.6 Luna, the free-tier model, with live
web search) against OrthoAppeals, on the same 60 synthetic denial letters, each
with a chart summary. Three kinds of case: the payer publishes the policy with
its criteria (30); the payer publishes the policy but the criteria live in
InterQual or MCG (15); the payer publishes nothing (15). Two questions: did it
find the policy that governs the denial, and is the appeal letter it wrote one
a reviewer would act on.

**Finding the policy.** OrthoAppeals 60 of 60. ChatGPT 38 of 60 — 50% where a
policy with criteria exists, 60% where the policy is public but the criteria
are vendor-held, 93% where nothing exists. Paired by letter: 22 cases where
OrthoAppeals was right and ChatGPT was not, none the other way. OrthoAppeals is
graded against its own directory here, so its score is a floor check, not a
finding; ChatGPT's is a finding.

**The letter.** Sixty letters each, graded blind against the correct policy,
with every quotation checked against the policy's text by string match.

| | OrthoAppeals | ChatGPT |
|---|---|---|
| names the governing policy | 100% | 51% |
| maps the plan's criteria to the records | 100% | 98% |
| states the appeal deadline | 97% | 45% |
| says where to send it | 100% | 67% |
| quotes the policy (quotations made / wrong) | 155 / 4 | 14 / 3 |
| any factual error in the letter | 6.8% (4/59) | 21.7% (13/60) |
| completeness, 0–4 | 3.6 | 2.8 |

Paired by letter, ChatGPT's letter carried an error and ours did not in 11
cases; the reverse in 2 (P=.02). Our four errors are all misquotations — a
sentence quoted with a word changed or a phrase dropped. ChatGPT's thirteen
are six rules attributed to the plan with no source, six invented policy
numbers or dates, two misquotations, and one letter addressed to the wrong
insurer. ChatGPT uses the records as well as we do. It does not quote the
policy — 14 quotations across 60 letters — and in most letters does not know
the deadline or the governing document.

**What the pilot found about the product, fixed before this run.** It invented
policy quotations because it held links, not text; it withheld documents it had
on 896 rows; it served Medicare Advantage policies to commercial members on 368
UnitedHealthcare rows; every letter omitted the deadline and the address; the live server was not passing the letter the member's name, the deadline, the submission route or the criteria demand at all. The
comparison above is against the fixed product, which now reads the policy and
quotes only what is in it.

**Cost.** About $115 in model and search fees for the whole pilot, including
every re-run. The 400-letter study is estimated at $250–400.

**Before the 400.** Sign-off on the three case kinds and on one OrthoAppeals
arm, and one decision: a letter refused by OpenAI's content filter (once in 60)
is scored as no answer, or excluded.
