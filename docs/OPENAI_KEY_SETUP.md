# OpenAI key setup (MyOS Care demo)

The care assistant uses OpenAI (`gpt-4.1`, `app/services/care/chat.py`) to write grounded answers.
Without a valid key the assistant **still works safely**: it quotes the closest approved clinic passage
unedited and labels the reply "AI unavailable — quoted approved clinic material". Safety routing
(needs_clinician / urgent) is rule-based and does not depend on OpenAI.

## 1. Put the key in `.env` (never in chat, git, or screenshots)
1. Create a project key at https://platform.openai.com/api-keys (restrict it to the demo project and
   set a monthly budget cap).
2. Open `profsidekick-api/.env` in an editor and set one line:
   `OPENAI_API_KEY=sk-...` (no quotes, no spaces).
3. `.env` is git-ignored. Do not paste the key into terminals with shared history or into any chat.

## 2. Load it and verify without printing it
```bash
cd profsidekick-api
.venv/bin/python scripts/verify_care_llm.py --rebuild
```
* exit 0 → live LLM verified (reply has provenance `ai_generated`, provider.llm `ok`)
* exit 2 → key missing or still the placeholder
* exit 1 → call failed; the error *kind* is printed (auth / rate_limit / quota / upstream / network)

The script checks the key by shape only and never echoes it. `--rebuild` runs
`docker compose up -d --build backend` so the container picks up the new value.

## 3. Check health
* Public: `GET /api/care/health` → `openai.ok` true, `error_kind` null (no live call).
* Admin: `GET /api/care/admin/status` does a live check and reports latency + error kind.

## 4. Rotate / remove
Revoke the key in the OpenAI dashboard, replace the line in `.env`, re-run step 2.
Removing the key returns the assistant to quoted-passage mode; nothing else breaks.

## Notes
* Demo data is synthetic. Do not send real patient data to OpenAI until a BAA / zero-retention
  agreement is in place (see `docs/care/HIPAA_BLOCKERS.md`).
