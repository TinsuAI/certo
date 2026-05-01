# Operations runbook

For the on-call human. Things that go wrong and how to fix them.

## Common operations

### Restart the service

```bash
sudo systemctl restart data-hub
journalctl -u data-hub -f   # tail
```

### Apply a migration

Migrations live in `db/migrations/NNN_*.sql` and run automatically at
service boot via `app.database.apply_migrations()`. The runner is
idempotent — already-applied filenames are skipped via
`hub.schema_migrations`.

To check what's been applied:

```bash
psql -d data_hub -c "select filename, applied_at from hub.schema_migrations order by applied_at desc;"
```

To apply manually (e.g. before restarting service):

```bash
sudo -u hub_app psql -d data_hub -f /opt/data-hub/db/migrations/0NN_xxx.sql
sudo -u hub_app psql -d data_hub -c "insert into hub.schema_migrations (filename) values ('0NN_xxx.sql');"
```

### Check LLM usage

```bash
psql -d data_hub -c "
select date, client_id, call_count
from hub.llm_usage
where date >= current_date - interval '7 days'
order by date desc, call_count desc;"
```

### Reset a user's password (admin operation)

Use `/admin/users` UI — the "edit user" form has a password field.
There is no CLI password reset by design (forces all auth changes to
go through the audit log).

## Common failure modes

### Service won't start: `column "X" does not exist`

A migration partially applied. Look at journalctl for the failing
migration filename.

```bash
psql -d data_hub -c "select filename from hub.schema_migrations order by applied_at desc limit 5;"
# If the failing migration ISN'T in there, it was rolled back. Fix the
# SQL and restart. If it IS in there but the column is missing, rewind:
psql -d data_hub -c "delete from hub.schema_migrations where filename='0NN_failed.sql';"
# fix the SQL, restart service.
```

### Service won't start: `keys/k1.private.pem` permission denied

```bash
ls -la /etc/data-hub/keys/
# Should be 0400 root:hub or hub:hub. Fix:
sudo chown root:hub /etc/data-hub/keys/k*.private.pem
sudo chmod 0400 /etc/data-hub/keys/k*.private.pem
```

### LLM upload fails for one client

`/admin/settings/technical` to verify base_url + model + api_key.
LLM disabled = upload route surfaces a "configure LLM" message — not
a 500.

If quota exhausted: bump `llm_max_calls_per_day_per_client` in
hub.app_settings, OR wait until midnight UTC for the daily counter to
reset.

### Storage filling up: `/var/lib/data-hub/files`

Files are content-addressed (sha256). Same-content uploads dedupe.
Excess size is genuine retention pressure. Phase 1 has no automatic
purge — the regulatory requirement is 5-10 year retention per TT
39/2018 anyway.

If genuinely tight: snapshot to S3 + delete locally older than 30 days.

### "Provenance alarm spam" — staff getting too many notifications

Reduce the alarm to email-summary-only (TBD in phase 2). For now: bulk
mark-read via /notifications/read-all, or `psql -c "update
hub.notifications set status='read' where kind='provenance_alarm' and
status='unread';"`.

### Postgres restore drill

```bash
# 1. stop the app
sudo systemctl stop data-hub
# 2. drop + recreate the db
sudo -u postgres dropdb data_hub
sudo -u postgres createdb data_hub -O hub_app
# 3. restore from latest dump
sudo -u hub_app pg_restore --no-owner --no-privileges \
  -d data_hub /var/backups/data-hub/$(ls -t /var/backups/data-hub | head -1)
# 4. restart
sudo systemctl start data-hub
```

## Cross-app coordination

When a Data Hub schema change affects sister apps:

1. Update `db/migrations/` here.
2. Update the consuming app's adapter:
   - BCQT-System: `~/workspace/client/BCQT-System/app/adapters/data_hub_*`
   - CO: `~/workspace/client/barry-CO-main/app/adapters/data_hub_*`
3. Document in `~/workspace/client/BCQT-System/.ai/DECISIONS.md` AND
   here in `.ai/DECISIONS.md`. Cross-link.

Roll out order: Data Hub schema → Data Hub deploy → consumer adapter
updates → consumer deploy. NEVER ship a consumer adapter expecting a
schema change before the schema is live in Data Hub.

## Monitoring (TBD)

Phase 2 candidates: prometheus exporter for FastAPI request counters,
LLM usage via app_settings query, notification queue length, BOM
proposal rejection rate. For now: journalctl + `psql` ad-hoc queries.
