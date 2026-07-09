"""Dual voice pipeline — subscriber voice preferences, provider catalog, and
TTS usage billing.

Routes:
  GET    /api/voice-catalog       — list voices for a provider
  GET    /api/voice-availability  — per-provider availability (pre-session panel)
  GET    /api/voice-preferences   — saved override + resolved effective voice
  PUT    /api/voice-preferences   — save/replace the override
  DELETE /api/voice-preferences   — clear override (fall back to publisher default)
  POST   /api/sessions/{session_id}/runs/{session_run_id}/voice-usage
         — meter a synthesized utterance
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import (
    PricingConfig,
    Session as SessionModel,
    SessionRun,
    SubscriberVoicePreference,
    User,
)
from app.dependencies.auth import require_subscriber
from app.schemas.schemas import (
    ProviderAvailability,
    ResolvedVoiceResponse,
    VoiceAvailabilityResponse,
    VoiceCatalogEntry,
    VoiceCatalogResponse,
    VoicePreferenceResponse,
    VoicePreferenceUpdate,
    VoicePreferenceWithResolutionResponse,
    VoiceUsageRequest,
    VoiceUsageResponse,
)
from app.services import (
    billing_service,
    voice_catalog_service,
    voice_resolution_service,
)

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


def _get_or_404_avatar_for_user(db: Session, user: User):
    """Voice preferences aren't tied to a specific avatar — resolution needs
    *an* avatar only when previewing the effective voice. We resolve against
    the user's most recently started session's avatar, if any; with none,
    only the saved override (no publisher fallback) is returned."""
    last_run = (
        db.query(SessionRun)
        .filter(SessionRun.user_id == user.id)
        .order_by(SessionRun.start_time.desc())
        .first()
    )
    if not last_run:
        return None
    session = (
        db.query(SessionModel).filter(SessionModel.id == last_run.session_id).first()
    )
    if not session or not session.avatar_id:
        return None
    from app.database.models import Avatar

    return db.query(Avatar).filter(Avatar.id == session.avatar_id).first()


@router.get("/voice-preferences", response_model=VoicePreferenceWithResolutionResponse)
async def get_voice_preference(
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    preference = (
        db.query(SubscriberVoicePreference)
        .filter(SubscriberVoicePreference.user_id == current_user.id)
        .first()
    )

    avatar = _get_or_404_avatar_for_user(db, current_user)
    resolved = None
    if avatar:
        resolution = await voice_resolution_service.resolve_session_voice(
            db, avatar, current_user
        )
        resolved = ResolvedVoiceResponse(
            provider=resolution.provider,
            voice_id=resolution.voice_id,
            dialect=resolution.dialect,
            source=resolution.source,
        )
    elif preference and preference.is_valid and preference.voice_id:
        resolved = ResolvedVoiceResponse(
            provider=preference.provider,
            voice_id=preference.voice_id,
            dialect=preference.dialect,
            source="subscriber",
        )
    else:
        resolved = ResolvedVoiceResponse(
            provider="elevenlabs", voice_id="", dialect=None, source="publisher"
        )

    return VoicePreferenceWithResolutionResponse(
        preference=(
            VoicePreferenceResponse.model_validate(preference) if preference else None
        ),
        resolved=resolved,
    )


@router.put("/voice-preferences", response_model=VoicePreferenceResponse)
async def set_voice_preference(
    data: VoicePreferenceUpdate,
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    if data.provider == "openai" and not voice_catalog_service.is_known_openai_voice(
        data.voice_id
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{data.voice_id}' is not a recognized OpenAI TTS voice",
        )

    reachable = await voice_catalog_service.check_voice_reachable(
        data.provider, data.voice_id
    )
    if not reachable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{data.voice_id}' is not a valid/reachable {data.provider} voice",
        )

    preference = (
        db.query(SubscriberVoicePreference)
        .filter(SubscriberVoicePreference.user_id == current_user.id)
        .first()
    )
    if preference:
        preference.provider = data.provider
        preference.voice_id = data.voice_id
        preference.dialect = data.dialect
        preference.is_valid = True
        preference.updated_at = datetime.utcnow()
    else:
        preference = SubscriberVoicePreference(
            id=uuid.uuid4(),
            user_id=current_user.id,
            provider=data.provider,
            voice_id=data.voice_id,
            dialect=data.dialect,
            is_valid=True,
        )
        db.add(preference)

    db.commit()
    db.refresh(preference)
    return VoicePreferenceResponse.model_validate(preference)


@router.delete("/voice-preferences", status_code=status.HTTP_204_NO_CONTENT)
async def clear_voice_preference(
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    db.query(SubscriberVoicePreference).filter(
        SubscriberVoicePreference.user_id == current_user.id
    ).delete()
    db.commit()


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
