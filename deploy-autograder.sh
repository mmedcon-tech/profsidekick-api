#!/bin/bash
# Quick deployment script for autograder backend on VPS

set -e  # Exit on error

echo "================================"
echo "Autograder Backend Deployment"
echo "================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if running on VPS (adjust this check as needed)
if [ ! -d "/opt/profsidekick" ]; then
    echo -e "${YELLOW}Warning: /opt/profsidekick directory not found.${NC}"
    echo "This script is designed to run on the VPS."
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Configuration
AUTOGRADER_DIR="/opt/profsidekick/autograder/profsidekick-api"
BRANCH="feature/math-autograder-frontend"
COMPOSE_FILE="docker-compose.autograder.yml"

echo -e "${YELLOW}Deployment Configuration:${NC}"
echo "  Directory: $AUTOGRADER_DIR"
echo "  Branch: $BRANCH"
echo "  Compose File: $COMPOSE_FILE"
echo ""

# Navigate to autograder directory
if [ -d "$AUTOGRADER_DIR" ]; then
    echo -e "${GREEN}✓${NC} Found autograder directory"
    cd "$AUTOGRADER_DIR"
else
    echo -e "${RED}✗${NC} Autograder directory not found at $AUTOGRADER_DIR"
    echo "Please run the initial setup first (see VPS_DUAL_DEPLOYMENT.md)"
    exit 1
fi

# Check if docker-compose file exists
if [ ! -f "$COMPOSE_FILE" ]; then
    echo -e "${RED}✗${NC} $COMPOSE_FILE not found"
    echo "Please ensure docker-compose.autograder.yml is in the directory"
    exit 1
fi

# Pull latest changes
echo ""
echo -e "${YELLOW}Pulling latest changes from $BRANCH...${NC}"
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo -e "${GREEN}✓${NC} Code updated"

# Stop existing containers
echo ""
echo -e "${YELLOW}Stopping existing containers...${NC}"
docker-compose -f "$COMPOSE_FILE" down
echo -e "${GREEN}✓${NC} Containers stopped"

# Build new images
echo ""
echo -e "${YELLOW}Building Docker images...${NC}"
docker-compose -f "$COMPOSE_FILE" build --no-cache
echo -e "${GREEN}✓${NC} Images built"

# Start containers
echo ""
echo -e "${YELLOW}Starting containers...${NC}"
docker-compose -f "$COMPOSE_FILE" up -d
echo -e "${GREEN}✓${NC} Containers started"

# Wait for backend to be healthy
echo ""
echo -e "${YELLOW}Waiting for backend to be ready...${NC}"
sleep 10

# Check if containers are running
if docker ps | grep -q "profsidekick-backend-autograder"; then
    echo -e "${GREEN}✓${NC} Backend container is running"
else
    echo -e "${RED}✗${NC} Backend container failed to start"
    echo "Checking logs..."
    docker-compose -f "$COMPOSE_FILE" logs --tail=50 backend-autograder
    exit 1
fi

if docker ps | grep -q "profsidekick-postgres-autograder"; then
    echo -e "${GREEN}✓${NC} Database container is running"
else
    echo -e "${RED}✗${NC} Database container failed to start"
    exit 1
fi

# Run database migrations
echo ""
echo -e "${YELLOW}Running database migrations...${NC}"
if docker exec profsidekick-backend-autograder alembic upgrade head; then
    echo -e "${GREEN}✓${NC} Migrations completed"
else
    echo -e "${RED}✗${NC} Migrations failed"
    echo "Check logs with: docker logs profsidekick-backend-autograder"
    exit 1
fi

# Test the endpoint
echo ""
echo -e "${YELLOW}Testing autograder backend...${NC}"
if curl -f -s http://localhost:8001/health > /dev/null; then
    echo -e "${GREEN}✓${NC} Backend is responding on port 8001"
else
    echo -e "${YELLOW}⚠${NC} Backend health check failed (this might be normal if /health endpoint doesn't exist)"
fi

# Show running containers
echo ""
echo -e "${YELLOW}Running containers:${NC}"
docker ps | grep "profsidekick.*autograder"

# Show logs
echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Autograder backend is running on port 8001"
echo "Database is running on port 5434"
echo "Redis is running on port 6380"
echo ""
echo "View logs with:"
echo "  docker logs -f profsidekick-backend-autograder"
echo ""
echo "Test with:"
echo "  curl -H 'Origin: https://profsidekick-autograder.app' https://api.eliteflex.app/health"
echo ""
echo -e "${YELLOW}Note: Make sure nginx is configured and running to route requests properly!${NC}"
