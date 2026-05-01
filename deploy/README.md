# Data Hub deployment scaffold (M9 #6)

Files in this directory describe how to run Data Hub in production. None
of them is invoked automatically — they are templates the operator
copies, customises, and installs on the target host.

## Layout

```
deploy/
├── README.md               (this file)
├── env.template            (env vars Data Hub reads)
├── systemd/
│   └── data-hub.service    (systemd unit for the FastAPI app)
├── nginx/
│   └── data-hub.conf       (reverse-proxy + TLS termination)
├── scripts/
│   ├── backup-postgres.sh  (pg_dump → S3-compatible / local file)
│   └── rotate-keys.sh      (Ed25519 keypair rotation SOP)
└── runbook.md              (ops cheat-sheet: deploy, rotate, restore)
```

## Target shape (1 VPS, 3 systemd units)

Per the architecture decision (`~/workspace/client/BCQT-System/.ai/
DECISIONS.md` → "2026-04-30 PM — Data Hub 3-app architecture"):

```
host: data-hub.example
├── postgres (single instance)
│   ├── role: hub_app  → owns hub.* schema, full DDL/DML
│   ├── role: bcqt_app → owns bcqt.*, READ-ONLY on hub.*
│   └── role: co_app   → owns co.*,   READ-ONLY on hub.* (writes via API)
├── systemd
│   ├── data-hub.service   (this app, port :8754)
│   ├── bcqt.service       (BCQT-System,  port :8755)
│   └── co.service         (CO-System,    port :8756)
├── /var/lib/data-hub/files     (LocalFS uploads, S3-compat phase 2)
├── /etc/data-hub/keys/         (Ed25519 keypairs, 0400 root:hub)
├── /etc/data-hub/.env          (secrets, 0440 root:hub)
└── nginx → :443 + Let's Encrypt → routes by Host header to the 3 apps
```

## First-time install

```bash
# 1. System deps
apt install -y postgresql nginx
# 2. Clone + build
sudo -u hub git clone <repo> /opt/data-hub && cd /opt/data-hub
sudo -u hub uv sync --frozen
# 3. DB
sudo -u postgres createuser hub_app -P
sudo -u postgres createdb data_hub -O hub_app
# 4. Config
sudo install -m 0440 -o root -g hub deploy/env.template /etc/data-hub/.env
sudo $EDITOR /etc/data-hub/.env  # set DATABASE_URL, SEED_*, etc.
sudo install -d -m 0700 -o root -g hub /etc/data-hub/keys
# 5. systemd
sudo install deploy/systemd/data-hub.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now data-hub
# 6. nginx
sudo install deploy/nginx/data-hub.conf /etc/nginx/sites-available/
sudo ln -s ../sites-available/data-hub.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
# 7. Backup cron
sudo install deploy/scripts/backup-postgres.sh /usr/local/bin/
sudo install deploy/scripts/rotate-keys.sh /usr/local/bin/
sudo install -m 0644 deploy/cron.d/data-hub /etc/cron.d/
```

## Services & dependencies (post phase 1)

- Data Hub MVP needs only Postgres + LocalFS. No Redis. No queue.
- LLM endpoint (vLLM / OpenAI / Anthropic via OAI shim) configurable via
  `/admin/settings/technical` UI — operator does not need to wire env
  vars for LLM at deploy time.

## Backup strategy

- `pg_dump --format=custom data_hub` → `/var/backups/data-hub/YYYY-MM-DD.dump`
- Daily via cron, retain 30 days locally + lifecycle to S3 monthly.
- File uploads (`/var/lib/data-hub/files/`) are content-addressed
  (sha256). Backup via `restic` to the same S3.
- Key rotation ≠ backup: rotated old keys MUST stay in `keys/` until
  every issued token has expired (10 min default), then they can be
  archived separately. See `rotate-keys.sh`.

## Restore drill (quarterly)

1. Spin up clean VPS.
2. `pg_restore` the latest dump.
3. Restore `keys/` from secret-archive vault.
4. Restore `/var/lib/data-hub/files/` from restic.
5. Boot data-hub.service. Verify `/healthz` + login.
6. Smoke: list clients, view BCCT, run agent query — all from UI.
