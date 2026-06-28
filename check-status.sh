#!/bin/bash
# Status check script for both backend deployments

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "========================================"
echo "  ProfSidekick Backends Status"
echo "========================================"
echo ""

# Function to check if container is running
check_container() {
    local container_name=$1
    if docker ps --format '{{.Names}}' | grep -q "^${container_name}$"; then
        echo -e "${GREEN}✓${NC} Running"
        return 0
    else
        echo -e "${RED}✗${NC} Not running"
        return 1
    fi
}

# Function to get container uptime
get_uptime() {
    local container_name=$1
    if docker ps --format '{{.Names}} {{.Status}}' | grep "^${container_name}" > /dev/null; then
        docker ps --format '{{.Names}} {{.Status}}' | grep "^${container_name}" | awk '{$1=""; print $0}' | sed 's/^ //'
    else
        echo "N/A"
    fi
}

# Main Backend Status
echo -e "${BLUE}━━━ Main Backend (Port 8000) ━━━${NC}"
echo -n "  Backend:   "
check_container "profsidekick-backend"
echo "  Uptime:    $(get_uptime 'profsidekick-backend')"

echo -n "  Database:  "
check_container "profsidekick-postgres"
echo "  Port:      5433"

echo -n "  Redis:     "
check_container "profsidekick-redis"
echo "  Port:      6379"

# Test endpoint
echo -n "  API Test:  "
if curl -f -s -m 5 http://localhost:8000/docs > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Responding"
else
    echo -e "${RED}✗${NC} Not responding"
fi

echo ""

# Autograder Backend Status
echo -e "${BLUE}━━━ Autograder Backend (Port 8001) ━━━${NC}"
echo -n "  Backend:   "
check_container "profsidekick-backend-autograder"
echo "  Uptime:    $(get_uptime 'profsidekick-backend-autograder')"

echo -n "  Database:  "
check_container "profsidekick-postgres-autograder"
echo "  Port:      5434"

echo -n "  Redis:     "
check_container "profsidekick-redis-autograder"
echo "  Port:      6380"

# Test endpoint
echo -n "  API Test:  "
if curl -f -s -m 5 http://localhost:8001/docs > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Responding"
else
    echo -e "${RED}✗${NC} Not responding"
fi

echo ""

# Nginx Status
echo -e "${BLUE}━━━ Nginx Reverse Proxy ━━━${NC}"
if systemctl is-active --quiet nginx; then
    echo -e "  Status:    ${GREEN}✓${NC} Running"
    echo "  Config:    /etc/nginx/sites-available/api.eliteflex.app"
    
    # Test external endpoint
    echo -n "  External:  "
    if curl -f -s -m 5 -k https://api.eliteflex.app/docs > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} api.eliteflex.app responding"
    else
        echo -e "${YELLOW}⚠${NC} api.eliteflex.app not responding"
    fi
else
    echo -e "  Status:    ${RED}✗${NC} Not running"
fi

echo ""

# Resource Usage
echo -e "${BLUE}━━━ Resource Usage ━━━${NC}"
echo "Container Name                        CPU %     MEM USAGE"
echo "-------------------------------------------------------"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" | \
    grep profsidekick | \
    awk '{printf "%-35s %-9s %s\n", $1, $2, $3}'

echo ""

# Disk Usage
echo -e "${BLUE}━━━ Docker Volumes ━━━${NC}"
docker system df -v | grep -A 20 "Local Volumes:" | grep profsidekick || echo "  No volumes found"

echo ""

# Quick Access Commands
echo -e "${BLUE}━━━ Quick Commands ━━━${NC}"
echo "  Main backend logs:        docker logs -f profsidekick-backend"
echo "  Autograder backend logs:  docker logs -f profsidekick-backend-autograder"
echo "  Nginx logs:               sudo tail -f /var/log/nginx/api.eliteflex.app.access.log"
echo "  Restart main:             cd /opt/profsidekick/main/profsidekick-api && docker-compose restart"
echo "  Restart autograder:       cd /opt/profsidekick/autograder/profsidekick-api && docker-compose -f docker-compose.autograder.yml restart"

echo ""
echo "========================================"
