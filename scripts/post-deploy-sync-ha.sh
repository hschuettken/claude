#!/usr/bin/env bash
# Post-deployment hook for syncing Home Assistant config.
#
# This script is called automatically by deploy-pull.sh after pulling
# latest changes and starting services. It syncs HomeAssistant_config/
# to the running HAOS instance and triggers config reload.
#
# Usage: Called automatically by deploy-pull.sh
#        Or manually: ./scripts/post-deploy-sync-ha.sh
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Exit gracefully if HA_TOKEN is not set (optional feature)
if [ -z "${HA_TOKEN:-}" ]; then
    if [ -f "$REPO_ROOT/.env" ]; then
        export $(grep -v "^#" "$REPO_ROOT/.env" | xargs) || true
    fi
fi

if [ -z "${HA_TOKEN:-}" ]; then
    echo "[SKIP] HA_TOKEN not set — skipping Home Assistant config sync."
    echo "       Set HA_TOKEN in .env to enable automatic HA config sync after deploy."
    exit 0
fi

# Call the sync script with a 10-second grace period for HA to start
echo "[POST-DEPLOY] Waiting 10 seconds for Home Assistant services to stabilize..."
sleep 10

echo ""
echo "[POST-DEPLOY] Syncing Home Assistant config..."
if ./scripts/sync-ha-config.sh; then
    echo ""
    echo "[POST-DEPLOY] ✓ Home Assistant config sync successful"
    exit 0
else
    echo ""
    echo "[POST-DEPLOY] ✗ Home Assistant config sync failed (non-blocking)"
    # Don't fail the entire deploy — HA sync is additive, not critical for startup
    exit 0
fi
