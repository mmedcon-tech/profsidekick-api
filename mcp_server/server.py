"""MyOS read-only MCP server (Part 4).

Runs in its own image (Dockerfile.mcp) so the API's FastAPI/starlette/anyio pins are untouched.
It holds no data and no database access: each tool forwards to the API's agent endpoints with the
patient-issued agent token. The API checks identity, clinic, ownership, grant scope, expiry,
revocation and enrolment on every call, and writes the patient-visible access log.
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

API = os.environ.get("MYOS_API_URL", "http://backend:8000").rstrip("/")
TOKEN = os.environ.get("MYOS_AGENT_TOKEN", "")

mcp = FastMCP("myos-care")


def _get(path: str) -> dict:
    if not TOKEN:
        return {"error": "No agent token configured. Create one on the MyOS 'Memory & access' page."}
    r = httpx.get(f"{API}/api/care/agent/v1/{path}", headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10)
    if r.status_code != 200:
        try:
            msg = r.json().get("message") or r.json().get("detail")
        except Exception:
            msg = None
        return {"error": msg or f"Access denied ({r.status_code})"}
    return r.json()


@mcp.tool()
def get_my_preferences() -> dict:
    """Read the patient's saved communication preferences (name, language, reading level...). Read-only."""
    return _get("preferences")


@mcp.tool()
def list_my_conversations() -> dict:
    """List the patient's MyOS conversations (titles and dates only, no message content). Read-only."""
    return _get("conversations")


if __name__ == "__main__":
    mcp.run(transport=os.environ.get("MCP_TRANSPORT", "stdio"))
