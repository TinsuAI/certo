#!/usr/bin/env bash
# backup-to-r2.sh — ship Data Hub backups OFFSITE to Cloudflare R2.
#
# Runs after the daily local backup (backup-data-hub.sh). Two streams:
#   - appfiles : sync the RAW appfiles volume (content-addressed .xls etc.),
#                excluding render_cache/ (regenerable). Because filenames are
#                content hashes, an incremental sync only ever uploads NEW
#                blobs — no daily re-upload, natural dedup.
#   - artifacts: mirror the local GFS-pruned db dumps + appkeys tars so R2
#                follows the same retention as local.
#
# Free-tier guard: if the bucket already holds >= R2_MAX_GB, SKIP all uploads
# and raise ALARM-R2. Daily deltas are tiny + GFS-bounded, so this keeps usage
# under Cloudflare R2's 10 GB free tier without a hard billing cap existing.
#
# rclone runs via its official Docker image (no host install). The container
# runs as the invoking uid so it can read the 0600 rclone.conf; all mounts are
# read-only. Creds live ONLY in ~/.config/rclone/rclone.conf on the box.
set -uo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/home/tinsu/data-hub}"
BACKUP_ROOT="${BACKUP_ROOT:-/home/tinsu/backups/data-hub}"
R2_REMOTE="${R2_REMOTE:-r2}"
R2_BUCKET="${R2_BUCKET:-tinsu-datahub-backups}"
R2_MAX_GB="${R2_MAX_GB:-9.5}"
APPFILES_VOL="${APPFILES_VOL:-$(basename "$COMPOSE_DIR")_appfiles}"
RCLONE_CONF_DIR="${RCLONE_CONF_DIR:-$HOME/.config/rclone}"
RCLONE_IMAGE="${RCLONE_IMAGE:-rclone/rclone:latest}"
ALARM="${BACKUP_ROOT}/ALARM-R2"

log() { echo "[$(date '+%F %T')] $*"; }

rclone_base=(docker run --rm --user "$(id -u):$(id -g)"
  -e HOME=/cfg -e RCLONE_CONFIG=/cfg/rclone.conf
  -v "${RCLONE_CONF_DIR}:/cfg:ro")

rc()     { "${rclone_base[@]}" "$RCLONE_IMAGE" "$@"; }                       # no source mount
rc_src() { local s="$1"; shift; "${rclone_base[@]}" -v "${s}:/data:ro" "$RCLONE_IMAGE" "$@"; }

bucket_bytes() {  # echoes current bucket size in bytes (0 if empty/unknown)
    rc size "${R2_REMOTE}:${R2_BUCKET}" --json 2>/dev/null \
        | tr -d ' ' | grep -oE '"bytes":[0-9]+' | grep -oE '[0-9]+' | head -1
}

max_bytes="$(awk -v g="$R2_MAX_GB" 'BEGIN{printf "%d", g*1024*1024*1024}')"

# --- Free-tier guard --------------------------------------------------------
cur="$(bucket_bytes)"; cur="${cur:-0}"
log "R2 usage: $((cur/1024/1024)) MiB / cap ${R2_MAX_GB} GiB"
if [ "$cur" -ge "$max_bytes" ]; then
    log "R2 AT/OVER CAP — skipping uploads (stay in free tier)"
    echo "R2 at/over cap ${R2_MAX_GB}G: $((cur/1024/1024)) MiB on $(date +%F)" > "$ALARM"
    exit 1
fi

errors=0

# --- appfiles: incremental raw-volume sync (excl render_cache) --------------
log "sync appfiles ${APPFILES_VOL} -> ${R2_BUCKET}/appfiles (excl render_cache)"
if ! rc_src "$APPFILES_VOL" sync /data "${R2_REMOTE}:${R2_BUCKET}/appfiles" \
        --exclude '/render_cache/**' --fast-list --transfers 8 2>&1 | sed 's/^/  /'; then
    errors=$((errors+1)); log "  appfiles sync FAILED"
fi

# --- artifacts: mirror local GFS db dumps + appkeys -------------------------
log "sync artifacts (db dumps + appkeys) -> ${R2_BUCKET}/artifacts"
if ! rc_src "$BACKUP_ROOT" sync /data "${R2_REMOTE}:${R2_BUCKET}/artifacts" \
        --include 'db-*.dump' --include 'appkeys-*.tar.zst' \
        --fast-list 2>&1 | sed 's/^/  /'; then
    errors=$((errors+1)); log "  artifacts sync FAILED"
fi

# --- post-check + alarm management ------------------------------------------
cur="$(bucket_bytes)"; cur="${cur:-0}"
log "R2 usage after: $((cur/1024/1024)) MiB"
if [ "$errors" -gt 0 ]; then
    echo "R2 sync had ${errors} error(s) on $(date +%F)" > "$ALARM"
    log "DONE with ${errors} error(s)"
    exit 1
fi
[ "$cur" -ge "$max_bytes" ] \
    && echo "R2 crossed cap ${R2_MAX_GB}G after sync: $((cur/1024/1024)) MiB" > "$ALARM" \
    || rm -f "$ALARM"
log "R2 offsite sync OK"
