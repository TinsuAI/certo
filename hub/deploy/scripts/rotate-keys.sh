#!/bin/bash
# rotate-keys.sh — Ed25519 SSO keypair rotation.
#
# Procedure:
#   1. Generate new keypair {kid}.private.pem + {kid}.public.pem in
#      DATA_HUB_KEYS_DIR.
#   2. Restart the service so the new key shows up in JWKS.
#   3. Wait JWKS_CACHE_TTL (default 600s) for consumer caches to expire
#      and refetch — JWKS now publishes BOTH old + new keys.
#   4. Flip sso_active_kid in app_settings to the new kid.
#   5. Wait token TTL (default 600s) for old tokens to expire.
#   6. Optional: archive the old keypair off the live host.
#
# Usage: sudo ./rotate-keys.sh [new-kid]
#   new-kid defaults to k$(date +%Y%m%d)

set -euo pipefail

KEYS_DIR="${DATA_HUB_KEYS_DIR:-/etc/data-hub/keys}"
NEW_KID="${1:-k$(date +%Y%m%d)}"

if [ -f "$KEYS_DIR/$NEW_KID.private.pem" ]; then
    echo "error: $NEW_KID already exists" >&2
    exit 1
fi

# Generate Ed25519 keypair using openssl (no Python needed for this step).
priv="$KEYS_DIR/$NEW_KID.private.pem"
pub="$KEYS_DIR/$NEW_KID.public.pem"

openssl genpkey -algorithm ed25519 -out "$priv"
openssl pkey -in "$priv" -pubout -out "$pub"
chown root:hub "$priv" "$pub"
chmod 0400 "$priv"
chmod 0444 "$pub"

echo "ok: generated $priv + $pub"
echo
echo "Next steps:"
echo "  1. systemctl restart data-hub  # picks up new key into JWKS"
echo "  2. Verify: curl -s https://your-host/v1/auth/jwks | jq '.keys[].kid'"
echo "     should now show: $NEW_KID + the previous active kid"
echo "  3. Wait ~10 minutes for consumer JWKS caches to refresh"
echo "  4. Open /admin/settings/technical and set sso_active_kid=$NEW_KID"
echo "     (or psql: update hub.app_settings set value=$NEW_KID where key=sso_active_kid;)"
echo "  5. Wait another ~10 minutes for old-key tokens to expire"
echo "  6. Optional: move the old keypair to your secret archive."
