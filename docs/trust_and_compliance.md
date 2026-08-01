# Trust & compliance (Phase 3)

Work toward safely accepting real patient information. Some of this is code
(shipped here); the rest is legal/operational and is flagged as remaining.

## Shipped

- **HTTP security headers** (`synthetic_harness/security.py`, applied to every
  response): `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: SAMEORIGIN`, `Cross-Origin-Opener-Policy: same-origin`, a
  conservative `Content-Security-Policy`, `Strict-Transport-Security` when the
  request arrived over HTTPS through a trusted proxy, and `Cache-Control:
  no-store` on all `/api/` responses so patient data is never cached. The CSP
  keeps `'unsafe-inline'` (both frontends use inline code) but shuts off object
  embeds, cross-origin framing, and base-tag hijacking. Override via `MDPLUS_CSP`
  (empty to disable); HSTS via `MDPLUS_ENABLE_HSTS`.
- **Consent gate at intake** (`mockups/map/`): before building the appeal, the
  patient must check a box acknowledging this is not medical or legal advice and
  not a coverage guarantee, and agreeing to the Privacy Notice & Terms. The build
  button is disabled until then.
- **Privacy Notice & Terms page** (`mockups/legal.html`, served at
  `/patient/legal.html`): a plain-language, senior-readable template covering
  what is collected, how it is used, sharing, retention, choices, and terms. It
  is clearly marked as a template for counsel to finalize, with bracketed fields
  ([COMPANY], [CONTACT EMAIL], [RETENTION PERIOD], effective date).

## Remaining (before real patients)

- **TLS in production.** Terminate HTTPS at a reverse proxy (see `docs/deploy.md`)
  and set `MDPLUS_TRUST_PROXY=true` so HSTS is sent and forwarded client IPs are
  honored. The app should not be reachable over plain HTTP once live.
- **Encryption at rest — extend it.** Envelope AES-256-GCM encryption
  (`synthetic_harness/encryption.py`) now seals the most sensitive artifacts —
  uploaded denial-letter files and the OCR'd letter text — when a key is
  configured (`MDPLUS_ENCRYPTION_KEY`). The design is envelope-based so the
  master key can move to a managed KMS later with no data migration. Two things
  remain: (1) turn on **volume/disk encryption** at the host as the baseline that
  covers everything at rest (the DB, message envelopes, results, logs) with no
  code, and (2) extend field-level encryption to the episode message bodies and
  the SQLite state (the follow-on). Recommended stance: volume encryption now +
  the app-level sealing already shipped, then KMS + field-level encryption as a
  BAA/audit requires.
- **BAA + HIPAA assessment.** Sign a Business Associate Agreement with the model
  and any subprocessors, and complete a HIPAA/privacy assessment, before PHI
  flows through. List covered vendors in the privacy notice.
- **Retention/deletion automation.** Implement the retention period the notice
  promises (scheduled purge/de-identification) and a self-serve or email deletion
  path.
- **Finalize the legal template** with counsel and fill the bracketed fields.
