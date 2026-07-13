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
        self.assistant_prompt: str = ""

        # Per-tier Gemini Files API URIs.
        # Structure: {"pro": {"rubric": "uri", "solution": "uri", "webassign_solution": "uri"}, ...}
        # Tiers: "pro", "flash", "free".  A tier entry is populated only when that
        # tier has an API key configured.  Tiers sharing the same key share the same
        # entry (no duplicate uploads).
        self.gemini_uris: dict[str, dict[str, str]] = {}

        # GCS URIs for Vertex AI caching (optional).
        # Populated at startup when GCS_STATIC_BUCKET is set.
        # Structure: {"rubric": "gs://...", "solution": "gs://...", "webassign_solution": "gs://..."}
        self.vertex_gcs_uris: dict[str, str] = {}

        # Base64-encoded static PDFs — always populated at startup.
        # Used by providers that send files inline (Vertex AI inline fallback, OpenAI).
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
# Gemini Files API upload helpers
# ---------------------------------------------------------------------------

def _upload_one(api_key: str, filename: str) -> tuple[str, str]:
    """Upload one static PDF to Gemini Files API. Returns (uri, expires_at_iso)."""
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
# Per-tier Gemini Files API refresh
# ---------------------------------------------------------------------------

def refresh_static_uris_for_tier(api_key: str, tier: str) -> None:
    """
    Upload any missing or expired static PDFs for one Gemini tier and update
    autograder_cache.gemini_uris[tier] in-place.  Persists to CACHE_JSON.

    Synchronous — call via asyncio.to_thread() from async context.
    """
    cached = _load_cache_json()
    tier_cached: dict = cached.get(tier, {})
    tier_uris: dict[str, str] = {}
    updated = False

    for key, filename in _STATIC_FILES.items():
        entry = tier_cached.get(key, {})
        uri: str = entry.get("uri", "")
        expires_at: str = entry.get("expires_at", "")

        if not uri or not expires_at or _is_expired(expires_at):
            print(f"[CACHE/{tier}] Uploading {filename} to Gemini Files API…")
            uri, expires_at = _upload_one(api_key, filename)
            tier_cached[key] = {"uri": uri, "expires_at": expires_at}
            updated = True
            print(f"[CACHE/{tier}] {filename} → {uri} (expires: {expires_at})")
        else:
            print(f"[CACHE/{tier}] Reusing cached URI for {filename}")

        tier_uris[key] = uri

    autograder_cache.gemini_uris[tier] = tier_uris

    if updated:
        cached[tier] = tier_cached
        _save_cache_json(cached)


# ---------------------------------------------------------------------------
# GCS upload helpers for Vertex AI caching (optional)
# ---------------------------------------------------------------------------

def _upload_to_gcs(bucket_name: str, project: str) -> dict[str, str]:
    """
    Upload static PDFs to GCS and return {key: gs://uri} mapping.
    Raises if google-cloud-storage is not installed or upload fails.
    """
    from google.cloud import storage  # type: ignore

    client = storage.Client(project=project)
    bucket = client.bucket(bucket_name)
    gcs_uris: dict[str, str] = {}

    for key, filename in _STATIC_FILES.items():
        pdf_bytes = (DATA_DIR / filename).read_bytes()
        blob_name = f"autograder/{filename}"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(pdf_bytes, content_type="application/pdf")
        uri = f"gs://{bucket_name}/{blob_name}"
        gcs_uris[key] = uri
        print(f"[CACHE/vertex_gcs] {filename} → {uri}")

    return gcs_uris


# ---------------------------------------------------------------------------
# Public startup entrypoint
# ---------------------------------------------------------------------------

def load_autograder_cache() -> None:
    """
    FastAPI lifespan entrypoint.  Raises RuntimeError on any missing file or
    empty prompt.

    Per-tier Gemini Files API uploads are performed for each tier that has an
    API key configured.  If a tier shares a key with a previously-uploaded tier,
    its URIs are aliased rather than re-uploaded (avoids redundant uploads).

    Vertex AI GCS caching is performed if GCS_STATIC_BUCKET is set; falls back
    silently to inline base64 if GCS upload fails.

    Base64 encoding of static PDFs is always done — used by Vertex AI inline
    path, OpenAI, and as a last-resort fallback.
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

    _assistant_file = DATA_DIR / "assistant_system_prompt.txt"
    if _assistant_file.exists():
        autograder_cache.assistant_prompt = _assistant_file.read_text(encoding="utf-8")

    # Always pre-encode static PDFs to base64 (Vertex AI inline path + OpenAI).
    for key, filename in _STATIC_FILES.items():
        b64 = base64.b64encode((DATA_DIR / filename).read_bytes()).decode("utf-8")
        setattr(autograder_cache, f"{key}_b64", b64)

    # ── Gemini Files API uploads (per tier) ──────────────────────────────────
    # Track uploaded keys so tiers sharing a key reuse the same upload.
    _key_to_tier: dict[str, str] = {}

    pro_key = settings.gemini_pro_api_key or settings.gemini_api_key
    flash_key = settings.gemini_flash_api_key or settings.gemini_free_api_key
    free_key = settings.gemini_free_api_key

    # Pro tier
    if pro_key:
        refresh_static_uris_for_tier(pro_key, "pro")
        _key_to_tier[pro_key] = "pro"
    else:
        print("[STARTUP] Gemini Pro tier disabled (no GEMINI_PRO_API_KEY).")

    # Flash tier
    if flash_key:
        if flash_key in _key_to_tier:
            autograder_cache.gemini_uris["flash"] = autograder_cache.gemini_uris[_key_to_tier[flash_key]]
            print(f"[STARTUP] Gemini Flash reusing URIs from '{_key_to_tier[flash_key]}' tier (same key).")
        else:
            refresh_static_uris_for_tier(flash_key, "flash")
            _key_to_tier[flash_key] = "flash"
    else:
        print("[STARTUP] Gemini Flash tier disabled (no GEMINI_FLASH_API_KEY).")

    # Free tier
    if free_key:
        if free_key in _key_to_tier:
            autograder_cache.gemini_uris["free"] = autograder_cache.gemini_uris[_key_to_tier[free_key]]
            print(f"[STARTUP] Gemini Free reusing URIs from '{_key_to_tier[free_key]}' tier (same key).")
        else:
            refresh_static_uris_for_tier(free_key, "free")
            _key_to_tier[free_key] = "free"
    else:
        print("[STARTUP] Gemini Free tier disabled (no GEMINI_FREE_API_KEY).")

    # ── Vertex AI GCS caching (optional) ────────────────────────────────────
    if settings.gcs_static_bucket and settings.google_cloud_project:
        try:
            gcs_uris = _upload_to_gcs(
                settings.gcs_static_bucket,
                settings.google_cloud_project,
            )
            autograder_cache.vertex_gcs_uris = gcs_uris
            print(
                f"[STARTUP] Vertex AI GCS caching enabled: "
                f"bucket={settings.gcs_static_bucket}"
            )
        except Exception as exc:
            print(
                f"[STARTUP] Vertex AI GCS upload failed (non-fatal — using inline b64): {exc}"
            )
    else:
        print(
            "[STARTUP] Vertex AI GCS caching disabled "
            "(set GCS_STATIC_BUCKET to enable). Using inline base64."
        )

    autograder_cache.loaded = True
    print(
        f"[STARTUP] Autograder cache ready. "
        f"Prompt: {len(autograder_cache.grading_prompt)} chars | "
        f"Gemini tiers with URIs: {list(autograder_cache.gemini_uris.keys())} | "
        f"Vertex GCS: {'yes' if autograder_cache.vertex_gcs_uris else 'no (inline)'}"
    )
