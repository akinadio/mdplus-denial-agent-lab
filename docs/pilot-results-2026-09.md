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
| maps the plan's criteria to the records | 98% | 97% |
| states the appeal deadline | 95% | 38% |
| says where to send it | 90% | 65% |
| quotes the policy (quotations made / wrong) | 158 / 4 | 11 / 3 |
| invents a policy number or date | 9% | 12% |
| addresses the wrong insurer | 0 | 1 |
| completeness, 0–4 | 3.3 | 2.7 |

ChatGPT uses the records as well as we do. It does not quote the policy — 11
quotations across 60 letters, a quarter of them not in the document — and in
most letters it does not know the deadline or the governing document.

**What the pilot found about the product, fixed before this run.** It invented
policy quotations because it held links, not text; it withheld documents it had
on 896 rows; it served Medicare Advantage policies to commercial members on 368
UnitedHealthcare rows; every letter omitted the deadline and the address. The
comparison above is against the fixed product, which now reads the policy and
quotes only what is in it.

**Cost.** About $60 in model and search fees for the whole pilot, including
every re-run. The 400-letter study is estimated at $250–400.

**Before the 400.** Sign-off on the three case kinds and on one OrthoAppeals
arm, and one decision: a letter refused by OpenAI's content filter (once in 60)
is scored as no answer, or excluded.
