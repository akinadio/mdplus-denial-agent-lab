# Deploying OrthoAppeals (public, with TLS)

The service is designed to run as one managed process behind a TLS-terminating
reverse proxy. This puts HTTPS in front (the remaining Phase 3 blocker) without
the app having to manage certificates.

## Shape

```
  patient's browser ──HTTPS──▶ reverse proxy (Caddy/nginx) ──HTTP──▶ 127.0.0.1:8781 (harness)
```

The harness binds to localhost only; the proxy is the sole public listener and
terminates TLS. The proxy sets `X-Forwarded-Proto`/`X-Forwarded-For`, which the
app honors when `MDPLUS_TRUST_PROXY=true` (so it emits HSTS and rate-limits by
the real client IP).

## Steps

1. **Install the app and dependencies**
   ```bash
   cd /home/clawd/mdplus-denial-agent-lab
   pip install -e .          # anthropic + requests
   pip install -e '.[fetch]' # optional: brotli/zstd page decoding
   (cd ui && npm ci && npm run build)   # server refuses to start without ui/dist
   ```

2. **Configure secrets and settings**
   ```bash
   sudo mkdir -p /etc/mdplus
   sudo cp deploy/mdplus.env.example /etc/mdplus/mdplus.env
   sudo chmod 600 /etc/mdplus/mdplus.env
   sudo nano /etc/mdplus/mdplus.env   # fill in ANTHROPIC_API_KEY, WEB_SEARCH_API_KEY, etc.
   ```

3. **Install the service** (auto-restart, starts on boot, loads the env file)
   ```bash
   sudo cp deploy/mdplus-harness.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now mdplus-harness
   sudo systemctl status mdplus-harness
   ```

4. **Put TLS in front** — pick one:

   **Caddy (automatic HTTPS, simplest):**
   ```bash
   sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
   sudo nano /etc/caddy/Caddyfile     # set your domain
   sudo systemctl reload caddy
   ```

   **nginx + certbot:**
   ```bash
   sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/mdplus
   sudo ln -s /etc/nginx/sites-available/mdplus /etc/nginx/sites-enabled/
   sudo certbot --nginx -d appeals.example.com
   sudo nginx -t && sudo systemctl reload nginx
   ```

5. **Verify**
   ```bash
   curl -s https://appeals.example.com/api/health | python3 -m json.tool
   ```
   `degraded` should be `false`. If it lists reasons (missing key, UI not built,
   budget paused), fix those first. Then open `https://appeals.example.com/` —
   it redirects to the patient intake.

## Operating notes

- **Logs:** `journalctl -u mdplus-harness -f` (and `harness_server.log`).
- **Health/alerting:** point an uptime check at `/api/health` and alert on
  `degraded: true`; set `MDPLUS_ALERT_WEBHOOK` to get failed runs pushed to a
  channel.
- **Cost:** `MDPLUS_DAILY_BUDGET_USD` caps daily model spend (durable across
  restarts); rate limits bound per-client load. Watch spend under
  `/api/health → spend`.
- **Restarts are safe:** in-flight runs are reconciled to `interrupted` on
  startup and are retryable; the budget survives restarts.
- **Backups:** enable the daily backup timer and set `MDPLUS_BACKUP_DIR` to
  encrypted, ideally off-box storage:
  ```bash
  sudo cp deploy/mdplus-backup.service deploy/mdplus-backup.timer /etc/systemd/system/
  sudo systemctl enable --now mdplus-backup.timer
  ```
  Each backup is a `mdplus-backup-<UTC>.tar.gz` with the episodes directory and a
  consistent SQLite copy.
- **Retention:** set `MDPLUS_RETENTION_DAYS` and enable the purge timer
  (`mdplus-purge.timer`) so old records are deleted per your Privacy Notice.

## Restore drill (practice this before you need it)

```bash
sudo systemctl stop mdplus-harness
cd /home/clawd/mdplus-denial-agent-lab
tar -tzf /path/to/mdplus-backup-<UTC>.tar.gz | head        # inspect
# restore episodes and the DB (adjust paths to your MDPLUS_* settings):
tar -xzf /path/to/mdplus-backup-<UTC>.tar.gz -C /tmp/restore
rsync -a --delete /tmp/restore/episodes/ outputs/synthetic_patient_simulations/episodes/
cp /tmp/restore/state.sqlite3 outputs/state.sqlite3
sudo systemctl start mdplus-harness
curl -s https://appeals.example.com/api/health | python3 -m json.tool
```
Do this end-to-end at least once so a real recovery isn't the first attempt.

## Still required before real patients (see docs/trust_and_compliance.md)

Encryption at rest, a BAA with the model provider + HIPAA assessment,
retention/deletion automation, and finalizing the legal template with counsel.
