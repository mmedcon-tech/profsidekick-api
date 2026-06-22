#!/bin/bash
# Test CORS and routing for dual backend setup

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

API_URL="https://api.eliteflex.app"
MAIN_ORIGIN="https://profsidekick-ai.vercel.app"
AUTOGRADER_ORIGIN="https://profsidekick-autograder.vercel.app"

echo "========================================"
echo "  CORS & Routing Test"
echo "========================================"
echo ""

# Test function
test_cors() {
    local origin=$1
    local expected_instance=$2
    
    echo -e "${BLUE}Testing Origin: ${origin}${NC}"
    echo "Expected backend instance: ${expected_instance}"
    echo ""
    
    # Make request and capture response
    response=$(curl -s -H "Origin: ${origin}" "${API_URL}/health")
    
    # Parse response
    status=$(echo "$response" | jq -r '.status' 2>/dev/null)
    instance=$(echo "$response" | jq -r '.instance' 2>/dev/null)
    origin_header=$(echo "$response" | jq -r '.origin' 2>/dev/null)
    
    echo "Response:"
    echo "$response" | jq '.' 2>/dev/null || echo "$response"
    echo ""
    
    # Verify routing
    if [ "$instance" == "$expected_instance" ]; then
        echo -e "${GREEN}✓ Routing CORRECT: Request routed to ${instance} backend${NC}"
    else
        echo -e "${RED}✗ Routing INCORRECT: Expected ${expected_instance}, got ${instance}${NC}"
    fi
    
    # Check CORS headers
    echo ""
    echo "Checking CORS headers..."
    cors_headers=$(curl -s -I -H "Origin: ${origin}" "${API_URL}/health" | grep -i "access-control")
    
    if [ -n "$cors_headers" ]; then
        echo -e "${GREEN}✓ CORS headers present:${NC}"
        echo "$cors_headers"
    else
        echo -e "${RED}✗ No CORS headers found${NC}"
    fi
    
    echo ""
    echo "----------------------------------------"
    echo ""
}

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo -e "${YELLOW}⚠ jq not found. Installing for JSON parsing...${NC}"
    echo "Run: sudo apt install jq -y"
    echo ""
fi

# Test 1: Main backend
echo ""
echo -e "${YELLOW}[TEST 1] Main Backend Routing${NC}"
echo ""
test_cors "$MAIN_ORIGIN" "main"

# Test 2: Autograder backend
echo ""
echo -e "${YELLOW}[TEST 2] Autograder Backend Routing${NC}"
echo ""
test_cors "$AUTOGRADER_ORIGIN" "autograder"

# Test 3: Preflight (OPTIONS) request
echo ""
echo -e "${YELLOW}[TEST 3] Preflight (OPTIONS) Request${NC}"
echo ""
echo "Testing OPTIONS request from autograder origin..."
options_response=$(curl -s -X OPTIONS -H "Origin: ${AUTOGRADER_ORIGIN}" \
    -H "Access-Control-Request-Method: POST" \
    -H "Access-Control-Request-Headers: Content-Type" \
    -I "${API_URL}/health")

echo "$options_response" | grep -i "access-control"

if echo "$options_response" | grep -q "access-control-allow-origin"; then
    echo -e "${GREEN}✓ Preflight request successful${NC}"
else
    echo -e "${RED}✗ Preflight request failed${NC}"
fi

echo ""
echo "========================================"
echo "  Test Summary"
echo "========================================"
echo ""
echo "To view live traffic routing:"
echo "  sudo tail -f /var/log/nginx/api.eliteflex.app.access.log"
echo ""
echo "To test from browser:"
echo "  1. Open DevTools (F12) → Network tab"
echo "  2. Make API request from your frontend"
echo "  3. Check response headers for 'access-control-allow-origin'"
echo ""
