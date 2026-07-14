"""Voice catalog and TTS usage billing — publisher-only voice selection.

Routes:
  GET    /api/voice-catalog       — list voices for a provider
  GET    /api/voice-availability  — per-provider availability (pre-session panel)
  POST   /api/sessions/{session_id}/runs/{session_run_id}/voice-usage
         — meter a synthesized utterance
"""


import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import PricingConfig, SessionRun, User
from app.dependencies.auth import require_subscriber
from app.schemas.schemas import (
    ProviderAvailability,
    VoiceAvailabilityResponse,
    VoiceCatalogEntry,
    VoiceCatalogResponse,
    VoiceUsageRequest,
    VoiceUsageResponse,
)
from app.services import billing_service, voice_catalog_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["voice"])


def _cost_per_1k_characters(provider: str, db: Session) -> Decimal:
    pricing = (
        db.query(PricingConfig)
        .filter(PricingConfig.operation_type == f"tts_{provider}")
        .first()
    )
    if not pricing:
        return Decimal("0")
    # Character-based cost reuses the token-shaped column as $/1k characters
    # (see billing_service.charge_usage callers below).
    return Decimal(str(pricing.cost_per_1k_input_tokens))


@router.get("/voice-catalog", response_model=VoiceCatalogResponse)
async def get_voice_catalog(
    provider: str = Query(..., pattern="^(openai|elevenlabs)$"),
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    if provider == "openai":
        voices = voice_catalog_service.OPENAI_TTS_VOICES
    else:
        voices = await voice_catalog_service.list_elevenlabs_voices()

    return VoiceCatalogResponse(
        provider=provider,
        voices=[VoiceCatalogEntry(**v) for v in voices],
        cost_per_1k_characters_usd=_cost_per_1k_characters(provider, db),
    )


@router.get("/voice-availability", response_model=VoiceAvailabilityResponse)
async def get_voice_availability(
    current_user: User = Depends(require_subscriber),
):
    """Provider-level availability for the pre-session voice panel — lets it
    disable a provider (and auto-select the other) *before* the subscriber
    picks a voice that would fail mid-session, rather than discovering a
    platform-side outage only when synthesis is attempted."""
    openai_available, openai_reason = (
        await voice_catalog_service.check_provider_availability("openai")
    )
    elevenlabs_available, elevenlabs_reason = (
        await voice_catalog_service.check_provider_availability("elevenlabs")
    )
    return VoiceAvailabilityResponse(
        openai=ProviderAvailability(available=openai_available, reason=openai_reason),
        elevenlabs=ProviderAvailability(
            available=elevenlabs_available, reason=elevenlabs_reason
        ),
    )


@router.post(
    "/sessions/{session_id}/runs/{session_run_id}/voice-usage",
    response_model=VoiceUsageResponse,
)
async def log_voice_usage(
    session_id: str,
    session_run_id: str,
    data: VoiceUsageRequest,
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    session_run = (
        db.query(SessionRun).filter(SessionRun.session_run_id == session_run_id).first()
    )
    if not session_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session run not found"
        )
    if current_user.role != "admin" and str(session_run.user_id) != str(
        current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorised"
        )

    record = billing_service.charge_usage(
        user_id=current_user.id,
        operation_type=f"tts_{data.provider}",
        input_tokens=data.character_count,
        output_tokens=0,
        db=db,
        session_run_id=session_run.id,
        idempotency_key=data.idempotency_key,
    )
    balance_info = billing_service.get_active_balance(current_user.id, db)
    return VoiceUsageResponse(
        operation_type=record.operation_type,
        credits_charged=record.credits_charged,
        new_balance=balance_info["balance"],
    )
