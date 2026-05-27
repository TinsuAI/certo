#!/usr/bin/env bash
# backup-data-hub.sh — daily full Data Hub backup (Compose deploy).
#
# Captures three artifacts to $BACKUP_ROOT:
#   db-YYYY-MM-DD.dump          pg_dump custom format (compressed)
#   appfiles-YYYY-MM-DD.tar.zst tar of the appfiles volume (uploaded XLS/PDF blobs)
#   appkeys-YYYY-MM-DD.tar.zst  tar of the appkeys volume (JWT signing keys)
#   status-YYYY-MM-DD.txt       PASS|FAIL with per-step details
#
# Each artifact is verified after write (pg_restore --list / zstd -t).
# Older artifacts are pruned by RETAIN_DAYS (default 30).
# Designed for `tinsu` user cron, no sudo required.

set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/home/tinsu/data-hub}"
DB_SERVICE="${DB_SERVICE:-db}"
APP_SERVICE="${APP_SERVICE:-app}"
DB_NAME="${DB_NAME:-data_hub}"
DB_USER="${DB_USER:-hub}"
BACKUP_ROOT="${BACKUP_ROOT:-/home/tinsu/backups/data-hub}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"

today=$(date +%F)
status_file="${BACKUP_ROOT}/status-${today}.txt"

mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"

cd "$COMPOSE_DIR"

# Resolve actual volume names (project_prefix + suffix) once
proj=$(basename "$COMPOSE_DIR")
appfiles_vol="${proj}_appfiles"
appkeys_vol="${proj}_appkeys"

log() { echo "[$(date '+%F %T')] $*"; }
declare -a errors=()

# --- Step 1: Postgres dump --------------------------------------------------
db_target="${BACKUP_ROOT}/db-${today}.dump"
log "pg_dump → $db_target"
if docker compose exec -T "$DB_SERVICE" \
        pg_dump --format=custom --no-owner --no-privileges \
                -U "$DB_USER" -d "$DB_NAME" > "${db_target}.tmp"; then
    mv "${db_target}.tmp" "$db_target"
    if docker compose exec -T "$DB_SERVICE" \
            pg_restore --list < "$db_target" >/dev/null 2>&1; then
        log "  ok: $(du -h "$db_target" | cut -f1)"
    else
        errors+=("db_verify: pg_restore --list failed on $db_target")
    fi
else
    errors+=("db_dump: pg_dump exited non-zero")
    rm -f "${db_target}.tmp"
fi

# --- Step 2 & 3: Volume tar (appfiles + appkeys) ----------------------------
# Mount the named volume read-only into a throwaway alpine container and
# stream tar | zstd back to the host. No app downtime: docker handles
# concurrent read of the volume contents.
backup_volume() {
    local vol="$1" label="$2"
    local target="${BACKUP_ROOT}/${label}-${today}.tar.zst"
    log "tar volume $vol → $target"
    if docker run --rm \
            -v "${vol}:/source:ro" \
            -v "${BACKUP_ROOT}:/out" \
            alpine:3.20 \
            sh -c "apk add --quiet --no-cache zstd tar >/dev/null && \
                   tar -C /source -cf - . | zstd -q -3 -o /out/${label}-${today}.tar.zst.tmp" \
            >/dev/null 2>&1; then
        mv "${target}.tmp" "$target"
        # Verify the zstd stream
        if zstd -q -t "$target" 2>/dev/null; then
            log "  ok: $(du -h "$target" | cut -f1)"
        else
            errors+=("${label}_verify: zstd -t failed on $target")
        fi
    else
        errors+=("${label}_tar: docker run tar | zstd failed")
        rm -f "${target}.tmp"
    fi
}

backup_volume "$appfiles_vol" appfiles
backup_volume "$appkeys_vol" appkeys

# --- Step 4: Prune -----------------------------------------------------------
log "prune older than ${RETAIN_DAYS} days"
find "$BACKUP_ROOT" -maxdepth 1 \
    \( -name 'db-*.dump' -o -name 'appfiles-*.tar.zst' \
       -o -name 'appkeys-*.tar.zst' -o -name 'status-*.txt' \) \
    -mtime "+${RETAIN_DAYS}" -delete

# --- Step 5: Write status ---------------------------------------------------
if [ "${#errors[@]}" -eq 0 ]; then
    {
        echo "PASS"
        echo "date=${today}"
        echo "db=$(du -h "$db_target" 2>/dev/null | cut -f1 || echo missing)"
        echo "appfiles=$(du -h "${BACKUP_ROOT}/appfiles-${today}.tar.zst" 2>/dev/null | cut -f1 || echo missing)"
        echo "appkeys=$(du -h "${BACKUP_ROOT}/appkeys-${today}.tar.zst" 2>/dev/null | cut -f1 || echo missing)"
    } > "$status_file"
    log "PASS"
    rm -f "${BACKUP_ROOT}/ALARM"
else
    {
        echo "FAIL"
        echo "date=${today}"
        for e in "${errors[@]}"; do echo "error=$e"; done
    } > "$status_file"
    echo "FAIL on ${today}: ${errors[*]}" > "${BACKUP_ROOT}/ALARM"
    log "FAIL (${#errors[@]} errors)"
    exit 1
fi
