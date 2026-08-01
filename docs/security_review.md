# Security posture & pre-launch checklist

A summary of what is hardened and a checklist to run before the link goes out.

## Hardening in place

- **Sustainable auth:** the model is reached via an API key held as a server
  secret, not an interactive CLI login (no expiring session).
- **Transport:** HTTPS via a reverse proxy; HSTS emitted behind a trusted proxy;
  security headers (nosniff, no-referrer, SAMEORIGIN, COOP, CSP) on every
  response; `no-store` on all `/api/` responses (no PHI in caches).
- **Abuse/cost:** per-client rate limiting (429) on the expensive endpoints, a
  daily spend cap (durable across restarts), and a bounded concurrency pool.
- **Operator endpoints** (`/evaluate`, `/adjudicate`, `/api/metrics`,
  `/api/admin/*`) gated behind `X-Admin-Token` when `MDPLUS_ADMIN_TOKEN` is set.
- **Data at rest:** uploaded denial letters + OCR text sealed with envelope
  AES-256-GCM when a key is configured (pair with host volume encryption).
- **SSRF:** the fetch tool blocks loopback/link-local/private hosts and non-HTTP
  schemes (`scripts/policy_eval/webtools.py`).
- **Input bounds:** request-body cap; episode ids validated against a strict
  pattern (no path traversal).
- **Integrity:** hash-chained episode/message logs; frozen results are immutable.
- **Data lifecycle:** scheduled retention purge + a per-episode deletion endpoint;
  scheduled backups with a consistent SQLite copy and a documented restore drill.

## Pre-launch checklist

- [ ] Secrets are in `/etc/mdplus/mdplus.env` (chmod 600), **not** in the repo or
      the systemd unit. `ANTHROPIC_API_KEY`, `WEB_SEARCH_API_KEY` set.
- [ ] `MDPLUS_ADMIN_TOKEN` set to a strong random value.
- [ ] `MDPLUS_TRUST_PROXY=true` and the app bound to `127.0.0.1` behind the proxy;
      the app port is **not** reachable publicly.
- [ ] TLS works and HTTP redirects to HTTPS; certificate auto-renews.
- [ ] `MDPLUS_DAILY_BUDGET_USD` set to a sane cap; prices set to real values.
- [ ] `MDPLUS_ENCRYPTION_KEY` set (and backed up in a secret manager); host volume
      encryption on.
- [ ] `MDPLUS_RETENTION_DAYS` matches the Privacy Notice; purge timer enabled.
- [ ] Backup timer enabled; **restore drill performed once** end-to-end.
- [ ] Uptime check on `/api/health` alerting on `degraded: true`;
      `MDPLUS_ALERT_WEBHOOK` set.
- [ ] Privacy Notice & Terms finalized by counsel; bracketed fields filled.
- [ ] BAA signed with the model provider (and any subprocessors).
- [ ] Placeholder per-state payer directory replaced with real data.
- [ ] Ran `scripts/readiness_check.py https://<domain>` — reports READY.

## Run the readiness check

```bash
python3 scripts/readiness_check.py https://appeals.example.com
```
Confirms health is not degraded, the server handles concurrent requests, and the
rate limiter engages. Exit code is non-zero on failure, so it can gate a deploy.

## Known limits / follow-ons

- Field-level encryption of message bodies + the SQLite DB is not yet done (rely
  on volume encryption meanwhile).
- No user accounts yet; plans are anonymous, keyed by episode id in the browser.
- The in-process rate limiter is per-instance; add an edge limiter if you run
  multiple instances.
- A third-party penetration test is recommended before scaling to real patients.
