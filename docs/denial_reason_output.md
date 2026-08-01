# Denial-reason-aware output and appeal-letter drafting

The retrieval agent already classifies *why* a claim was denied and cites the
payer's own policy language. `synthetic_harness/appeal_letter.py` turns that into
the patient/doctor deliverable, branching on the reason.

## The branch: not every denial wants a letter

`assess_letter(result)` returns a decision with a plain-language `reason`:

| kind | recommended | when |
| --- | --- | --- |
| `appeal_letter` | yes | A governing policy is confirmed (with citations) and the denial turns on documentation or administrative grounds. |
| `gather_first` | no | No confirmed governing policy + citation yet — nothing to ground a letter on. Confirm the source first. |
| `meet_criteria` | no | The plan's criteria appear genuinely unmet (not merely undocumented). Complete them before appealing. |
| `not_appealable` | no | Reads as a benefit exclusion; a criteria-met letter does not fit. Route to a plan-level exception/review. |
| `blocked` | no | The retrieval was blocked, so there is no verified policy to cite. |

This lets the UI show "here's what to do first" when a letter is not the right
step, rather than always producing one.

## The letter — two voices

`generate_appeal_letter(result, patient_submission=..., sender=...)` drafts an
appeal letter grounded strictly in the retrieved citations, in the intended
voice: simple and doctor-friendly, framing the denial as the payer's decision
measured against the payer's *own* published criteria, without inflammatory or
accusatory language and without promising coverage. It never fabricates PHI —
patient/chart specifics are left as `[bracketed placeholders]`.

Two `sender` voices are produced:

- `provider` — a physician's-office letter, written in the third person for the
  surgeon's office to sign and send.
- `patient` — a first-person member appeal the patient can send themselves.

Output is Markdown ending with a not-advice / no-guarantee note.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/episodes/<id>/appeal-letter` | Body `{"arm": "web_only"}`. Assesses the denial; if a letter is warranted (and within budget) drafts **both** voices and stores them, returning `{assessment, letters: {provider, patient}}`. If not warranted, returns `{assessment}` with the reason. |
| GET | `/api/episodes/<id>/appeal-letter/<arm>?version=provider\|patient` | Returns a previously drafted letter `{version, markdown, meta}`. |

The episode snapshot (`GET /api/episodes/<id>`) includes, per arm, an `appeal`
object: `{assessment, letters_available: [...]}`.

Drafts and metadata are stored at `system/<arm>/appeal_letter_<voice>.md` and
`..._meta.json`; the draft event is written to the episode log.

## Frontend

The patient app (`mockups/map/`) is wired: the results screen shows a **Draft my
appeal letter** button when a letter is the recommended next step (button-
triggered, so a paid draft only runs when the patient asks). It renders both
voices with a toggle and offers copy-to-clipboard and print / save-as-PDF. When
a letter is *not* the right step, it shows the assessment's plain-language
"do this first" guidance instead. Markdown is rendered client-side (headings,
bold/italic, `[placeholder]` highlighting, linkified email); the copy button
copies clean plain text.
