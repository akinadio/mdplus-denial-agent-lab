# Protocol changes since the September draft

For Dr. Kassam. Five things moved during the pilot. Each one is a sign-off.

**1. Three kinds of case, not one.** The draft had "in library" only. The pilot
forced a middle kind: the payer publishes the policy for the code, but the
policy says the criteria live in InterQual or MCG. That is 13% of the directory
and includes UnitedHealthcare. The correct answer there is both halves — give
the patient the document, and tell them how to demand the criteria. So the
cases are now in-library / vendor-held / no-policy. Pilot split 30 / 15 / 15.
Proposed for the full run: 240 / 80 / 80.

**2. One OrthoAppeals arm, not two.** Finding the policy is a lookup, not a
model call, so Sonnet and Opus return identical rows. The model matters when
the letter is written. If we want Opus vs Sonnet, it is a letter-quality
comparison, and it should be its own question.

**3. Correct means the right document, not the right web address.** Payers
publish the same guideline as a PDF and a web page, in several states' copies,
and in successive editions. Exact-URL matching marked all of those wrong. A
cited document now counts if it carries the same guideline number from the same
publisher, or names the denied code and states criteria for it.

**4. The letter is graded on named defects, not "fatal."** Each counted on its
own: a quotation that is not in the policy (checked against the document by
string match, not by a judge), a rule attributed to the plan with no source,
the wrong policy cited, the wrong insurer addressed, the wrong deadline, an
invented policy number or date, an unfinished letter where the records had the
fact. Plus what a good letter does: cites the right policy, maps criteria to
the records, states the deadline, says where to send it, demands the criteria.

**5. Every case carries a chart.** Symptom duration, a dated PT course with
visit counts, injection, imaging findings, functional deficit, exam. Both arms
get the identical chart. Without one, every letter was placeholders and the
grader marked them all unfinished.

One thing to decide before the full run: a letter refused by OpenAI's content
filter (it happened once in 60) — score it as no answer, which is what the
patient experiences, or exclude it?

Letters are graded by a blinded AI grader against the case's correct policy;
quotations are checked against the fetched policy text by string match.

What the pilot found about the product, fixed before the full run: it invented
policy quotations on 47% of in-library letters because it held links, not
text; it withheld documents it had for 896 rows; it served Medicare Advantage
policies to commercial members for 368 UnitedHealthcare rows; it omitted the
appeal deadline and address from every letter. The comparison is now against a
tool that reads the document and quotes only what is in it.
