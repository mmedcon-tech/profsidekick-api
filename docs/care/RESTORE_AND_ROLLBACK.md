# Restore and rollback (MyOS Care)

## Before any migration
```bash
export PATH=/opt/homebrew/bin:$PATH
docker exec -i profsidekick-postgres pg_dump -U profsidekick -Fc profsidekick > backup_$(date +%Y%m%d_%H%M).dump
```

## Roll back the Phase 3 migration
Head: `z8a9b0c1d2e3`. Round-trip (upgrade → downgrade → upgrade) was verified on an isolated restore
container with rows intact.
```bash
docker compose exec backend alembic downgrade -1   # drops Phase 3 tables/columns only
docker compose exec backend alembic upgrade head   # re-apply
```

## Restore a dump into an isolated container (rehearsal — never over the live DB first)
```bash
docker run -d --name care-restore -e POSTGRES_PASSWORD=postgres -p 5440:5432 pgvector/pgvector:pg16
docker exec -i care-restore createdb -U postgres profsidekick
docker exec -i care-restore pg_restore -U postgres -d profsidekick < backup_XXXX.dump
# point a scratch backend at :5440, run `alembic current`, spot-check rows, then remove the container
```

## Code rollback
Local branch `myos-care-checkpoint` (api + frontend) is never pushed. Return with
`git switch <previous-branch>`; rebuild with `docker compose up -d --build backend`.

## Feature-level fallbacks (no deploy needed)
* OpenAI key removed → quoted-passage mode.
* ElevenLabs unavailable/quota → text replies continue; UI says "voice service unavailable".
* LiveAvatar unavailable → avatar panel shows an error, chat unaffected.
