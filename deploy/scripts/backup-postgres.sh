#!/bin/bash
# backup-postgres.sh — daily Data Hub database dump (Docker Compose deploy).
#
# Runs `pg_dump` inside the `db` service container, writes the dump
# to BACKUP_ROOT on the host. Designed to be called from cron on the
# Compose host (e.g. tinsu).
#
# Install:
#   sudo install deploy/scripts/backup-postgres.sh /usr/local/bin/
# Schedule:
#   /etc/cron.d/data-hub: 30 2 * * * tinsu /usr/local/bin/backup-postgres.sh

set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/home/tinsu/data-hub}"
DB_SERVICE="${DB_SERVICE:-db}"
DB_NAME="${DB_NAME:-data_hub}"
DB_USER="${DB_USER:-hub}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/data-hub}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"

today=$(date +%F)
target="${BACKUP_ROOT}/${today}.dump"

mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"

cd "$COMPOSE_DIR"

# Run pg_dump inside the db container; stream to a temp file on host.
# --format=custom is compressed + supports parallel restore.
docker compose exec -T "$DB_SERVICE" \
    pg_dump --format=custom --no-owner --no-privileges \
            -U "$DB_USER" -d "$DB_NAME" \
    > "$target".tmp
mv "$target".tmp "$target"

# Verify the dump opens (catches truncated streams).
docker compose exec -T "$DB_SERVICE" \
    pg_restore --list < "$target" >/dev/null

# Prune older than RETAIN_DAYS.
find "$BACKUP_ROOT" -maxdepth 1 -name '*.dump' -mtime "+$RETAIN_DAYS" -delete

# Optional: ship to S3-compatible (uncomment + configure).
# aws s3 cp "$target" "s3://${S3_BUCKET:-data-hub-backups}/$today.dump" \
#   --endpoint-url "${S3_ENDPOINT:-https://s3.amazonaws.com}"

echo "ok: $target ($(du -h "$target" | cut -f1))"
