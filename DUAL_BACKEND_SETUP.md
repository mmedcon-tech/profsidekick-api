# Dual Backend VPS Deployment - Quick Start

This setup allows you to run two backend branches concurrently on your Contabo VPS, with nginx routing requests based on which frontend (Origin header) is making the request.

## Architecture

```
api.eliteflex.app (nginx)
    ├─→ Port 8000: Main Backend      → profsidekick-ai.vercel.app
    └─→ Port 8001: Autograder Backend → profsidekick-autograder.vercel.app
```

## Files Created

### Configuration Files
- **docker-compose.autograder.yml** - Docker Compose config for autograder backend (port 8001)
- **nginx-dual-backend.conf** - Nginx config that routes based on Origin header
- **nginx-vps.conf** - Alternative nginx config (more detailed)

### Deployment Scripts
- **setup-vps.sh** - Initial VPS setup (run once)
- **deploy-autograder.sh** - Deploy/update autograder backend
- **check-status.sh** - Check status of both backends

### Systemd Services
- **systemd/profsidekick-main.service** - Auto-start main backend on boot
- **systemd/profsidekick-autograder.service** - Auto-start autograder backend on boot

### Documentation
- **VPS_DUAL_DEPLOYMENT.md** - Complete deployment guide

## Quick Start

### 1. On Your VPS (First Time Setup)

```bash
# Copy setup-vps.sh to your VPS
scp setup-vps.sh user@your-vps-ip:/tmp/

# SSH into VPS and run setup
ssh user@your-vps-ip
bash /tmp/setup-vps.sh
```

This will:
- Install Docker, Docker Compose, and Nginx
- Create directory structure at `/opt/profsidekick/{main,autograder}`
- Clone both branches
- Setup nginx configuration
- Install systemd services

### 2. Configure Environment

Edit the `.env` files for both backends:

```bash
# Main backend
nano ~/myos/profsidekick-api/.env

# Autograder backend
nano ~/myos/autograder/profsidekick-api/.env
```

### 3. Setup SSL Certificate

```bash
sudo certbot --nginx -d api.eliteflex.app
```

### 4. Start Backends

```bash
# Start main backend
cd ~/myos/profsidekick-api
docker-compose up -d

# Start autograder backend
cd ~/myos/autograder/profsidekick-api
docker-compose -f docker-compose.autograder.yml up -d
```

### 5. Check Status

```bash
bash ~/myos/profsidekick-api/check-status.sh
```

## Daily Operations

### Update Autograder Backend

```bash
cd ~/myos/autograder/profsidekick-api
bash deploy-autograder.sh
```

### Update Main Backend

```bash
cd ~/myos/profsidekick-api
git pull origin main
docker-compose down
docker-compose build
docker-compose up -d
```

### View Logs

```bash
# Main backend
docker logs -f profsidekick-backend

# Autograder backend
docker logs -f profsidekick-backend-autograder

# Nginx routing
sudo tail -f /var/log/nginx/api.eliteflex.app.access.log
```

### Restart Services

```bash
# Restart main backend
docker restart profsidekick-backend

# Restart autograder backend
docker restart profsidekick-backend-autograder

# Reload nginx (after config changes)
sudo nginx -t && sudo systemctl reload nginx
```

## Testing

### Test Main Backend
```bash
curl -H "Origin: https://profsidekick-ai.vercel.app" \
     https://api.eliteflex.app/docs
```

### Test Autograder Backend
```bash
curl -H "Origin: https://profsidekick-autograder.vercel.app" \
     https://api.eliteflex.app/docs
```

## Troubleshooting

### Check which backend handles requests

Add this middleware to your FastAPI app to log routing:

```python
@app.middleware("http")
async def log_routing(request: Request, call_next):
    origin = request.headers.get("origin", "no-origin")
    logger.info(f"Request from Origin: {origin}")
    response = await call_next(request)
    return response
```

### If requests go to wrong backend

1. Check nginx logs: `sudo tail -f /var/log/nginx/api.eliteflex.app.access.log`
2. Verify Origin header is sent from frontend
3. Test nginx config: `sudo nginx -t`
4. Reload nginx: `sudo systemctl reload nginx`

### If containers won't start

```bash
# Check Docker logs
docker-compose logs

# Check if ports are in use
sudo netstat -tulpn | grep -E '8000|8001|5433|5434'

# Check disk space
df -h
docker system df
```

### Database migrations fail

```bash
# Main backend
docker exec -it profsidekick-backend alembic upgrade head

# Autograder backend
docker exec -it profsidekick-backend-autograder alembic upgrade head

# Check migration status
docker exec -it profsidekick-backend-autograder alembic current
docker exec -it profsidekick-backend-autograder alembic history
```

## Port Allocation

| Service | Main (8000) | Autograder (8001) |
|---------|-------------|-------------------|
| Backend | 8000 | 8001 |
| PostgreSQL | 5433 | 5434 |
| Redis | 6379 | 6380 |

## CORS Configuration

Make sure both frontends are allowed in your backend CORS settings:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://profsidekick-ai.vercel.app",
        "https://profsidekick-autograder.vercel.app",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Auto-Start on Boot

Both backends are configured to start automatically on VPS boot via systemd:

```bash
# Check service status
sudo systemctl status profsidekick-main
sudo systemctl status profsidekick-autograder

# Enable/disable auto-start
sudo systemctl enable profsidekick-main
sudo systemctl disable profsidekick-autograder
```

## Backup

```bash
# Backup main database
docker exec profsidekick-postgres pg_dump -U profsidekick profsidekick > backup_main_$(date +%Y%m%d).sql

# Backup autograder database
docker exec profsidekick-postgres-autograder pg_dump -U profsidekick profsidekick_autograder > backup_autograder_$(date +%Y%m%d).sql
```

## Resources

- Full Documentation: `VPS_DUAL_DEPLOYMENT.md`
- Nginx Config: `/etc/nginx/sites-available/api.eliteflex.app`
- Main Backend: `~/myos/profsidekick-api`
- Autograder Backend: `~/myos/autograder/profsidekick-api`

## Support

If you encounter issues:
1. Check `check-status.sh` output
2. Review logs for both backends
3. Verify nginx routing with curl tests
4. Check that Origin headers are being sent from frontends
