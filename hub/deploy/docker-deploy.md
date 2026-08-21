# Docker Compose deploy (demo)

Target: any Linux box with Docker + git installed. Demo runs over a
private network (Tailscale, VPN, etc.). Workflow:
local dev → push GitHub → server pulls → `docker compose up -d --build`.

Connection details (host, user, IP) live in your local SSH config or
`.env`, not in this doc.

## One-time server bootstrap

On the server (assume Docker + git already installed):

```bash
sudo mkdir -p /opt/data-hub
sudo chown "$USER:$USER" /opt/data-hub
git clone <git-url> /opt/data-hub
cd /opt/data-hub

cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD and DATA_HUB_SEED_PASSWORD to strong values.
chmod 0600 .env
```

## Seed the demo database (one-time)

The seed dump is **not** in git — scp it from your dev box:

```bash
# On the dev box
scp data/seed/demo.dump <user>@<host>:/opt/data-hub/data/seed/demo.dump
```

Then on the server, bring up Postgres alone, restore, then bring up app:

```bash
cd /opt/data-hub
docker compose up -d db
# wait for db healthy
docker compose exec -T db sh -c \
  'until pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do sleep 1; done'

# Drop the empty hub schema the app would otherwise create, restore the dump
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c 'DROP SCHEMA IF EXISTS hub CASCADE;'
docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --no-owner --no-privileges /seed/demo.dump

docker compose up -d app
docker compose logs -f app   # check migration runner + boot
```

After this, the demo company `Demo Precision Manufacturing VN` plus the
four real-data clients (Growatt, Johnson, DKE, Do Thanh) are present.

Visit `http://<host>:8754` over your private network. Login with the
admin email/password from `.env`.

## Routine deploy (every push)

On dev:

```bash
git push origin main
```

On server:

```bash
cd /opt/data-hub
git pull
docker compose up -d --build
docker compose logs -f app
```

`apply_migrations()` runs at app boot, so new `db/migrations/NNN_*.sql`
files are applied automatically.

## Useful commands

```bash
# Tail logs
docker compose logs -f app

# Restart just the app
docker compose restart app

# Open a psql shell
docker compose exec db psql -U hub -d data_hub

# Re-build after changing pyproject.toml / uv.lock
docker compose build --no-cache app

# Stop everything (data persists in named volumes)
docker compose down

# DESTROY everything including DB (do not use casually)
docker compose down -v
```

## What persists in volumes

| Volume     | Path inside container       | Holds                                       |
|------------|-----------------------------|---------------------------------------------|
| `pgdata`   | `/var/lib/postgresql/data`  | All Postgres data (`hub` schema, users)     |
| `appfiles` | `/var/lib/data-hub/files`   | Uploaded Excel/PDFs (content-addressed)     |
| `appkeys`  | `/var/lib/data-hub/keys`    | JWT ed25519 keypairs (auto-generated boot)  |

Server-side backups can be taken with `pg_dump` against the running
container, e.g.:

```bash
docker compose exec -T db pg_dump -U hub -d data_hub --format=custom \
  > backup-$(date +%F).dump
```

## Notes

- Port `8754` binds on `0.0.0.0` by default → reachable from any
  interface, including Tailscale. If you later add nginx, set
  `APP_BIND=127.0.0.1` in `.env`.
- `DATA_HUB_AUTO_SEED_DEMO=0` is hard-set in compose; the dump from
  dev is the only source of demo data.
- Keys are persisted in the `appkeys` volume. The first boot
  generates a fresh ed25519 keypair — you do not need to copy keys
  from the dev box.
- LLM uploads will surface a "configure LLM" message until you go to
  `/admin/settings/technical` and fill in `base_url + model + api_key`.
