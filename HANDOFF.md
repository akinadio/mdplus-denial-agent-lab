# Handoff: taking OrthoAppeals to a sustainable product

This document is for whoever picks up the work. It summarizes the changes made
on the `feature/sustainable-api-backend` branch, how to run them, and what
remains. It complements the phase checklist (delivered separately) and the
detailed docs under `docs/`.

## What changed and why

The prototype reached the model through the `codex`/`claude` CLI, authenticated
by an interactive login that expires — incompatible with running unattended for
months. The output was also an action plan only (no appeal letter), and the
denial-reason branching lived implicitly in the model's answer.

Three tranches of work address that:

### 1. Sustainable execution engine (`docs/sustainable_backend.md`)
- `synthetic_harness/api_runner.py` — a key-authenticated engine that runs the
  `web_search`/`http_fetch` tool loop **in-process** against the Messages API.
  No CLI, no MCP subprocess, no macOS `sandbox-exec` (isolation is intrinsic:
  the model has only those two tools). Auto-selected when `ANTHROPIC_API_KEY`
  is set; legacy `codex`/`claude` engines remain as fallbacks.
- Concurrency cap (`MDPLUS_MAX_CONCURRENT_ARMS`) and an in-process daily spend
  guard (`MDPLUS_DAILY_BUDGET_USD`) with per-run cost accounting.

### 2. Unattended-operation support (`docs/sustainable_backend.md`)
- `synthetic_harness/reliability.py` — startup crash recovery (orphaned
  "running" arms are flipped to "interrupted" and become retryable), a rich
  `/api/health` with a `degraded` flag and reasons, and a failure `alert()`
  hook (`MDPLUS_ALERT_WEBHOOK`).

### 3. Denial-reason-aware output + appeal letter (`docs/denial_reason_output.md`)
- `synthetic_harness/appeal_letter.py` — `assess_letter()` decides what the
  denial reason calls for (draft a letter vs. gather records vs. meet criteria
  vs. not appealable), and `generate_appeal_letter()` drafts a grounded,
  doctor-friendly, payer-onus letter that never fabricates PHI.
- Endpoints: `POST /api/episodes/<id>/appeal-letter`,
  `GET /api/episodes/<id>/appeal-letter/<arm>`; the episode snapshot exposes a
  per-arm `appeal` object.

## Run it

```bash
pip install -e .                 # anthropic + requests
pip install -e '.[fetch]'        # optional: brotli/zstd page decoding
export ANTHROPIC_API_KEY=...      # the sustainable engine
export WEB_SEARCH_API_KEY=...     # Brave Search (web_search)
export MDPLUS_MAX_CONCURRENT_ARMS=4
export MDPLUS_DAILY_BUDGET_USD=50
export MDPLUS_ALERT_WEBHOOK=https://...   # optional failure alerts
cd ui && npm ci && npm run build && cd ..
python3 -m synthetic_harness.server --port 8781 --host 0.0.0.0
```

`deploy/mdplus-harness.service` runs it as a managed systemd service. Set the
env vars in the unit (or an `EnvironmentFile=`) so the service inherits the key.

## Tests

```bash
python3 -m unittest \
  tests.test_synthetic_harness tests.test_api_runner \
  tests.test_reliability tests.test_appeal_letter \
  tests.test_appeal_letter_endpoint      # 51 tests
```

(Four older `tests/` modules use `pytest`; `pip install pytest` to run them.)

## Full environment-variable reference

See the table in `docs/sustainable_backend.md`. Key ones: `ANTHROPIC_API_KEY`,
`WEB_SEARCH_API_KEY`, `MDPLUS_AGENT_ENGINE`, `MDPLUS_API_MODEL`,
`MDPLUS_MAX_CONCURRENT_ARMS`, `MDPLUS_DAILY_BUDGET_USD`, `MDPLUS_ALERT_WEBHOOK`,
`MDPLUS_LOG_LEVEL`.

## What remains (roadmap)

Tracked in the phase checklist. The near-term items:

- **Wire the frontend to the new endpoints.** `mockups/map/` should call
  `POST .../appeal-letter` and render/download the returned Markdown. Today the
  results screen shows the action plan only.
- **Database + object storage (confirmed needed).** Episode/run state is on the
  local filesystem; runtime run-state is in-memory. This is required for running
  multiple instances behind a load balancer and for durable spend/accounts. The
  current single managed service + startup reconciliation survives restarts, so
  this is the next scaling step, not a launch blocker — but it *is* on the plan.
- **Trust/compliance (Phase 3):** TLS + encryption at rest, a BAA with the model
  provider, retention/deletion, terms/privacy/disclaimers, and replacing the
  placeholder per-state payer directory (`mockups/assets/data.js` says it "MUST
  be replaced").
- **Accounts + auth/rate-limiting (Phase 4):** the API has no auth or throttling
  yet.
- **Finish the accuracy eval (Phase 6):** the cold calibration run (board task
  T005) has never executed; run it before real patients rely on the output.

## Branch / delivery

All work is on `feature/sustainable-api-backend` as atomic commits. If you
received this as a patch: `git checkout -b feature/sustainable-api-backend &&
git am < sustainable-api-backend.patch`, then push and open a PR.
