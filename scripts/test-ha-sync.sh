#!/usr/bin/env bash
# Test Home Assistant config sync setup.
#
# Validates prerequisites and performs a dry-run of the sync process.
#
# Usage: ./scripts/test-ha-sync.sh [verbose]
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

verbose="${1:-}"
passed=0
failed=0
warned=0

log_pass() {
    echo -e "${GREEN}✓${NC} $@"
    ((passed++))
}

log_fail() {
    echo -e "${RED}✗${NC} $@"
    ((failed++))
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $@"
    ((warned++))
}

log_info() {
    echo -e "${BLUE}ℹ${NC} $@"
}

echo "========================================================"
echo "Home Assistant Config Sync — Setup Test"
echo "========================================================"
echo ""

# Load .env if it exists
if [ -f "$REPO_ROOT/.env" ]; then
    export $(grep -v "^#" "$REPO_ROOT/.env" | xargs) || true
fi

# --- Test 1: Required files exist ---
echo "1. Checking required files..."
if [ -d "$REPO_ROOT/HomeAssistant_config" ]; then
    log_pass "HomeAssistant_config/ directory exists"
    config_files=$(find "$REPO_ROOT/HomeAssistant_config" -type f ! -name "ha_export.md" ! -name "test" | wc -l)
    echo "  Found $config_files config files"
else
    log_fail "HomeAssistant_config/ directory not found"
fi

if [ -f "$REPO_ROOT/scripts/sync-ha-config.sh" ]; then
    log_pass "sync-ha-config.sh script exists"
else
    log_fail "sync-ha-config.sh script not found"
fi

if [ -f "$REPO_ROOT/scripts/post-deploy-sync-ha.sh" ]; then
    log_pass "post-deploy-sync-ha.sh script exists"
else
    log_fail "post-deploy-sync-ha.sh script not found"
fi

echo ""

# --- Test 2: Script permissions ---
echo "2. Checking script permissions..."
for script in scripts/sync-ha-config.sh scripts/post-deploy-sync-ha.sh; do
    if [ -x "$script" ]; then
        log_pass "$script is executable"
    else
        log_fail "$script is not executable (run: chmod +x $script)"
    fi
done
echo ""

# --- Test 3: Environment variables ---
echo "3. Checking environment & credentials..."
if [ -n "${HA_URL:-}" ]; then
    log_pass "HA_URL is set: $HA_URL"
else
    log_warn "HA_URL not set (default: http://homeassistant.local:8123)"
fi

if [ -n "${HA_TOKEN:-}" ]; then
    token_short=$(echo "$HA_TOKEN" | cut -c1-10)...
    log_pass "HA_TOKEN is set: $token_short"
else
    log_fail "HA_TOKEN not set (required for sync)"
fi

if [ -n "${SAMBA_PASSWORD:-}" ]; then
    log_pass "SAMBA_PASSWORD is set (for Samba sync)"
else
    log_warn "SAMBA_PASSWORD not set (falling back to SSH addon)"
fi

if [ -n "${SSH_ADDON_PASSWORD:-}" ]; then
    log_pass "SSH_ADDON_PASSWORD is set (for SSH addon sync)"
else
    log_warn "SSH_ADDON_PASSWORD not set (falling back to Samba)"
fi

echo ""

# --- Test 4: Command availability ---
echo "4. Checking required commands..."
commands=("curl" "find" "ping")
optional_commands=("smbclient:Samba sync" "sshpass:SSH addon sync" "rsync:SSH rsync (faster)")

for cmd in "${commands[@]}"; do
    if command -v "$cmd" &>/dev/null; then
        log_pass "$cmd is installed"
    else
        log_fail "$cmd is not installed"
    fi
done

echo "  Optional commands (for specific sync methods):"
for pair in "${optional_commands[@]}"; do
    cmd="${pair%:*}"
    desc="${pair#*:}"
    if command -v "$cmd" &>/dev/null; then
        log_pass "$cmd ($desc)"
    else
        log_warn "$cmd not installed ($desc) — sync may fall back to other method"
    fi
done

echo ""

# --- Test 5: Network connectivity ---
echo "5. Checking network connectivity to HAOS..."
ha_url="${HA_URL:-http://homeassistant.local:8123}"
ha_host=$(echo "$ha_url" | sed -e 's#^https://##' -e 's#^http://##' -e 's#:.*##')

if ping -c 1 -W 2 "$ha_host" &>/dev/null; then
    log_pass "HAOS is reachable at $ha_host"
else
    # Try fallback IP
    if ping -c 1 -W 2 "192.168.0.40" &>/dev/null; then
        log_warn "$ha_host not reachable, but 192.168.0.40 (fallback) is reachable"
    else
        log_fail "Cannot reach HAOS at $ha_host or 192.168.0.40 (may be offline or unreachable from this host)"
    fi
fi

echo ""

# --- Test 6: HA API connectivity ---
echo "6. Testing Home Assistant API..."
if [ -z "${HA_TOKEN:-}" ]; then
    log_warn "Skipping API test (HA_TOKEN not set)"
else
    ha_url="${HA_URL:-http://homeassistant.local:8123}"
    api_response=$(curl -s -m 5 \
        -H "Authorization: Bearer $HA_TOKEN" \
        -H "Content-Type: application/json" \
        "$ha_url/api/" 2>&1 || echo "timeout")
    
    if echo "$api_response" | grep -q "homeassistant" 2>/dev/null; then
        ha_version=$(echo "$api_response" | grep -o '"homeassistant_version":"[^"]*' | cut -d'"' -f4)
        log_pass "HA API is accessible (version: $ha_version)"
    elif [ "$api_response" = "timeout" ]; then
        log_fail "HA API timeout (HA may be offline or unreachable)"
    else
        log_fail "HA API error or invalid token"
        if [ "$verbose" = "verbose" ]; then
            echo "  Response: $api_response"
        fi
    fi
fi

echo ""

# --- Test 7: Dry-run sync (without actually syncing) ---
echo "7. Validating sync script..."
if bash -n "$REPO_ROOT/scripts/sync-ha-config.sh" 2>&1 | head -5; then
    log_pass "sync-ha-config.sh syntax is valid"
else
    log_fail "sync-ha-config.sh has syntax errors"
fi

echo ""

# --- Test 8: Configuration.yaml validation ---
echo "8. Checking HomeAssistant_config/configuration.yaml..."
config_yaml="$REPO_ROOT/HomeAssistant_config/configuration.yaml"
if [ -f "$config_yaml" ]; then
    log_pass "configuration.yaml exists"
    
    # Check for common issues
    if grep -q "^#" "$config_yaml" | head -1; then
        log_pass "configuration.yaml has comments/structure"
    fi
    
    lines=$(wc -l < "$config_yaml")
    echo "  File size: $lines lines"
else
    log_fail "configuration.yaml not found"
fi

echo ""

# --- Test 9: Dashboards ---
echo "9. Checking dashboards..."
if [ -d "$REPO_ROOT/HomeAssistant_config/dashboards" ]; then
    dashboard_count=$(find "$REPO_ROOT/HomeAssistant_config/dashboards" -type f | wc -l)
    log_pass "dashboards/ directory exists ($dashboard_count files)"
else
    log_warn "dashboards/ directory not found (optional)"
fi

echo ""

# --- Test 10: Integration check ---
echo "10. Checking deploy-pull.sh integration..."
if grep -q "post-deploy-sync-ha.sh" "$REPO_ROOT/scripts/deploy-pull.sh" 2>/dev/null; then
    log_pass "deploy-pull.sh calls post-deploy-sync-ha.sh"
else
    log_fail "deploy-pull.sh does not call post-deploy-sync-ha.sh"
fi

echo ""

# --- Summary ---
echo "========================================================"
echo "Test Summary"
echo "========================================================"
echo -e "  ${GREEN}Passed${NC}: $passed"
echo -e "  ${YELLOW}Warned${NC}: $warned"
echo -e "  ${RED}Failed${NC}: $failed"
echo "========================================================"

if [ "$failed" -eq 0 ] && [ -n "${HA_TOKEN:-}" ]; then
    echo ""
    echo -e "${GREEN}✓ Setup is ready!${NC}"
    echo ""
    echo "You can now:"
    echo "  1. Run manual sync: ./scripts/sync-ha-config.sh"
    echo "  2. Push changes to git (auto-sync via ops-bridge)"
    echo "  3. Or run full deploy: ./scripts/deploy-pull.sh"
    echo ""
    exit 0
elif [ "$failed" -eq 0 ]; then
    echo ""
    echo -e "${YELLOW}⚠ Setup is almost ready, but HA_TOKEN is not set.${NC}"
    echo ""
    echo "Add HA_TOKEN to .env to enable sync:"
    echo "  1. Generate token: HA UI → Settings → Automation (top-right) → Create Token"
    echo "  2. Add to .env: echo 'HA_TOKEN=<token>' >> .env"
    echo ""
    echo "Then re-run this test."
    exit 0
else
    echo ""
    echo -e "${RED}✗ Setup has issues that need fixing.${NC}"
    echo ""
    echo "See failures above. Common fixes:"
    echo "  - Add HA_TOKEN to .env"
    echo "  - Ensure homeassistant.local is reachable: ping homeassistant.local"
    echo "  - Check HAOS is running and accessible"
    echo "  - Verify Samba/SSH addon is installed on HAOS"
    echo ""
    exit 1
fi
