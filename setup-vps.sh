#!/bin/bash
# Initial setup script for VPS dual backend deployment
# Run this on your Contabo VPS

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "========================================"
echo "  ProfSidekick VPS Dual Backend Setup"
echo "========================================"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
    echo -e "${RED}Please do not run as root. Run as a regular user with sudo privileges.${NC}"
    exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Docker not found. Installing Docker...${NC}"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo -e "${GREEN}✓${NC} Docker installed"
else
    echo -e "${GREEN}✓${NC} Docker is already installed"
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo -e "${YELLOW}Docker Compose not found. Installing...${NC}"
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo -e "${GREEN}✓${NC} Docker Compose installed"
else
    echo -e "${GREEN}✓${NC} Docker Compose is already installed"
fi

# Check if Nginx is installed
if ! command -v nginx &> /dev/null; then
    echo -e "${YELLOW}Nginx not found. Installing...${NC}"
    sudo apt update
    sudo apt install -y nginx
    sudo systemctl enable nginx
    sudo systemctl start nginx
    echo -e "${GREEN}✓${NC} Nginx installed"
else
    echo -e "${GREEN}✓${NC} Nginx is already installed"
fi

# Create directory structure
echo ""
echo -e "${YELLOW}Creating directory structure...${NC}"
mkdir -p ~/myos/autograder
echo -e "${GREEN}✓${NC} Directories created"

# Prompt for Git repository URL
echo ""
read -p "Enter your Git repository URL (e.g., https://github.com/user/repo.git): " GIT_REPO
if [ -z "$GIT_REPO" ]; then
    echo -e "${RED}Repository URL is required${NC}"
    exit 1
fi

# Clone main branch
echo ""
echo -e "${YELLOW}Cloning main branch...${NC}"
cd ~/myos
if [ ! -d "profsidekick-api" ]; then
    git clone "$GIT_REPO" profsidekick-api
    cd profsidekick-api
    git checkout main
    echo -e "${GREEN}✓${NC} Main branch cloned"
else
    echo -e "${YELLOW}Main repository already exists, pulling latest...${NC}"
    cd profsidekick-api
    git pull origin main
fi

# Clone autograder branch
echo ""
echo -e "${YELLOW}Cloning autograder branch...${NC}"
cd ~/myos/autograder
if [ ! -d "profsidekick-api" ]; then
    git clone "$GIT_REPO" profsidekick-api
    cd profsidekick-api
    git checkout feature/math-autograder-frontend
    echo -e "${GREEN}✓${NC} Autograder branch cloned"
else
    echo -e "${YELLOW}Autograder repository already exists, pulling latest...${NC}"
    cd profsidekick-api
    git pull origin feature/math-autograder-frontend
fi

# Setup environment files
echo ""
echo -e "${YELLOW}Setting up environment files...${NC}"

# Main backend
if [ ! -f "~/myos/profsidekick-api/.env" ]; then
    if [ -f "~/myos/profsidekick-api/.env.example" ]; then
        cp ~/myos/profsidekick-api/.env.example ~/myos/profsidekick-api/.env
        echo -e "${YELLOW}⚠${NC} Created .env for main backend - please edit it with your settings"
    else
        echo -e "${RED}No .env.example found for main backend${NC}"
    fi
else
    echo -e "${GREEN}✓${NC} Main backend .env exists"
fi

# Autograder backend
if [ ! -f "~/myos/autograder/profsidekick-api/.env" ]; then
    if [ -f "~/myos/autograder/profsidekick-api/.env.example" ]; then
        cp ~/myos/autograder/profsidekick-api/.env.example ~/myos/autograder/profsidekick-api/.env
        echo -e "${YELLOW}⚠${NC} Created .env for autograder backend - please edit it with your settings"
    else
        echo -e "${RED}No .env.example found for autograder backend${NC}"
    fi
else
    echo -e "${GREEN}✓${NC} Autograder backend .env exists"
fi

# Setup Nginx configuration
echo ""
echo -e "${YELLOW}Setting up Nginx configuration...${NC}"
if [ -f "~/myos/profsidekick-api/nginx-dual-backend.conf" ]; then
    sudo cp ~/myos/profsidekick-api/nginx-dual-backend.conf /etc/nginx/sites-available/api.eliteflex.app
    
    # Enable site
    if [ ! -L "/etc/nginx/sites-enabled/api.eliteflex.app" ]; then
        sudo ln -s /etc/nginx/sites-available/api.eliteflex.app /etc/nginx/sites-enabled/
    fi
    
    # Test nginx config
    if sudo nginx -t 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Nginx configuration valid"
        sudo systemctl reload nginx
    else
        echo -e "${RED}✗${NC} Nginx configuration has errors"
        echo "    Fix the SSL certificate paths in /etc/nginx/sites-available/api.eliteflex.app"
    fi
else
    echo -e "${RED}nginx-dual-backend.conf not found${NC}"
fi

# Setup SSL certificate
echo ""
echo -e "${YELLOW}SSL Certificate Setup${NC}"
if [ ! -d "/etc/letsencrypt/live/api.eliteflex.app" ]; then
    echo "SSL certificate not found. To set up SSL:"
    echo "  1. Install certbot: sudo apt install certbot python3-certbot-nginx -y"
    echo "  2. Get certificate: sudo certbot --nginx -d api.eliteflex.app"
else
    echo -e "${GREEN}✓${NC} SSL certificate exists"
fi

# Setup systemd services
echo ""
echo -e "${YELLOW}Setting up systemd services for auto-start...${NC}"
if [ -f "~/myos/profsidekick-api/systemd/profsidekick-main.service" ]; then
    sudo cp ~/myos/profsidekick-api/systemd/profsidekick-main.service /etc/systemd/system/
    sudo cp ~/myos/profsidekick-api/systemd/profsidekick-autograder.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable profsidekick-main.service
    sudo systemctl enable profsidekick-autograder.service
    echo -e "${GREEN}✓${NC} Systemd services installed"
else
    echo -e "${YELLOW}⚠${NC} Systemd service files not found"
fi

# Make scripts executable
echo ""
echo -e "${YELLOW}Making helper scripts executable...${NC}"
chmod +x ~/myos/autograder/profsidekick-api/deploy-autograder.sh 2>/dev/null || true
chmod +x ~/myos/profsidekick-api/check-status.sh 2>/dev/null || true

# Summary
echo ""
echo -e "${GREEN}========================================"
echo "  Setup Complete!"
echo "========================================${NC}"
echo ""
echo "Next steps:"
echo ""
echo "1. Edit environment files:"
echo "   nano ~/myos/profsidekick-api/.env"
echo "   nano ~/myos/autograder/profsidekick-api/.env"
echo ""
echo "2. Setup SSL certificate (if not done):"
echo "   sudo certbot --nginx -d api.eliteflex.app"
echo ""
echo "3. Start main backend:"
echo "   cd ~/myos/profsidekick-api"
echo "   docker-compose up -d"
echo ""
echo "4. Start autograder backend:"
echo "   cd ~/myos/autograder/profsidekick-api"
echo "   docker-compose -f docker-compose.autograder.yml up -d"
echo ""
echo "5. Check status:"
echo "   bash ~/myos/profsidekick-api/check-status.sh"
echo ""
echo "Documentation: ~/myos/profsidekick-api/VPS_DUAL_DEPLOYMENT.md"
echo ""
