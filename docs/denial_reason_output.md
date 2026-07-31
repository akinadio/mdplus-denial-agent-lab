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

## The letter

`generate_appeal_letter(result, patient_submission=...)` drafts a
provider-to-payer appeal letter, grounded strictly in the retrieved citations,
in the intended voice: simple and doctor-friendly, framing the denial as the
payer's decision measured against the payer's *own* published criteria, without
inflammatory or accusatory language and without promising coverage. It never
fabricates PHI — patient/chart specifics are left as `[bracketed placeholders]`
for the surgeon's office to complete. Output is Markdown ending with a
not-advice / no-guarantee note.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/episodes/<id>/appeal-letter` | Body `{"arm": "web_only"}`. Assesses the denial; if a letter is warranted (and within budget) drafts and stores it, returning `{assessment, letter}`. If not warranted, returns `{assessment}` with the reason. |
| GET | `/api/episodes/<id>/appeal-letter/<arm>` | Returns a previously drafted letter `{markdown, meta}`. |

The episode snapshot (`GET /api/episodes/<id>`) now includes, per arm, an
`appeal` object: `{assessment, letter_available}` — enough for the frontend to
show either a "Draft the appeal letter" button or the "do this first" guidance.

The drafted letter and its metadata are stored at
`system/<arm>/appeal_letter.md` and `system/<arm>/appeal_letter_meta.json`, and
the draft event is written to the episode log.

## Not yet wired

The patient frontend (`mockups/map/`) does not yet call these endpoints — the
results screen still shows the action plan only. Wiring a "Draft my appeal
letter" button to `POST .../appeal-letter` and rendering the returned Markdown
(with download / print) is the remaining front-end task for this feature.
