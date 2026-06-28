#!/bin/sh
# Fix ownership of bind-mounted volumes (host may have created them as root).
chown -R app:app /app/uploads /app/static 2>/dev/null || true

# Drop to the app user and start.
exec gosu app sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --limit-concurrency 100 --timeout-keep-alive 30 --proxy-headers --forwarded-allow-ips=*"
