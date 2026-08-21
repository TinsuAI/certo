#!/usr/bin/env bash
# prune-render-cache.sh — bound the declaration PDF render cache.
#
# render_cache/ holds LibreOffice-rendered declaration PDFs, content-addressed
# by source .xls sha256 (see app/declarations_pdf.py). It is a pure cache: a
# miss re-renders on the fly, so eviction never costs correctness — only a one-
# time re-render. Left unbounded it grew to ~24G and filled the host disk
# (prod outage 2026-06-12). This caps it by age then by total size (LRU).
#
# Two-stage eviction against the appfiles volume:
#   1. TTL   — delete entries older than RENDER_CACHE_TTL_DAYS (default 30)
#   2. SIZE  — if still over RENDER_CACHE_MAX_GB (default 6), delete oldest
#              (by mtime) until under budget
#
# Runs read-mostly via a throwaway alpine container; no app downtime, works
# whether the app is up or down. Designed for `tinsu` user cron, no sudo.

set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/home/tinsu/data-hub}"
VOL="${RENDER_CACHE_VOL:-$(basename "$COMPOSE_DIR")_appfiles}"
TTL_DAYS="${RENDER_CACHE_TTL_DAYS:-30}"
MAX_GB="${RENDER_CACHE_MAX_GB:-6}"

echo "[$(date '+%F %T')] prune render_cache: vol=$VOL ttl=${TTL_DAYS}d cap=${MAX_GB}G"

docker run --rm -i -v "${VOL}:/f" alpine:3.20 sh -s "$TTL_DAYS" "$MAX_GB" <<'INNER'
set -eu
TTL="$1"; MAXGB="$2"
D=/f/render_cache
[ -d "$D" ] || { echo "  no render_cache dir — nothing to do"; exit 0; }
apk add --quiet --no-cache findutils coreutils >/dev/null 2>&1 || true

before=$(du -sh "$D" 2>/dev/null | cut -f1)

# Stage 1: TTL
find "$D" -type f -mtime "+${TTL}" -delete 2>/dev/null || true

# Stage 2: size-cap LRU (oldest mtime first)
max=$(( MAXGB * 1024 * 1024 * 1024 ))
cur=$(du -sb "$D" 2>/dev/null | cut -f1 || echo 0)
if [ "$cur" -gt "$max" ]; then
    find "$D" -type f -printf '%T@\t%s\t%p\n' 2>/dev/null | sort -n | \
    while IFS="$(printf '\t')" read -r _t s p; do
        [ "$cur" -le "$max" ] && break
        rm -f "$p" && cur=$(( cur - s ))
    done
fi
# prune now-empty dirs
find "$D" -mindepth 1 -type d -empty -delete 2>/dev/null || true

after=$(du -sh "$D" 2>/dev/null | cut -f1 || echo 0)
echo "  render_cache: ${before:-0} -> ${after:-0}"
INNER
