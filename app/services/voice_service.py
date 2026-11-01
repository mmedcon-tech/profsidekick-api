"""
ElevenLabs voices and instant voice clones, and the LiveAvatar avatar list,
for the publisher's avatar settings page.

The API holds ELEVENLABS_API_KEY and LIVEAVATAR_API_KEY. Provider response
bodies are never passed to the client or logged (they can include account
details); callers get a short message and an HTTP status instead.
"""

import logging
from typing import BinaryIO, List, Optional, Tuple

import httpx
from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"
LIVEAVATAR_BASE_URL = "https://api.liveavatar.com/v1"

# Upload limits for clone samples. ElevenLabs asks for at least 5 s per file and
# 10 s in total, and recommends 1-2 minutes; the browser checks durations.
MAX_SAMPLE_FILES = 10
MAX_SAMPLE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_SAMPLE_BYTES = 50 * 1024 * 1024
ALLOWED_SAMPLE_EXTENSIONS = {"mp3", "wav", "m4a", "webm", "ogg"}

NOT_CONFIGURED = "Voice cloning isn't configured on the server"
PROVIDER_REFUSED = "The voice provider refused the request (check plan/quota)"
PROVIDER_FAILED = "The voice provider could not be reached. Try again later."

# (filename, file object, content type), as httpx expects for multipart files.
SampleFile = Tuple[str, BinaryIO, str]


def _sniff_audio(head: bytes) -> Optional[str]:
    """Audio format from the file's first bytes, or None if not a known one."""
    if head[:3] == b"ID3" or (
        len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0
    ):
        return "mp3"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[4:8] == b"ftyp":
        return "m4a"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if head[:4] == b"OggS":
        return "ogg"
    return None


def validate_clone_samples(files: List[SampleFile]) -> None:
    """Check count, extension, magic bytes and sizes. Rewinds each file."""
    if not files:
        raise HTTPException(status_code=400, detail="Add at least one voice sample")
    if len(files) > MAX_SAMPLE_FILES:
        raise HTTPException(
            status_code=400, detail=f"Use at most {MAX_SAMPLE_FILES} samples"
        )
    total = 0
    for filename, fileobj, _ in files:
        ext = (filename or "").rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_SAMPLE_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"{filename}: use an mp3, wav, m4a, webm or ogg file",
            )
        head = fileobj.read(12)
        if _sniff_audio(head) is None:
            raise HTTPException(
                status_code=400, detail=f"{filename} is not a recognised audio file"
            )
        fileobj.seek(0, 2)
        size = fileobj.tell()
        fileobj.seek(0)
        if size > MAX_SAMPLE_BYTES:
            raise HTTPException(
                status_code=400, detail=f"{filename} is larger than 10 MB"
            )
        total += size
    if total > MAX_TOTAL_SAMPLE_BYTES:
        raise HTTPException(
            status_code=400, detail="Samples are larger than 50 MB in total"
        )


def _elevenlabs_key() -> str:
    if not settings.elevenlabs_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=NOT_CONFIGURED
        )
    return settings.elevenlabs_api_key


PLAN_CODES = {"can_not_use_instant_voice_cloning"}
PLAN_REQUIRED = (
    "Voice cloning needs a paid ElevenLabs plan (Starter or higher). "
    "Pick a stock voice for now, or upgrade the ElevenLabs account."
)


def _provider_code(res: httpx.Response) -> Optional[str]:
    """ElevenLabs' machine-readable error code (detail.status), never its text."""
    try:
        detail = res.json().get("detail")
    except Exception:
        return None
    return detail.get("status") if isinstance(detail, dict) else None


def _raise_for_provider(res: httpx.Response, what: str) -> None:
    """Map a provider error to a client-safe HTTPException."""
    if res.is_success:
        return
    logger.warning("%s failed with status %s", what, res.status_code)
    if _provider_code(res) in PLAN_CODES:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=PLAN_REQUIRED
        )
    if res.status_code in (400, 422):
        raise HTTPException(
            status_code=400,
            detail=(
                "ElevenLabs could not use these samples. Each must be at least "
                "5 seconds of clear speech (10 seconds in total) in a supported "
                "audio format."
            ),
        )
    if res.status_code in (401, 402, 403, 429):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=PROVIDER_REFUSED
        )
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=PROVIDER_FAILED)


async def list_elevenlabs_voices(search: Optional[str] = None) -> List[dict]:
    """Voices the account can use (stock and its own clones), up to 300."""
    key = _elevenlabs_key()
    voices: List[dict] = []
    params = {"page_size": 100, "include_total_count": "false"}
    if search:
        params["search"] = search
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for _ in range(3):
                res = await client.get(
                    f"{ELEVENLABS_BASE_URL}/v2/voices",
                    headers={"xi-api-key": key},
                    params=params,
                )
                _raise_for_provider(res, "ElevenLabs voice list")
                data = res.json()
                for v in data.get("voices") or []:
                    voices.append(
                        {
                            "voice_id": v.get("voice_id"),
                            "name": v.get("name"),
                            "category": v.get("category"),
                            "labels": v.get("labels") or {},
                            "preview_url": v.get("preview_url"),
                        }
                    )
                token = data.get("next_page_token")
                if not data.get("has_more") or not token:
                    break
                params["next_page_token"] = token
    except httpx.HTTPError as exc:
        logger.warning("ElevenLabs voice list unreachable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=PROVIDER_FAILED
        )
    return voices


async def create_instant_clone(
    name: str,
    files: List[SampleFile],
    remove_background_noise: bool = False,
) -> dict:
    """POST /v1/voices/add. Returns {voice_id, requires_verification}."""
    key = _elevenlabs_key()
    data = {
        "name": name,
        "remove_background_noise": "true" if remove_background_noise else "false",
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            res = await client.post(
                f"{ELEVENLABS_BASE_URL}/v1/voices/add",
                headers={"xi-api-key": key},
                data=data,
                files=[("files", f) for f in files],
            )
    except httpx.HTTPError as exc:
        logger.warning("ElevenLabs voice clone unreachable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=PROVIDER_FAILED
        )
    _raise_for_provider(res, "ElevenLabs voice clone")
    body = res.json()
    voice_id = body.get("voice_id")
    if not voice_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=PROVIDER_FAILED
        )
    return {
        "voice_id": voice_id,
        "requires_verification": bool(body.get("requires_verification")),
    }


async def delete_elevenlabs_voice(voice_id: str) -> None:
    """Delete a voice at ElevenLabs. A voice that is already gone counts as deleted."""
    key = _elevenlabs_key()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.delete(
                f"{ELEVENLABS_BASE_URL}/v1/voices/{voice_id}",
                headers={"xi-api-key": key},
            )
    except httpx.HTTPError as exc:
        logger.warning("ElevenLabs voice delete unreachable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=PROVIDER_FAILED
        )
    if res.status_code == 404:
        return
    _raise_for_provider(res, "ElevenLabs voice delete")


async def list_liveavatar_avatars() -> List[dict]:
    """Public LiveAvatar avatars plus the account's own, active ones only."""
    if not settings.liveavatar_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The streaming avatar isn't configured on the server",
        )
    headers = {"X-API-KEY": settings.liveavatar_api_key}
    avatars: List[dict] = []
    seen = set()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for path in ("/avatars", "/avatars/public"):
                res = await client.get(
                    f"{LIVEAVATAR_BASE_URL}{path}",
                    headers=headers,
                    params={"page_size": 100},
                )
                if not res.is_success:
                    logger.warning(
                        "LiveAvatar %s failed with status %s", path, res.status_code
                    )
                    continue
                for a in (res.json().get("data") or {}).get("results") or []:
                    if not a.get("id") or a["id"] in seen:
                        continue
                    if a.get("status") not in (None, "ACTIVE") or a.get("is_expired"):
                        continue
                    seen.add(a["id"])
                    avatars.append(
                        {
                            "id": a["id"],
                            "name": a.get("name"),
                            "preview_url": a.get("preview_url"),
                        }
                    )
    except httpx.HTTPError as exc:
        logger.warning("LiveAvatar avatar list unreachable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=PROVIDER_FAILED
        )
    return avatars


# voice_id -> (category, fetched_at). Stock ("premade") voices never change.
_category_cache: dict = {}
_CATEGORY_TTL_S = 3600


async def get_voice_category(voice_id: str) -> Optional[str]:
    """ElevenLabs category of a voice ("premade", "cloned", ...), or None."""
    import time

    hit = _category_cache.get(voice_id)
    if hit and time.monotonic() - hit[1] < _CATEGORY_TTL_S:
        return hit[0]
    key = _elevenlabs_key()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(
                f"{ELEVENLABS_BASE_URL}/v1/voices/{voice_id}",
                headers={"xi-api-key": key},
            )
    except httpx.HTTPError as exc:
        logger.warning("ElevenLabs voice lookup unreachable: %s", type(exc).__name__)
        return None
    if not res.is_success:
        logger.info("ElevenLabs voice lookup returned %s", res.status_code)
        return None
    category = (res.json() or {}).get("category")
    _category_cache[voice_id] = (category, time.monotonic())
    return category
