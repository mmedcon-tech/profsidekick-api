# Runbook: MyOS read-only MCP server

**What it is.** `mcp_server/server.py` is an MCP server built on the official Python SDK (`mcp==1.30.0`, pinned in
`requirements-mcp.txt`). It exposes two read-only tools: `get_my_preferences` and `list_my_conversations`.

**Why it has its own image.** Every available `mcp` release needs starlette ≥ 1.x and anyio ≥ 4. The API pins
fastapi 0.104.1, which needs starlette 0.27 and anyio 3.7. Upgrading the API's core web stack just for this was out of
scope, so the server runs from `Dockerfile.mcp` with its own requirements. It has no database access. Each tool calls
the API's `/api/care/agent/v1/*` endpoints with the patient's agent token (using httpx, which the SDK already depends on).

**Who enforces access.** The API does, on every call (`app/services/care/agent_access.authorize`). It checks, in order:
- the token hash matches a grant;
- the grant hasn't been revoked;
- the grant hasn't expired;
- the tool's scope was granted;
- the patient is still enrolled at the grant's clinic.

Identity and clinic come only from the grant, and no tool takes a patient or clinic argument. Every allowed or denied
call is written to the access log, which the patient can see. Revoking a grant takes effect on the next call.

**How to run it.**
1. The patient creates a grant (scopes plus a 1–90 day expiry) on *Memory & access*. The token is shown once; only its
   SHA-256 is stored.
2. Build the image: `docker compose --profile mcp build mcp`
3. Run it over stdio: `docker compose --profile mcp run --rm -e MYOS_AGENT_TOKEN=<token> mcp`
4. Smoke test: `docker compose --profile mcp run --rm -e MYOS_AGENT_TOKEN=<token> mcp python /srv/smoke.py`

**How to upgrade.** Bump the pin in `requirements-mcp.txt`, rebuild, and rerun the smoke test with a valid grant, then
again after revoking it (it should return "Agent access denied").

**Rollback.** Stop using the `mcp` profile. The API endpoints don't depend on it.
