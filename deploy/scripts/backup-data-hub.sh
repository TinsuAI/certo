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
# GFS retention: keep N most-recent dailies, then one-per-week (Sundays) for
# GFS_WEEKLY weeks, then one-per-month (day 01) for GFS_MONTHLY months. Decision
# is purely date-based from the filename, so it is stateless and idempotent.
GFS_DAILY="${GFS_DAILY:-7}"
GFS_WEEKLY="${GFS_WEEKLY:-8}"
GFS_MONTHLY="${GFS_MONTHLY:-6}"

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
#
# appfiles excludes render_cache/: it is a content-addressed cache of
# LibreOffice-rendered declaration PDFs, fully regenerable on demand from
# the source .xls in customs_declarations/ (a cache miss re-renders — see
# app/declarations_pdf.py). Backing it up daily wasted ~24G; the source
# .xls IS captured, so a restore loses nothing but a warm cache.
backup_volume() {
    local vol="$1" label="$2" exclude="${3:-}"
    local target="${BACKUP_ROOT}/${label}-${today}.tar.zst"
    local excl_flag=""
    [ -n "$exclude" ] && excl_flag="--exclude=${exclude}"
    log "tar volume $vol → $target${exclude:+ (excluding ${exclude})}"
    if docker run --rm \
            -v "${vol}:/source:ro" \
            -v "${BACKUP_ROOT}:/out" \
            alpine:3.20 \
            sh -c "apk add --quiet --no-cache zstd tar >/dev/null && \
                   tar -C /source ${excl_flag} -cf - . | zstd -q -3 -o /out/${label}-${today}.tar.zst.tmp" \
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

# appfiles is immutable/append-only, so a daily tar is ~identical to the
# previous day. R2 holds the current set incrementally (offsite); this local
# tar is the accidental-deletion / corruption safety net, for which weekly
# granularity suffices. Tar only on Sundays (dow=7); FORCE_APPFILES=1 overrides
# (manual runs / first seed). db dump + appkeys stay daily.
if [ "$(date +%u)" = "7" ] || [ "${FORCE_APPFILES:-0}" = "1" ]; then
    backup_volume "$appfiles_vol" appfiles "./render_cache"
    appfiles_status="$(du -h "${BACKUP_ROOT}/appfiles-${today}.tar.zst" 2>/dev/null | cut -f1)"
else
    log "skip appfiles tar (weekly: Sundays only); R2 holds current set"
    appfiles_status="skipped(weekly)"
fi
backup_volume "$appkeys_vol" appkeys

# --- Step 4: Prune (GFS) -----------------------------------------------------
# A dated artifact is KEPT when any tier claims it:
#   daily   : age <= GFS_DAILY days
#   weekly  : age <= GFS_WEEKLY weeks   AND it is a Sunday   (dow=7)
#   monthly : age <= GFS_MONTHLY months AND it is day-of-month 01
# Everything else is deleted. db dumps are tiny (~300M) so the long monthly
# tail is cheap; appfiles tars shrink further once R2 incremental is live.
now_epoch=$(date +%s)
gfs_verdict() {  # arg: YYYY-MM-DD -> echoes "keep" | "drop"
    local d="$1" epoch age_days dow dom
    epoch=$(date -d "$d" +%s 2>/dev/null) || { echo keep; return; }  # unparsable → keep
    age_days=$(( (now_epoch - epoch) / 86400 ))
    dow=$(date -d "$d" +%u 2>/dev/null)   # 1..7, 7=Sunday
    dom=$(date -d "$d" +%d 2>/dev/null)   # 01..31
    if [ "$age_days" -le "$GFS_DAILY" ]; then echo keep; return; fi
    if [ "$age_days" -le $(( GFS_WEEKLY * 7 )) ] && [ "$dow" = "7" ]; then echo keep; return; fi
    if [ "$age_days" -le $(( GFS_MONTHLY * 31 )) ] && [ "$dom" = "01" ]; then echo keep; return; fi
    echo drop
}
log "prune (GFS ${GFS_DAILY}d/${GFS_WEEKLY}w/${GFS_MONTHLY}m)"
for f in "$BACKUP_ROOT"/db-*.dump "$BACKUP_ROOT"/appfiles-*.tar.zst \
         "$BACKUP_ROOT"/appkeys-*.tar.zst "$BACKUP_ROOT"/status-*.txt \
         "$BACKUP_ROOT"/drill-*.txt; do
    [ -e "$f" ] || continue
    d=$(printf '%s\n' "$f" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1)
    [ -n "$d" ] || continue
    if [ "$(gfs_verdict "$d")" = "drop" ]; then
        rm -f "$f" && log "  pruned $(basename "$f")"
    fi
done

# --- Step 5: Write status ---------------------------------------------------
if [ "${#errors[@]}" -eq 0 ]; then
    {
        echo "PASS"
        echo "date=${today}"
        echo "db=$(du -h "$db_target" 2>/dev/null | cut -f1 || echo missing)"
        echo "appfiles=${appfiles_status:-missing}"
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
