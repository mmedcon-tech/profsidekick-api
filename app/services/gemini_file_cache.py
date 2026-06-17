import base64
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.config import settings

# profsidekick-api/data/  (3 parents up from app/services/)
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CACHE_JSON = DATA_DIR / "autograder_cache.json"

_STATIC_FILES = {
    "rubric": "rubric.pdf",
    "solution": "solution.pdf",
    "webassign_solution": "webassign_solution.pdf",
}

_EXPIRY_BUFFER = timedelta(hours=1)


class AutograderCache:
    def __init__(self):
        self.grading_prompt: str = ""
        # Gemini Files API URIs — populated at startup, used by Pro-tier provider only.
        self.rubric_uri: str = ""
        self.solution_uri: str = ""
        self.webassign_solution_uri: str = ""
        # Base64-encoded static PDFs — populated at startup, used by Free-tier and
        # OpenAI providers so they never read from disk during a live request.
        self.rubric_b64: str = ""
        self.solution_b64: str = ""
        self.webassign_solution_b64: str = ""
        self.loaded: bool = False


autograder_cache = AutograderCache()


# ---------------------------------------------------------------------------
# JSON persistence
# ---------------------------------------------------------------------------

def _load_cache_json() -> dict:
    if CACHE_JSON.exists():
        try:
            return json.loads(CACHE_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache_json(data: dict) -> None:
    try:
        CACHE_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[CACHE] Warning: could not persist {CACHE_JSON}: {exc}")


def _is_expired(expires_at_str: str) -> bool:
    try:
        expiry = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) >= expiry - _EXPIRY_BUFFER
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Gemini Files API upload helpers (synchronous — called at startup or via
# asyncio.to_thread() from the recovery path inside GeminiProvider)
# ---------------------------------------------------------------------------

def _upload_one(api_key: str, filename: str) -> tuple[str, str]:
    """Upload one static PDF. Returns (uri, expires_at_iso)."""
    pdf_bytes = (DATA_DIR / filename).read_bytes()
    metadata_json = json.dumps({"file": {"display_name": filename}})
    boundary = "bound_profsidekick"
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{metadata_json}\r\n"
        f"--{boundary}\r\nContent-Type: application/pdf\r\n\r\n"
    ).encode("utf-8") + pdf_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            "https://generativelanguage.googleapis.com/upload/v1beta/files"
            f"?uploadType=multipart&key={api_key}",
            content=body,
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Gemini upload failed for {filename}: HTTP {resp.status_code} — {resp.text}"
        )

    file_info = resp.json().get("file", {})
    file_name_path = file_info.get("name", "")
    expires_at = file_info.get("expirationTime", "")
    uri = file_info.get("uri") or (
        f"https://generativelanguage.googleapis.com/v1beta/{file_name_path}"
        if file_name_path else ""
    )
    if not uri:
        raise RuntimeError(
            f"Gemini upload for {filename} returned no usable URI: {file_info}"
        )

    _poll_until_active(api_key, file_name_path, filename)
    return uri, expires_at


def _poll_until_active(
    api_key: str,
    file_name_path: str,
    display_name: str,
    max_attempts: int = 20,
) -> None:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/{file_name_path}"
        f"?key={api_key}"
    )
    with httpx.Client(timeout=30.0) as client:
        for _ in range(max_attempts):
            resp = client.get(url)
            if resp.status_code == 200:
                state = resp.json().get("state")
                if state == "ACTIVE":
                    return
                if state == "FAILED":
                    raise RuntimeError(
                        f"Gemini file processing failed for {display_name}"
                    )
            time.sleep(2)
    raise RuntimeError(
        f"Gemini file '{display_name}' did not become ACTIVE after {max_attempts * 2}s"
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def refresh_static_uris(api_key: str | None = None) -> None:
    """
    Upload any missing or expired static PDFs to the Gemini Files API and
    update autograder_cache in-place.  Persists results to CACHE_JSON.

    Synchronous — call via asyncio.to_thread() from an async context.
    """
    if api_key is None:
        api_key = settings.gemini_pro_api_key or settings.gemini_api_key

    cached = _load_cache_json()
    updated = False

    for key, filename in _STATIC_FILES.items():
        entry = cached.get(key, {})
        uri: str = entry.get("uri", "")
        expires_at: str = entry.get("expires_at", "")

        if not uri or not expires_at or _is_expired(expires_at):
            print(f"[CACHE] Uploading {filename} to Gemini Files API…")
            uri, expires_at = _upload_one(api_key, filename)
            cached[key] = {"uri": uri, "expires_at": expires_at}
            updated = True
            print(f"[CACHE] {filename} → {uri} (expires: {expires_at})")
        else:
            print(f"[CACHE] Reusing cached URI for {filename}")

        setattr(autograder_cache, f"{key}_uri", uri)

    if updated:
        _save_cache_json(cached)


def load_autograder_cache() -> None:
    """
    FastAPI lifespan entrypoint.  Raises RuntimeError on any missing file,
    empty prompt, or missing API key — which surfaces as a fatal startup error.
    """
    required_files = ["grading_prompt.txt"] + list(_STATIC_FILES.values())
    missing = [f for f in required_files if not (DATA_DIR / f).exists()]
    if missing:
        raise RuntimeError(
            f"FATAL: Autograder cannot start. Missing files in {DATA_DIR}: "
            f"{', '.join(missing)}"
        )

    autograder_cache.grading_prompt = (DATA_DIR / "grading_prompt.txt").read_text(
        encoding="utf-8"
    )
    if not autograder_cache.grading_prompt.strip():
        raise RuntimeError("FATAL: grading_prompt.txt is empty.")

    primary_key = settings.gemini_pro_api_key or settings.gemini_api_key
    if not primary_key:
        raise RuntimeError(
            "FATAL: No Gemini API key found. Set GEMINI_PRO_API_KEY (or legacy GEMINI_API_KEY)."
        )

    # Pre-encode static PDFs to base64 once at startup so Free-tier and OpenAI
    # providers never perform disk I/O during a live request.
    for key, filename in _STATIC_FILES.items():
        b64 = base64.b64encode((DATA_DIR / filename).read_bytes()).decode("utf-8")
        setattr(autograder_cache, f"{key}_b64", b64)

    refresh_static_uris(primary_key)

    autograder_cache.loaded = True
    print(
        f"[STARTUP] Autograder cache ready. "
        f"Prompt: {len(autograder_cache.grading_prompt)} chars"
    )
