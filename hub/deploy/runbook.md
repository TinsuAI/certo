# Operations runbook

For the on-call human. Things that go wrong and how to fix them.

> **Note (2026-05-04)**: this runbook used to assume a host-systemd
> deployment. The live demo is Docker Compose on the `tinsu` host.
> Sections below are written for the Compose deploy. The
> systemd-era flow is preserved at the bottom under
> [Legacy: systemd host-deploy notes](#legacy-systemd-host-deploy-notes)
> for reference.
>
> The canonical **restore procedure** for the Compose deploy lives
> in [`docs/release-engineering.md`](../docs/release-engineering.md)
> §5. This file forwards to it; do not duplicate the procedure.

## Common operations

### Restart the service

```bash
ssh tinsu@100.84.189.87 \
  'cd ~/data-hub && docker compose restart app'

# Tail logs
ssh tinsu@100.84.189.87 \
  'cd ~/data-hub && docker compose logs -f --tail=100 app'
```

(WSL → Windows ssh.exe rule applies; use
`/mnt/c/Windows/System32/OpenSSH/ssh.exe` if WSL `ssh` is broken.)

### Apply a migration

Migrations live in `db/migrations/NNN_*.sql` and run automatically
at app boot via `app.database.apply_migrations()`. The runner is
idempotent — already-applied filenames are skipped via
`hub.schema_migrations`.

To check what's been applied:

```bash
ssh tinsu@... 'cd ~/data-hub && \
  docker compose exec -T db psql -U hub -d data_hub \
    -c "select filename, applied_at from hub.schema_migrations \
        order by applied_at desc;"'
```

To apply manually (rare — only if you need a migration to run
without a full app restart):

```bash
ssh tinsu@... 'cd ~/data-hub && \
  docker compose exec -T db psql -U hub -d data_hub \
    -f /docker-entrypoint-initdb.d/0NN_xxx.sql'
# Note: the migrations dir is not bind-mounted into the db container
# by default — usually easier to redeploy and let lifespan apply.
```

### Check LLM usage

```bash
ssh tinsu@... 'cd ~/data-hub && \
  docker compose exec -T db psql -U hub -d data_hub -c "
    select date, client_id, call_count
    from hub.llm_usage
    where date >= current_date - interval '\''7 days'\''
    order by date desc, call_count desc;"'
```

### Reset a user's password (admin operation)

Use `/admin/users` in the UI — the "edit user" form has a password
field. There is no CLI password reset by design (forces all auth
changes to go through the audit log).

If the only admin's password is forgotten and there's no other
admin to reset it: see `data-hub` session memory file
`feedback_use_python_heredoc.md` for the python-heredoc reset trick
(quoted heredoc to avoid shell escape bugs); applies via
`docker compose exec -T app python << "PY" ... PY`.

## Common failure modes

### App won't start: `column "X" does not exist`

A migration partially applied. Tail the app logs:

```bash
ssh tinsu@... 'cd ~/data-hub && docker compose logs --tail=80 app'
```

Then check what's recorded:

```bash
docker compose exec -T db psql -U hub -d data_hub \
  -c "select filename from hub.schema_migrations \
      order by applied_at desc limit 5;"
```

If the failing migration **isn't** in `schema_migrations`, it
rolled back — fix the SQL, redeploy, lifespan re-applies. If it
**is** in there but a referenced column is missing, the migration
was recorded but partially applied. Rewind:

```bash
docker compose exec -T db psql -U hub -d data_hub \
  -c "delete from hub.schema_migrations \
      where filename='0NN_failed.sql';"
# fix the SQL, redeploy.
```

### App won't start: JWT keypair permission / missing

The keys volume is mounted at `/var/lib/data-hub/keys` inside the
container (compose volume `appkeys`). The app generates an ed25519
keypair on first boot and reuses it.

If keys are corrupted or missing on the demo host, the cleanest
recovery is:

```bash
docker compose down
docker volume rm data-hub_appkeys
docker compose up -d
# App regenerates a fresh keypair on boot.
```

Consequences: any consumer holding a JWT issued by the previous
keypair will see "invalid token" until they refetch JWKS (≤10 min
cache TTL by default).

### LLM upload fails for one client

Verify the LLM config in `hub.app_settings`:

```bash
docker compose exec -T db psql -U hub -d data_hub \
  -c "select key, value from hub.app_settings where key like 'llm_%';"
```

Or via UI: `/admin/settings/technical`. LLM disabled = upload route
surfaces a "configure LLM" message — not a 500.

If quota exhausted: bump `llm_max_calls_per_day_per_client` in
`hub.app_settings`, OR wait until midnight UTC for the daily
counter to reset.

### Storage filling up: files volume

Files are content-addressed (sha256). Same-content uploads dedupe.
Excess size is genuine retention pressure. Tier-D demo has no
automatic purge — the regulatory requirement is 5-10 year retention
per TT 39/2018 anyway.

```bash
ssh tinsu@... \
  'docker compose exec -T app du -sh /var/lib/data-hub/files'
```

If genuinely tight: snapshot to S3 + delete locally older than 30
days. Tier-2 backup uplift covers off-site shipping for files —
see [`docs/release-engineering.md`](../docs/release-engineering.md)
§5.

### "Provenance alarm spam" — staff getting too many notifications

Reduce the alarm to email-summary-only (TBD in phase 2). For now,
bulk mark-read via `/notifications/read-all`, OR:

```bash
docker compose exec -T db psql -U hub -d data_hub -c "
  update hub.notifications set status='read'
  where kind='provenance_alarm' and status='unread';"
```

### Postgres restore drill

See [`docs/release-engineering.md`](../docs/release-engineering.md)
§5 → "Restore procedure (Tier-1, Compose)" for the canonical
copy-pasteable flow against the Compose deployment.

## Cross-app coordination

When a Data Hub schema change affects sister apps:

1. Update `db/migrations/` here.
2. Update the consuming app's adapter:
   - BCQT-System: `~/workspace/client/BCQT-System/app/adapters/data_hub_*`
   - CO: `~/workspace/client/barry-CO-main/app/adapters/data_hub_*`
3. Document in `~/workspace/client/BCQT-System/.ai/DECISIONS.md` AND
   here in `.ai/DECISIONS.md`. Cross-link.

Roll out order: Data Hub schema → Data Hub deploy → consumer
adapter updates → consumer deploy. **NEVER** ship a consumer
adapter expecting a schema change before the schema is live in
Data Hub.

## Monitoring (TBD)

Phase 2 candidates: prometheus exporter for FastAPI request
counters, LLM usage via `app_settings` query, notification queue
length, BOM proposal rejection rate. For now: `docker compose
logs` + `psql` ad-hoc queries.

External health probe (UptimeRobot / Healthchecks.io) is a Tier-2
uplift item — required before first paying customer per
[`docs/release-engineering.md`](../docs/release-engineering.md) §3.

---

## Legacy: systemd host-deploy notes

These commands apply to a hypothetical host-systemd deployment
shape (per `deploy/systemd/data-hub.service`). The live demo does
NOT use this shape; the Compose form above is canonical. Kept here
in case a future deployment goes back to host-systemd for
isolation reasons (e.g. running Postgres on bare metal).

```bash
# Restart
sudo systemctl restart data-hub
journalctl -u data-hub -f

# Apply a migration manually (host Postgres assumed)
sudo -u hub_app psql -d data_hub \
  -f /opt/data-hub/db/migrations/0NN_xxx.sql
sudo -u hub_app psql -d data_hub \
  -c "insert into hub.schema_migrations (filename) \
      values ('0NN_xxx.sql');"

# Keys directory permissions (host path)
sudo chown root:hub /etc/data-hub/keys/k*.private.pem
sudo chmod 0400 /etc/data-hub/keys/k*.private.pem

# Restore (host Postgres)
sudo systemctl stop data-hub
sudo -u postgres dropdb data_hub
sudo -u postgres createdb data_hub -O hub_app
sudo -u hub_app pg_restore --no-owner --no-privileges \
  -d data_hub /var/backups/data-hub/$(ls -t /var/backups/data-hub | head -1)
sudo systemctl start data-hub
```

If this section is ever needed in earnest, audit the file paths
first — `/opt/data-hub`, `/etc/data-hub/keys/`, `/var/backups/data-hub`
are documented in `deploy/env.template` and `deploy/systemd/data-hub.service`,
and may have drifted.
