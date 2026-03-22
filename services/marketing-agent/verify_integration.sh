#!/bin/bash
# Scout Engine Integration Verification Script
# Checks all components are properly integrated

set -e

BASEDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASEDIR"

echo "================================================================================"
echo "Scout Engine Integration Verification"
echo "================================================================================"
echo ""

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check_file() {
    if [ -f "$1" ]; then
        echo -e "${GREEN}✓${NC} $1"
        return 0
    else
        echo -e "${RED}✗${NC} $1 (MISSING)"
        return 1
    fi
}

check_import() {
    if python3 -c "import sys; sys.path.insert(0, '.'); $1" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Import: $1"
        return 0
    else
        echo -e "${RED}✗${NC} Import: $1 (FAILED)"
        return 1
    fi
}

FAILED=0

# ============================================================================
# 1. Check File Structure
# ============================================================================
echo "📋 Checking File Structure..."
echo ""

check_file "main.py" || FAILED=1
check_file "models.py" || FAILED=1
check_file "config.py" || FAILED=1
check_file "database.py" || FAILED=1
check_file "requirements.txt" || FAILED=1

check_file "app/scout/__init__.py" || FAILED=1
check_file "app/scout/searxng_client.py" || FAILED=1
check_file "app/scout/scorer.py" || FAILED=1
check_file "app/scout/profiles.py" || FAILED=1
check_file "app/scout/scheduler.py" || FAILED=1
check_file "app/scout/events.py" || FAILED=1

check_file "api/scout.py" || FAILED=1
check_file "api/signals.py" || FAILED=1

check_file "migrations/004_add_search_profiles_table.sql" || FAILED=1

echo ""

# ============================================================================
# 2. Check Python Syntax
# ============================================================================
echo "🐍 Checking Python Syntax..."
echo ""

python3 -m py_compile main.py && echo -e "${GREEN}✓${NC} main.py" || { echo -e "${RED}✗${NC} main.py syntax error"; FAILED=1; }
python3 -m py_compile models.py && echo -e "${GREEN}✓${NC} models.py" || { echo -e "${RED}✗${NC} models.py syntax error"; FAILED=1; }
python3 -m py_compile config.py && echo -e "${GREEN}✓${NC} config.py" || { echo -e "${RED}✗${NC} config.py syntax error"; FAILED=1; }

for f in app/scout/*.py; do
    python3 -m py_compile "$f" && echo -e "${GREEN}✓${NC} $f" || { echo -e "${RED}✗${NC} $f syntax error"; FAILED=1; }
done

for f in api/*.py; do
    python3 -m py_compile "$f" && echo -e "${GREEN}✓${NC} $f" || { echo -e "${RED}✗${NC} $f syntax error"; FAILED=1; }
done

echo ""

# ============================================================================
# 3. Check Requirements
# ============================================================================
echo "📦 Checking Dependencies in requirements.txt..."
echo ""

REQ_CHECKS=(
    "fastapi"
    "uvicorn"
    "sqlalchemy"
    "httpx"
    "apscheduler"
    "nats-py"
    "neo4j"
)

for req in "${REQ_CHECKS[@]}"; do
    if grep -q "$req" requirements.txt; then
        echo -e "${GREEN}✓${NC} $req"
    else
        echo -e "${RED}✗${NC} $req (NOT IN requirements.txt)"
        FAILED=1
    fi
done

echo ""

# ============================================================================
# 4. Check Configuration
# ============================================================================
echo "⚙️  Checking Configuration..."
echo ""

CONFIG_CHECKS=(
    "searxng_url"
    "nats_url"
    "scout_enabled"
)

for cfg in "${CONFIG_CHECKS[@]}"; do
    if grep -q "$cfg" config.py; then
        echo -e "${GREEN}✓${NC} config.py contains $cfg"
    else
        echo -e "${RED}✗${NC} config.py missing $cfg"
        FAILED=1
    fi
done

echo ""

# ============================================================================
# 5. Check Models
# ============================================================================
echo "🗄️  Checking ORM Models..."
echo ""

MODEL_CHECKS=(
    "class Signal"
    "class SearchProfile"
    "url_hash"
    "relevance_score"
    "pillar_id"
    "search_profile_id"
)

for model in "${MODEL_CHECKS[@]}"; do
    if grep -q "$model" models.py; then
        echo -e "${GREEN}✓${NC} models.py contains '$model'"
    else
        echo -e "${RED}✗${NC} models.py missing '$model'"
        FAILED=1
    fi
done

echo ""

# ============================================================================
# 6. Check Components
# ============================================================================
echo "🔧 Checking Scout Components..."
echo ""

COMPONENT_CHECKS=(
    "app/scout/searxng_client.py:class SearXNGClient"
    "app/scout/searxng_client.py:async def search"
    "app/scout/searxng_client.py:async def health_check"
    "app/scout/scorer.py:def score_signal"
    "app/scout/profiles.py:DEFAULT_PROFILES"
    "app/scout/profiles.py:get_default_profiles"
    "app/scout/scheduler.py:class ScoutScheduler"
    "app/scout/scheduler.py:async def start"
    "app/scout/scheduler.py:async def run_profile"
    "app/scout/events.py:class NATSPublisher"
    "app/scout/events.py:async def publish_signal_detected"
)

for check in "${COMPONENT_CHECKS[@]}"; do
    IFS=':' read -r file pattern <<< "$check"
    if grep -q "$pattern" "$file"; then
        echo -e "${GREEN}✓${NC} $file contains '$pattern'"
    else
        echo -e "${RED}✗${NC} $file missing '$pattern'"
        FAILED=1
    fi
done

echo ""

# ============================================================================
# 7. Check API Endpoints
# ============================================================================
echo "🌐 Checking API Endpoints..."
echo ""

ENDPOINT_CHECKS=(
    "api/scout.py:@router.get"
    "api/signals.py:@router.get"
    "api/signals.py:@router.patch"
    "api/signals.py:@router.post.*refresh"
)

for check in "${ENDPOINT_CHECKS[@]}"; do
    IFS=':' read -r file pattern <<< "$check"
    if grep -q "$pattern" "$file"; then
        echo -e "${GREEN}✓${NC} $file contains endpoint '$pattern'"
    else
        echo -e "${RED}✗${NC} $file missing endpoint '$pattern'"
        FAILED=1
    fi
done

echo ""

# ============================================================================
# 8. Check Main App Integration
# ============================================================================
echo "🚀 Checking FastAPI Integration..."
echo ""

MAIN_CHECKS=(
    "import.*scout"
    "init_nats_publisher"
    "close_nats_publisher"
    "get_scheduler"
    "app.include_router.*scout"
    "app.include_router.*signals"
)

for check in "${MAIN_CHECKS[@]}"; do
    if grep -q "$check" main.py; then
        echo -e "${GREEN}✓${NC} main.py contains '$check'"
    else
        echo -e "${RED}✗${NC} main.py missing '$check'"
        FAILED=1
    fi
done

echo ""

# ============================================================================
# 9. Check Profiles
# ============================================================================
echo "📊 Checking Search Profiles..."
echo ""

PROFILE_CHECKS=(
    "sap_datasphere"
    "sap_community"
    "sap_release"
    "ai_enterprise"
    "linkedin_signals"
)

for profile in "${PROFILE_CHECKS[@]}"; do
    if grep -q "$profile" app/scout/profiles.py; then
        echo -e "${GREEN}✓${NC} Profile: $profile"
    else
        echo -e "${RED}✗${NC} Profile: $profile (MISSING)"
        FAILED=1
    fi
done

echo ""

# ============================================================================
# 10. Check Documentation
# ============================================================================
echo "📚 Checking Documentation..."
echo ""

check_file "SCOUT_ENGINE.md" || FAILED=1
check_file "DEPLOYMENT.md" || FAILED=1
check_file "test_scout_engine.py" || FAILED=1

echo ""

# ============================================================================
# Summary
# ============================================================================
echo "================================================================================"

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo ""
    echo "Scout Engine is fully integrated and ready for deployment."
    echo ""
    echo "Next steps:"
    echo "  1. Apply database migration: psql -f migrations/004_add_search_profiles_table.sql"
    echo "  2. Start service: docker-compose up marketing-agent -d"
    echo "  3. Verify: curl http://localhost:8210/health"
    echo "  4. Monitor logs: docker logs marketing-agent -f"
    echo ""
    exit 0
else
    echo -e "${RED}✗ Some checks failed!${NC}"
    echo ""
    echo "Please fix the issues above before deployment."
    echo ""
    exit 1
fi
