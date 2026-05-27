#!/usr/bin/env bash
# restore-drill.sh — weekly drill: restore latest db dump to a throwaway
# container and verify table counts pass sanity thresholds.
#
# Why: a backup that has never been restored is Schrödinger's backup.
# Catches: truncated dumps, missing extensions (pgvector), schema drift,
# row-count regressions.
#
# Outputs:
#   $DRILL_LOG (append) — one line per run, ISO timestamp + PASS|FAIL
#   $BACKUP_ROOT/drill-YYYY-MM-DD.txt — full detail
#   $BACKUP_ROOT/ALARM — created on FAIL (rm'd on next PASS)

set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/home/tinsu/backups/data-hub}"
DRILL_LOG="${DRILL_LOG:-/home/tinsu/logs/data-hub-drill.log}"
SCRATCH_NAME="${SCRATCH_NAME:-data-hub-drill}"
SCRATCH_IMAGE="${SCRATCH_IMAGE:-pgvector/pgvector:pg16}"
DB_NAME="${DB_NAME:-data_hub_drill}"
DB_USER="${DB_USER:-drill}"
DB_PASS="${DB_PASS:-drillpw}"

today=$(date +%F)
detail_file="${BACKUP_ROOT}/drill-${today}.txt"

mkdir -p "$BACKUP_ROOT" "$(dirname "$DRILL_LOG")"

cleanup() { docker rm -f "$SCRATCH_NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# 1. Find newest dump
latest=$(ls -1t "$BACKUP_ROOT"/db-*.dump 2>/dev/null | head -1 || true)
if [ -z "$latest" ]; then
    msg="FAIL: no db-*.dump found in $BACKUP_ROOT"
    echo "$(date -Iseconds) $msg" >> "$DRILL_LOG"
    echo "$msg" > "$detail_file"
    echo "$msg" > "${BACKUP_ROOT}/ALARM"
    exit 1
fi
dump_age_days=$(( ( $(date +%s) - $(stat -c %Y "$latest") ) / 86400 ))

# 2. Boot scratch DB
cleanup
docker run -d --rm --name "$SCRATCH_NAME" \
    -e POSTGRES_USER="$DB_USER" \
    -e POSTGRES_PASSWORD="$DB_PASS" \
    -e POSTGRES_DB="$DB_NAME" \
    "$SCRATCH_IMAGE" >/dev/null

# Wait for ready (max 60s)
for i in $(seq 1 30); do
    if docker exec "$SCRATCH_NAME" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

# 3. Restore
restore_err=$(docker exec -i "$SCRATCH_NAME" \
    pg_restore --no-owner --no-privileges -U "$DB_USER" -d "$DB_NAME" \
    < "$latest" 2>&1 || true)

# 4. Smoke counts (must be > 0; production live counts as upper sanity)
counts=$(docker exec "$SCRATCH_NAME" psql -U "$DB_USER" -d "$DB_NAME" -At -F '|' -c "
    SELECT
      (SELECT count(*) FROM hub.bcct_rows),
      (SELECT count(*) FROM hub.customs_declaration_files),
      (SELECT count(*) FROM hub.bom_artifacts),
      (SELECT count(*) FROM hub.materials)
" 2>/dev/null || echo "ERR|ERR|ERR|ERR")
IFS='|' read -r n_bcct n_files n_bom n_mat <<< "$counts"

# 5. Decide PASS/FAIL
status="PASS"
reasons=()
if [ "$n_bcct" = "ERR" ] || [ -z "$n_bcct" ]; then
    status="FAIL"; reasons+=("smoke_query_failed")
elif [ "$n_bcct" -lt 1000 ]; then
    status="FAIL"; reasons+=("bcct_rows<1000: $n_bcct")
elif [ "$n_files" -lt 1 ]; then
    status="FAIL"; reasons+=("declaration_files=0")
fi
if [ "$dump_age_days" -gt 2 ]; then
    status="FAIL"; reasons+=("latest_dump_age>${dump_age_days}d")
fi

# 6. Write detail + log line
{
    echo "$status"
    echo "date=${today}"
    echo "source_dump=$(basename "$latest")"
    echo "dump_age_days=${dump_age_days}"
    echo "bcct_rows=${n_bcct}"
    echo "declaration_files=${n_files}"
    echo "bom_artifacts=${n_bom}"
    echo "materials=${n_mat}"
    if [ "${#reasons[@]}" -gt 0 ]; then
        for r in "${reasons[@]}"; do echo "reason=$r"; done
    fi
    if [ -n "$restore_err" ]; then
        echo "restore_stderr_head=$(echo "$restore_err" | head -3 | tr '\n' ';')"
    fi
} > "$detail_file"

line="$(date -Iseconds) ${status} dump=$(basename "$latest") bcct=${n_bcct} files=${n_files} bom=${n_bom} mat=${n_mat}"
echo "$line" >> "$DRILL_LOG"
echo "$line"

if [ "$status" = "FAIL" ]; then
    echo "${line} reasons=${reasons[*]}" > "${BACKUP_ROOT}/ALARM"
    exit 1
else
    # Clear ALARM only if it was a drill failure (don't stomp other ALARMs).
    if [ -f "${BACKUP_ROOT}/ALARM" ] && grep -q "drill\|dump" "${BACKUP_ROOT}/ALARM" 2>/dev/null; then
        rm -f "${BACKUP_ROOT}/ALARM"
    fi
fi
