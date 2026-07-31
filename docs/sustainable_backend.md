# Sustainable backend: the API execution engine

This document covers the change that lets the harness run **unattended** — no
human refreshing a login, no CLI, no macOS sandbox.

## The problem it fixes

The original engines reach the model by shelling out to the `codex` or `claude`
CLI. Those are authenticated by an **interactive login that lives on the host
and expires**. When it expires a run dies mid-flight (this is what killed the
T021 gated-payer probe after 26 minutes of work), and a human has to log back
in. That is incompatible with "runs for months without being monitored."

## The engine

`synthetic_harness/api_runner.py` (`run_api_arm`) talks to the Messages API
directly, authenticated by an **API key** held as a server secret. It also:

- Runs the agent's two tools (`web_search`, `http_fetch`) **in-process** — no
  MCP subprocess, no CLI binary.
- Needs **no macOS `sandbox-exec`**. The web-only isolation is intrinsic: the
  model's only capabilities are those two functions, so there is no file tool,
  no shell, and no path to the local library or answer key.
- Preserves the existing prompt, JSON result contract, tool-trace format, and
  the "resume the same conversation to fill missing sections" repair behavior.

It is selected automatically whenever `ANTHROPIC_API_KEY` is set (see
`agent_runner.engine_name`), falling back to the legacy `codex` / `claude`
engines otherwise. Force it with `MDPLUS_AGENT_ENGINE=api`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | **Required** for the api engine. Store as a secret, never in the repo. |
| `MDPLUS_AGENT_ENGINE` | `auto` | `auto` prefers `api` when a key is present; set to `api`, `claude`, or `codex` to force. |
| `MDPLUS_API_MODEL` | `claude-opus-5` | Model ID for the api engine. |
| `MDPLUS_MAX_TOOL_ITERATIONS` | `40` | Caps tool round-trips per run (bounds per-run cost). |
| `MDPLUS_MAX_OUTPUT_TOKENS` | `8000` | Max tokens per model response. |
| `MDPLUS_MAX_CONCURRENT_ARMS` | `4` | Server-wide cap on simultaneous heavy runs. Excess launches queue. |
| `MDPLUS_DAILY_BUDGET_USD` | `0` (off) | When >0, the server pauses new runs once the day's estimated spend hits it. |
| `MDPLUS_PRICE_INPUT_PER_MTOK` / `MDPLUS_PRICE_OUTPUT_PER_MTOK` | `15` / `75` | Per-million-token prices used for the cost estimate. Set to your model's real published prices. |
| `MDPLUS_API_MAX_RETRIES` | `4` | SDK retry count on transient API errors. |
| `MDPLUS_LOG_LEVEL` | `INFO` | Log verbosity for the harness logger. |
| `MDPLUS_ALERT_WEBHOOK` | — | If set, failed/crashed runs are POSTed here as JSON (best-effort, off-thread) so failures reach a human channel. |

## Crash recovery and health (unattended operation)

`synthetic_harness/reliability.py` adds the pieces that make "runs for months
unmonitored" real:

- **Crash recovery.** On startup the server calls `reconcile_interrupted_runs`.
  A run executes in a thread that cannot survive a restart, so any arm still
  marked `running` on disk after a reboot is stale — it is flipped to
  `interrupted` so the UI and the retry guard don't wait forever on a run that
  will never finish. An interrupted arm is immediately retryable.
- **Health you can page on.** `GET /api/health` now returns `degraded` plus
  `degraded_reasons` (missing `ANTHROPIC_API_KEY`/`WEB_SEARCH_API_KEY`, UI not
  built, budget paused), the active engine, live concurrency (max / active /
  free slots), the day's estimated spend, and the episode count. An uptime
  checker can alert on `degraded: true` instead of merely "is the port open".
- **Failure alerts.** Every failed or crashed run is logged and, if
  `MDPLUS_ALERT_WEBHOOK` is set, pushed to that URL.

Still deliberately deferred: moving episode/run state into a database + object
storage. That is only required for running multiple instances behind a load
balancer; for a single managed service (the systemd unit in `deploy/`), the
filesystem plus startup reconciliation already survives restarts. Do the DB
migration when horizontal scale is the actual need.

## Install

```bash
pip install -e .            # pulls in anthropic + requests
# optional, so payer pages compressed with brotli/zstd are readable:
pip install -e '.[fetch]'
```

## Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export WEB_SEARCH_API_KEY=...      # Brave Search, still required for web_search
export MDPLUS_MAX_CONCURRENT_ARMS=4
export MDPLUS_DAILY_BUDGET_USD=50
python3 -m synthetic_harness.server --port 8781 --host 0.0.0.0
```

## What this does and does not cover (from the Phase 1 checklist)

Covered here: the API-key engine (removes the expiring-login failure), the
concurrency cap, and a basic in-process spend guard with per-run cost accounting.

Still open in Phase 1: moving episode/run state off the local filesystem into a
database + object storage (needed for multi-instance and crash recovery), and
health-check/alerting wiring. The spend guard is in-process and resets on
restart; the durable version belongs with the database work.
