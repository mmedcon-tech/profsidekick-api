# Agent runbook (MYOS / ProfSidekick)

Local only. Never push, add remotes or clone. Never print `.env` values; `.env` is git-ignored.

## Run
- Backend (Docker): `docker compose up -d --build backend` → http://localhost:8000 (code is baked into the image: rebuild after changes).
- Frontend: `npm run dev` in `profsidekick-frontend` → http://localhost:3000 (log `/tmp/next-dev-3000.log`).
- Health: `curl localhost:8000/api/care/health`.

## Test
- API: `DATABASE_URL=postgresql://postgres:postgres@localhost:5435/profsidekick_test .venv/bin/pytest -q tests` (container `fert-test-pg`; schema via create_all, AI stubbed).
- Frontend: `node_modules/.bin/tsc --noEmit && node_modules/.bin/vitest run`.
- Browser e2e (synthetic demo users from `/tmp/fert/fertility_demo_users.json`): `node e2e/care-demo.mjs`. TTS is forced to 503 unless `CARE_E2E_REAL_TTS=1` (then exactly one real call).
- LLM: `.venv/bin/python scripts/verify_care_llm.py` (exit 2 = placeholder key) then `--rebuild` once a real key is in `profsidekick-api/.env`; restart the backend container so it loads it.

## Migrate (always on an isolated restore first)
1. Backup: `docker exec profsidekick-postgres pg_dump -U profsidekick -Fc profsidekick > ~/myos-backups/<name>.dump`
2. Restore copy: `docker run -d --name care-restore -e POSTGRES_PASSWORD=postgres -p 5440:5432 pgvector/pgvector:pg16`, `createdb`, `pg_restore --no-owner`.
3. `DATABASE_URL=postgresql://postgres:postgres@localhost:5440/profsidekick .venv/bin/alembic upgrade head && ... downgrade -1 && ... upgrade head`
4. Then live: `docker compose exec -T backend alembic upgrade head`. Remove `care-restore`.

## Roll back
- Schema: `docker compose exec -T backend alembic downgrade z8a9b0c1d2e3` (drops only the integrity columns).
- Data: `pg_restore --clean` from `~/myos-backups/pre_integrity_20261102_0719.dump`.
- Code: `git switch` to the previous commit/branch, rebuild backend.

## Blockers (see TASKS.md)
- OpenAI key placeholder (T19), ElevenLabs quota (T20), LiveAvatar free plan (10 credits, 2-min cap: ≤1 session ≤30 s, User-Agent header required — Cloudflare 1010).
- HIPAA: docs/care/HIPAA_BLOCKERS.md. No compliance claims.

## Retry policy
Max 3 attempts per task. Before each retry: read the failure, find the cause, record it in TASKS.md (Attempts/Evidence). Never weaken, skip or delete a test to make it pass; fix the code, or fix a test only when the test itself is provably wrong (and say so). After 3 failures mark the task blocked with findings and move to independent tasks.
