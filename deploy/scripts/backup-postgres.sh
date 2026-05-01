#!/bin/bash
# backup-postgres.sh — daily Data Hub database dump.
# Install via:
#   sudo install deploy/scripts/backup-postgres.sh /usr/local/bin/
# Schedule:
#   /etc/cron.d/data-hub: 30 2 * * * hub /usr/local/bin/backup-postgres.sh

set -euo pipefail

DB_NAME="${DB_NAME:-data_hub}"
DB_USER="${DB_USER:-hub_app}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/data-hub}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"

today=$(date +%F)
target="${BACKUP_ROOT}/${today}.dump"

mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"

# pg_dump uses the role's pg_hba auth (peer / md5 via .pgpass).
# --format=custom is compressed + supports parallel restore.
pg_dump --format=custom --no-owner --no-privileges \
        -U "$DB_USER" -d "$DB_NAME" \
        -f "$target".tmp
mv "$target".tmp "$target"

# Verify the dump opens (catches "I/O error during pg_dump")
pg_restore --list "$target" >/dev/null

# Prune older than RETAIN_DAYS
find "$BACKUP_ROOT" -maxdepth 1 -name '*.dump' -mtime "+$RETAIN_DAYS" -delete

# Optional: ship to S3-compatible (uncomment + configure)
# aws s3 cp "$target" "s3://${S3_BUCKET:-data-hub-backups}/$today.dump" \
#   --endpoint-url "${S3_ENDPOINT:-https://s3.amazonaws.com}"

echo "ok: $target ($(du -h "$target" | cut -f1))"
