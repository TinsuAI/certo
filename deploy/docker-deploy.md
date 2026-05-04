# Docker Compose deploy

Target: Linux host with Docker and git installed. Demo workflow:
local dev -> push GitHub -> server pulls -> `docker compose up -d --build`.

## One-time server setup

```bash
git clone <git-url> ~/co
cd ~/co
cp .env.example .env
chmod 0600 .env
```

Edit `.env`:

- keep `APP_PORT=8755`; Data Hub uses `8754` on the same demo host
- set `POSTGRES_PASSWORD`
- set `CO_PUBLIC_BASE_URL` to the private CO URL ending in `:8755`
- set `DATA_HUB_BASE_URL`, `DATA_HUB_API_BASE_URL`, and `DATA_HUB_ISSUER_URL` to the private Data Hub root URL ending in `:8754`
- set `DATA_HUB_JWKS_URL` to the Data Hub root URL plus `/v1/auth/jwks`
- leave `DATA_HUB_API_TOKEN` blank when Data Hub API auth is disabled
- set the LLM variables if CO has LLM-backed behavior enabled

## Seed or restore CO-owned state

The dump is not committed. Copy it into `data/seed/` on the server:

```bash
mkdir -p data/seed
scp data/seed/co-demo.dump <user>@<host>:~/co/data/seed/co-demo.dump
```

Then restore it before starting the app:

```bash
docker compose up -d db
docker compose exec -T db sh -c \
  'until pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do sleep 1; done'
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c 'DROP SCHEMA IF EXISTS co CASCADE; CREATE SCHEMA co;'
docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --no-owner --no-privileges /seed/co-demo.dump
docker compose up -d --build app
```

For a blank CO state, skip `pg_restore`; app startup applies migrations.
Master data still comes from Data Hub when `DATA_HUB_ENABLED=1`.

## Routine deploy

```bash
git pull
docker compose up -d --build
docker compose logs -f app
```

## Checks

```bash
curl -fsS http://127.0.0.1:8755/healthz
docker compose exec app curl -fsS "$DATA_HUB_API_BASE_URL/v1/hub/dncxs"
docker compose exec app curl -fsS "$LLM_BASE_URL/models"
```

## Persistence

| Volume | Path | Holds |
| --- | --- | --- |
| `pgdata` | `/var/lib/postgresql/data` | CO Postgres database, schema `co` |
| `appdata` | `/var/lib/barry-co` | CO runtime config and uploaded files |
