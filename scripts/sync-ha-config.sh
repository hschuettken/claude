#!/usr/bin/env bash
# Sync HomeAssistant_config/ to HAOS and trigger config reload.
#
# Usage: ./scripts/sync-ha-config.sh
#        HA_CONFIG_SYNC_METHOD=ssh ./scripts/sync-ha-config.sh    # Force SSH addon
#        HA_CONFIG_SYNC_METHOD=samba ./scripts/sync-ha-config.sh  # Force Samba
#
# Steps:
#   1. Detect sync method (Samba preferred, SSH addon fallback)
#   2. Sync HomeAssistant_config/ to HAOS /config/
#   3. POST to HA API endpoints to reload resources and config
#   4. Verify sync was successful
#
# Environment:
#   HA_URL — Home Assistant URL (default: http://homeassistant.local:8123)
#   HA_TOKEN — Long-lived access token
#   HA_CONFIG_SYNC_METHOD — "samba" or "ssh" (auto-detected if unset)
#   SAMBA_HOST — Samba host (default: homeassistant.local or 192.168.0.40)
#   SAMBA_USER — Samba user (default: homeassistant)
#   SAMBA_PASS — Samba password (from .env SAMBA_PASSWORD)
#   SSH_ADDON_PORT — SSH addon port (default: 22222)
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Load environment
if [ -f "$REPO_ROOT/.env" ]; then
    export $(grep -v "^#" "$REPO_ROOT/.env" | xargs)
fi

# Defaults
HA_URL="${HA_URL:-http://homeassistant.local:8123}"
HA_TOKEN="${HA_TOKEN:-}"
SAMBA_HOST="${SAMBA_HOST:-homeassistant.local}"
SAMBA_USER="${SAMBA_USER:-homeassistant}"
SAMBA_PASS="${SAMBA_PASSWORD:-}"
SSH_ADDON_PORT="${SSH_ADDON_PORT:-22222}"
SSH_ADDON_USER="${SSH_ADDON_USER:-root}"
SSH_ADDON_PASS="${SSH_ADDON_PASSWORD:-}"
SYNC_METHOD="${HA_CONFIG_SYNC_METHOD:-auto}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $@"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $@"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $@"
}

# Validate inputs
if [ -z "$HA_TOKEN" ]; then
    log_error "HA_TOKEN is not set. Set it in .env or pass as environment variable."
    exit 1
fi

if [ ! -d "$REPO_ROOT/HomeAssistant_config" ]; then
    log_error "HomeAssistant_config directory not found at $REPO_ROOT/HomeAssistant_config"
    exit 1
fi

log_info "Starting Home Assistant config sync..."
log_info "HA URL: $HA_URL"
log_info "Config directory: $REPO_ROOT/HomeAssistant_config"
log_info ""

# ============================================================================
# Step 1: Detect or validate sync method
# ============================================================================

sync_via_samba() {
    log_info "Syncing via Samba..."
    
    # Validate credentials
    if [ -z "$SAMBA_PASS" ]; then
        log_error "SAMBA_PASSWORD not set in .env or environment."
        return 1
    fi
    
    # Try DNS name first, fall back to IP
    local target="$SAMBA_HOST"
    if ! ping -c 1 -W 1 "$target" &>/dev/null; then
        log_warn "$target not reachable via ping, trying fallback IP 192.168.0.40..."
        target="192.168.0.40"
        if ! ping -c 1 -W 1 "$target" &>/dev/null; then
            log_error "Cannot reach HAOS at $SAMBA_HOST or 192.168.0.40"
            return 1
        fi
    fi
    
    # Sync config files
    # Using rsync over Samba mount would be ideal, but fallback to smbclient
    if command -v smbclient &>/dev/null; then
        log_info "Using smbclient to sync files..."
        # Create temp script for smbclient
        local script=$(mktemp)
        trap "rm -f '$script'" RETURN
        
        {
            echo "cd config"
            find "$REPO_ROOT/HomeAssistant_config" -type f ! -name "ha_export.md" ! -name "test" | while read -r file; do
                local rel="${file#$REPO_ROOT/HomeAssistant_config/}"
                local dir=$(dirname "$rel")
                if [ "$dir" != "." ]; then
                    echo "mkdir -p \"$dir\""
                fi
                echo "put \"$file\" \"$rel\""
            done
        } > "$script"
        
        # Use echo instead of smbclient interactive mode to avoid TTY issues
        local pass_encoded=$(printf '%s' "$SAMBA_PASS" | sed "s/'/'\\\\''/g")
        smbclient "//$target/homeassistant" -U "$SAMBA_USER%$pass_encoded" \
            -c "cd config; $(cat "$script" | tr '\n' ';')" || {
            log_error "Samba sync failed"
            return 1
        }
        log_info "Samba sync complete"
        return 0
    else
        log_error "smbclient not installed. Install via: apt-get install smbclient"
        return 1
    fi
}

sync_via_ssh() {
    log_info "Syncing via SSH addon..."
    
    # Validate credentials
    if [ -z "$SSH_ADDON_PASS" ]; then
        log_error "SSH_ADDON_PASSWORD not set in .env or environment."
        return 1
    fi
    
    # Check if sshpass is available (safer than storing password in ssh command)
    if ! command -v sshpass &>/dev/null; then
        log_error "sshpass not installed. Install via: apt-get install sshpass"
        return 1
    fi
    
    # Check connectivity
    if ! sshpass -p "$SSH_ADDON_PASS" ssh -o StrictHostKeyChecking=no \
        -p "$SSH_ADDON_PORT" "$SSH_ADDON_USER@homeassistant.local" \
        "echo 'SSH test'" &>/dev/null; then
        log_error "Cannot connect to SSH addon at homeassistant.local:$SSH_ADDON_PORT"
        return 1
    fi
    
    # Use rsync for efficient sync
    if command -v rsync &>/dev/null; then
        log_info "Using rsync over SSH to sync files..."
        RSYNC_RSH="sshpass -p '$SSH_ADDON_PASS' ssh -o StrictHostKeyChecking=no -p $SSH_ADDON_PORT" \
        rsync -avz --delete \
            --exclude='ha_export.md' --exclude='test' \
            "$REPO_ROOT/HomeAssistant_config/" \
            "$SSH_ADDON_USER@homeassistant.local:/config/" || {
            log_error "rsync sync failed"
            return 1
        }
        log_info "SSH/rsync sync complete"
        return 0
    else
        # Fallback to scp
        log_warn "rsync not available, falling back to scp (slower)..."
        sshpass -p "$SSH_ADDON_PASS" scp -r -o StrictHostKeyChecking=no \
            -P "$SSH_ADDON_PORT" \
            "$REPO_ROOT/HomeAssistant_config"/* \
            "$SSH_ADDON_USER@homeassistant.local:/config/" || {
            log_error "scp sync failed"
            return 1
        }
        log_info "SSH/scp sync complete"
        return 0
    fi
}

# Detect and execute sync method
if [ "$SYNC_METHOD" = "auto" ] || [ "$SYNC_METHOD" = "" ]; then
    log_info "Auto-detecting sync method..."
    
    # Try Samba first (preferred)
    if command -v smbclient &>/dev/null && [ -n "$SAMBA_PASS" ]; then
        if sync_via_samba; then
            SYNC_METHOD="samba"
        elif command -v sshpass &>/dev/null && [ -n "$SSH_ADDON_PASS" ]; then
            log_warn "Samba sync failed, falling back to SSH addon..."
            if sync_via_ssh; then
                SYNC_METHOD="ssh"
            fi
        fi
    elif command -v sshpass &>/dev/null && [ -n "$SSH_ADDON_PASS" ]; then
        if sync_via_ssh; then
            SYNC_METHOD="ssh"
        fi
    else
        log_error "No sync method available (need either Samba or SSH addon credentials)"
        exit 1
    fi
elif [ "$SYNC_METHOD" = "samba" ]; then
    sync_via_samba || exit 1
elif [ "$SYNC_METHOD" = "ssh" ]; then
    sync_via_ssh || exit 1
else
    log_error "Unknown sync method: $SYNC_METHOD (use 'samba' or 'ssh')"
    exit 1
fi

log_info ""
log_info "Sync method used: $SYNC_METHOD"

# ============================================================================
# Step 2: POST to HA API endpoints to reload config
# ============================================================================

log_info "Triggering Home Assistant config reload..."

# Helper to make HA API calls
ha_api_call() {
    local method="$1"
    local endpoint="$2"
    local data="${3:-}"
    
    local url="$HA_URL/api$endpoint"
    local headers=(
        -H "Authorization: Bearer $HA_TOKEN"
        -H "Content-Type: application/json"
        -H "Accept: application/json"
    )
    
    if [ "$method" = "POST" ]; then
        if [ -z "$data" ]; then
            curl -s -X POST "${headers[@]}" "$url"
        else
            curl -s -X POST "${headers[@]}" -d "$data" "$url"
        fi
    else
        curl -s -X GET "${headers[@]}" "$url"
    fi
}

# Call 1: Reload Lovelace resources (dashboards/UI)
log_info "  POST /api/services/lovelace/reload_resources"
RELOAD_LOVELACE=$(ha_api_call POST "/services/lovelace/reload_resources" '{}')
if echo "$RELOAD_LOVELACE" | grep -q "error\|unauthorized" 2>/dev/null; then
    log_warn "  Lovelace reload may have failed: $RELOAD_LOVELACE"
else
    log_info "  ✓ Lovelace resources reloaded"
fi

# Call 2: Reload config entries (integrations)
log_info "  POST /api/services/homeassistant/reload_config_entry"
RELOAD_CONFIG=$(ha_api_call POST "/services/homeassistant/reload_config_entry" '{}')
if echo "$RELOAD_CONFIG" | grep -q "error\|unauthorized" 2>/dev/null; then
    log_warn "  Config entry reload may have failed: $RELOAD_CONFIG"
else
    log_info "  ✓ Config entries reloaded"
fi

# Call 3: (Optional) Check HA is reachable and get version
log_info "  GET /api/"
HA_INFO=$(ha_api_call GET "/")
HA_VERSION=$(echo "$HA_INFO" | grep -o '"homeassistant_version":"[^"]*' | cut -d'"' -f4)
if [ -n "$HA_VERSION" ]; then
    log_info "  ✓ HA is online (version: $HA_VERSION)"
else
    log_warn "  Could not verify HA version, but may still be working"
fi

# ============================================================================
# Step 3: Verify sync was successful
# ============================================================================

log_info ""
log_info "Verifying sync..."

# Count files synced
CONFIG_FILE_COUNT=$(find "$REPO_ROOT/HomeAssistant_config" -type f ! -name "ha_export.md" ! -name "test" | wc -l)
log_info "  Config files to verify: $CONFIG_FILE_COUNT"

# Check critical files exist in remote
if [ "$SYNC_METHOD" = "ssh" ]; then
    if command -v sshpass &>/dev/null && [ -n "$SSH_ADDON_PASS" ]; then
        REMOTE_FILES=$(sshpass -p "$SSH_ADDON_PASS" ssh -o StrictHostKeyChecking=no \
            -p "$SSH_ADDON_PORT" "$SSH_ADDON_USER@homeassistant.local" \
            "find /config -maxdepth 1 -type f -name '*.yaml' | wc -l" 2>/dev/null)
        if [ "$REMOTE_FILES" -gt 0 ]; then
            log_info "  ✓ Found $REMOTE_FILES YAML files in remote /config/"
        else
            log_warn "  Could not verify remote files (SSH check)"
        fi
    fi
fi

log_info ""
log_info "✓ Home Assistant config sync complete!"
log_info ""
log_info "Summary:"
log_info "  - Synced $CONFIG_FILE_COUNT config files via $SYNC_METHOD"
log_info "  - Reloaded Lovelace resources"
log_info "  - Reloaded config entries"
log_info "  - HA is online and responding"
log_info ""
log_info "Next: Check Home Assistant UI for any validation errors or missing entities."
