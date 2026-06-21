# Deployment Guide: Running Two Backend Branches Concurrently on VPS

This guide explains how to run both the **main backend** (for profsidekick-ai.vercel.app) and the **autograder backend** (for profsidekick-autograder.vercel.app) on the same Contabo VPS, routed through nginx based on the frontend origin.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         Internet                             │
└───────────────────────┬─────────────────────────────────────┘
                        │ HTTPS
                        │ api.eliteflex.app
                        ▼
┌──────────────────────────────────────────────────────────────┐
│                    Nginx Reverse Proxy                        │
│              (Routes based on Origin header)                  │
└───────────┬──────────────────────────────────┬───────────────┘
            │                                  │
            │ Origin: profsidekick-ai          │ Origin: profsidekick-autograder
            ▼                                  ▼
    ┌──────────────┐                  ┌──────────────┐
    │   Backend    │                  │   Backend    │
    │   (main)     │                  │ (autograder) │
    │  Port 8000   │                  │  Port 8001   │
    │              │                  │              │
    │ PostgreSQL   │                  │ PostgreSQL   │
    │ Port 5433    │                  │ Port 5434    │
    │              │                  │              │
    │ Redis 6379   │                  │ Redis 6380   │
    └──────────────┘                  └──────────────┘
```

## Directory Structure on VPS

```
~/myos/
├── profsidekick-api/               # Main production backend
│   ├── docker-compose.yml
│   ├── .env
│   └── ...
│
└── autograder/                     # Autograder feature branch
    └── profsidekick-api/
        ├── docker-compose.autograder.yml
        ├── .env
        └── ...
```

## Step-by-Step Setup

### 1. Prepare VPS Directory Structure

```bash
# SSH into your Contabo VPS
ssh user@your-vps-ip

# Create directory structure
mkdir -p ~/myos/autograder
cd ~/myos
```

### 2. Clone/Update Main Branch

```bash
cd ~/myos
git clone https://github.com/yourusername/profsidekick-api.git
cd profsidekick-api
git checkout main  # or your production branch

# Copy environment file
cp .env.example .env
# Edit .env with your production settings
nano .env
```

### 3. Clone/Update Autograder Branch

```bash
cd ~/myos/autograder
git clone https://github.com/yourusername/profsidekick-api.git
cd profsidekick-api
git checkout feature/math-autograder-frontend

# Copy environment file
cp .env.example .env
# Edit .env with autograder-specific settings
nano .env
```

### 4. Configure Nginx

```bash
# Install nginx if not already installed
sudo apt update
sudo apt install nginx -y

# Copy the nginx configuration
sudo cp ~/myos/profsidekick-api/nginx-dual-backend.conf \
    /etc/nginx/sites-available/api.eliteflex.app

# Enable the site
sudo ln -s /etc/nginx/sites-available/api.eliteflex.app \
    /etc/nginx/sites-enabled/

# Test nginx configuration
sudo nginx -t

# If test passes, reload nginx
sudo systemctl reload nginx
```

### 5. Setup SSL Certificate (if not already done)

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx -y

# Get SSL certificate for api.eliteflex.app
sudo certbot --nginx -d api.eliteflex.app

# Certbot will automatically update your nginx config
```

### 6. Start Main Backend

```bash
cd ~/myos/profsidekick-api

# Start the main backend stack
docker-compose up -d

# Check logs
docker-compose logs -f backend
```

### 7. Start Autograder Backend

```bash
cd ~/myos/autograder/profsidekick-api

# Start the autograder backend stack
docker-compose -f docker-compose.autograder.yml up -d

# Check logs
docker-compose -f docker-compose.autograder.yml logs -f backend-autograder
```

## Verification

### Test Main Backend
```bash
curl -H "Origin: https://profsidekick-ai.vercel.app" \
     https://api.eliteflex.app/health
```

### Test Autograder Backend
```bash
curl -H "Origin: https://profsidekick-autograder.vercel.app" \
     https://api.eliteflex.app/health
```

### Check Which Backend Handles Request
Add this to your FastAPI backend to log which instance handles requests:

```python
# In app/main.py
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"[INSTANCE] Request from Origin: {request.headers.get('origin')}")
    response = await call_next(request)
    return response
```

## Management Commands

### Update Main Backend
```bash
cd ~/myos/profsidekick-api
git pull origin main
docker-compose down
docker-compose build
docker-compose up -d
```

### Update Autograder Backend
```bash
cd ~/myos/autograder/profsidekick-api
git pull origin feature/math-autograder-frontend
docker-compose -f docker-compose.autograder.yml down
docker-compose -f docker-compose.autograder.yml build
docker-compose -f docker-compose.autograder.yml up -d
```

### View Logs
```bash
# Main backend
docker logs -f profsidekick-backend

# Autograder backend
docker logs -f profsidekick-backend-autograder

# Nginx
sudo tail -f /var/log/nginx/api.eliteflex.app.access.log
```

### Stop Services
```bash
# Stop main backend
cd ~/myos/profsidekick-api
docker-compose down

# Stop autograder backend
cd ~/myos/autograder/profsidekick-api
docker-compose -f docker-compose.autograder.yml down
```

## Frontend CORS Configuration

Ensure both frontends are configured in your backend CORS settings:

```python
# app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://profsidekick-ai.vercel.app",
        "https://profsidekick-autograder.vercel.app",
        "http://localhost:3000",  # For local development
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Troubleshooting

### If requests go to wrong backend:
1. Check nginx logs: `sudo tail -f /var/log/nginx/api.eliteflex.app.access.log`
2. Verify Origin header is being sent from frontend
3. Test nginx routing with curl (see Verification section above)

### If database migrations fail:
Each backend has its own database, so migrations are independent:
```bash
# Main backend
docker exec -it profsidekick-backend alembic upgrade head

# Autograder backend
docker exec -it profsidekick-backend-autograder alembic upgrade head
```

### Port conflicts:
If ports are already in use, edit the docker-compose files to use different ports.

## Monitoring

Consider setting up monitoring for both backends:

```bash
# Check if both backends are running
docker ps | grep profsidekick-backend

# Check resource usage
docker stats
```

## Backup Strategy

Both backends have separate databases. Backup both:

```bash
# Main database backup
docker exec profsidekick-postgres pg_dump -U profsidekick profsidekick > backup_main_$(date +%Y%m%d).sql

# Autograder database backup
docker exec profsidekick-postgres-autograder pg_dump -U profsidekick profsidekick_autograder > backup_autograder_$(date +%Y%m%d).sql
```
