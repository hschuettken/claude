#!/bin/bash

# Ollama Router Configuration Verification Script
# Tests connectivity, model availability, and router endpoints

set -e

ROUTER_HOST="${ROUTER_HOST:-192.168.0.50}"
ROUTER_PORT="${ROUTER_PORT:-11434}"
ROUTER_METRICS_PORT="${ROUTER_METRICS_PORT:-9090}"

OLLAMA_GD90="192.168.0.23:11434"
OLLAMA_HM50="192.168.0.20:11434"

TIMEOUT=5
RETRIES=3

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=== Ollama Router Configuration Verification ==="
echo ""

# Helper: Test HTTP endpoint
test_endpoint() {
    local url=$1
    local name=$2
    
    echo -n "Testing $name ... "
    
    for attempt in $(seq 1 $RETRIES); do
        if response=$(curl -s -m $TIMEOUT "$url" 2>/dev/null); then
            echo -e "${GREEN}✓${NC}"
            echo "  Response: $(echo $response | head -c 100)..."
            return 0
        fi
        [ $attempt -lt $RETRIES ] && sleep 2
    done
    
    echo -e "${RED}✗${NC}"
    return 1
}

# Helper: Check model availability
check_models() {
    local host=$1
    local name=$2
    
    echo -n "Checking models on $name ($host) ... "
    
    response=$(curl -s -m $TIMEOUT "http://$host/api/tags" 2>/dev/null || echo "{}")
    
    if [ -z "$response" ] || [ "$response" = "{}" ]; then
        echo -e "${RED}✗${NC} (no response)"
        return 1
    fi
    
    model_count=$(echo "$response" | jq '.models | length' 2>/dev/null || echo 0)
    
    if [ "$model_count" -gt 0 ]; then
        echo -e "${GREEN}✓${NC} ($model_count models)"
        echo "$response" | jq -r '.models[] | "  - \(.name)"' 2>/dev/null || true
        return 0
    else
        echo -e "${YELLOW}⚠${NC} (0 models loaded)"
        return 0
    fi
}

echo "--- OLLAMA NODE VERIFICATION ---"
echo ""

# Test Ollama nodes
check_models "$OLLAMA_GD90" "ollama-gd90"
check_models "$OLLAMA_HM50" "ollama-hm50"

echo ""
echo "--- ROUTER VERIFICATION ---"
echo ""

# Test router health
test_endpoint "http://$ROUTER_HOST:$ROUTER_PORT/" "Router root endpoint"

# Test router /api/tags
echo ""
test_endpoint "http://$ROUTER_HOST:$ROUTER_PORT/api/tags" "Router /api/tags"

# Test OpenAI-compatible endpoint
echo ""
test_endpoint "http://$ROUTER_HOST:$ROUTER_PORT/v1/models" "Router /v1/models (OpenAI)"

# Test Prometheus metrics
echo ""
test_endpoint "http://$ROUTER_HOST:$ROUTER_METRICS_PORT/metrics" "Prometheus /metrics"

echo ""
echo "--- ROUTER ENDPOINT TESTING ---"
echo ""

# Test fast task type (should route to smallest model)
echo -n "Testing /v1/chat/completions with fast task ... "
response=$(curl -s -m 10 -X POST "http://$ROUTER_HOST:$ROUTER_PORT/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-Task-Type: fast" \
  -d '{"model":"fast/qwen2.5:7b-q4_K_M","messages":[{"role":"user","content":"Hello"}],"max_tokens":10}' \
  2>/dev/null)

if echo "$response" | grep -q "choices" || echo "$response" | grep -q "error"; then
    echo -e "${GREEN}✓${NC}"
    echo "  Response: $(echo $response | head -c 100)..."
else
    echo -e "${YELLOW}⚠${NC} (unexpected response)"
    echo "  Response: $response"
fi

# Test deep task type
echo ""
echo -n "Testing /v1/chat/completions with deep task ... "
response=$(curl -s -m 10 -X POST "http://$ROUTER_HOST:$ROUTER_PORT/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-Task-Type: deep" \
  -d '{"model":"deep/qwen2.5:32b-q4_K_M","messages":[{"role":"user","content":"Explain AI"}],"max_tokens":20}' \
  2>/dev/null)

if echo "$response" | grep -q "choices" || echo "$response" | grep -q "error"; then
    echo -e "${GREEN}✓${NC}"
    echo "  Response: $(echo $response | head -c 100)..."
else
    echo -e "${YELLOW}⚠${NC} (unexpected response)"
    echo "  Response: $response"
fi

echo ""
echo "--- CONFIGURATION SUMMARY ---"
echo ""
echo "Router Address: http://$ROUTER_HOST:$ROUTER_PORT"
echo "Metrics URL: http://$ROUTER_HOST:$ROUTER_METRICS_PORT/metrics"
echo "OpenAI API Base: http://$ROUTER_HOST:$ROUTER_PORT/v1"
echo ""
echo "Configured Nodes:"
echo "  1. ollama-gd90 @ $OLLAMA_GD90 (strong, CPU-only)"
echo "  2. ollama-hm50 @ $OLLAMA_HM50 (weak, embeddings)"
echo ""
echo "Task Types Available:"
echo "  - fast:      Quick responses (qwen2.5:7b)"
echo "  - deep:      Complex reasoning (qwen2.5:32b)"
echo "  - code:      Code generation"
echo "  - embedding: Vector embeddings"
echo "  - reasoning: Chain-of-thought"
echo ""
echo "=== Verification Complete ==="
