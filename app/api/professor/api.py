import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.professor import require_professor
from app.services.persona_service import PersonaService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["professor-persona"])
persona_service = PersonaService()


class PersonaPreferenceSelections(BaseModel):
    teachingStyle: str = Field(default="collaborative")
    tone: str = Field(default="encouraging")
    pace: str = Field(default="moderate")
    interactionLevel: str = Field(default="high")
    subjectFocus: str = Field(default="conceptual understanding")


class ProfessorPersonaUpsert(BaseModel):
    avatarId: str
    preferences: PersonaPreferenceSelections
    refinedPrompt: Optional[str] = None


class PersonaRefineRequest(BaseModel):
    avatarId: str
    preferences: PersonaPreferenceSelections


@router.get("/avatars")
async def list_avatars(
    current_user: User = Depends(require_professor),
) -> Dict[str, List[Dict[str, Any]]]:
    return {"avatars": persona_service.list_avatars()}


@router.get("/professor/persona")
async def get_professor_persona(
    current_user: User = Depends(require_professor),
    db: Session = Depends(get_db),
):
    persona = persona_service.get_persona(db, current_user)
    if persona is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persona not found",
        )
    return persona_service.persona_to_dict(persona)


@router.post("/professor/persona")
async def upsert_professor_persona(
    body: ProfessorPersonaUpsert,
    current_user: User = Depends(require_professor),
    db: Session = Depends(get_db),
):
    try:
        return persona_service.upsert_persona(
            db,
            current_user,
            body.avatarId,
            body.preferences.model_dump(),
            refined_prompt=body.refinedPrompt,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Persona upsert failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post("/professor/persona/refine")
async def refine_professor_persona(
    body: PersonaRefineRequest,
    current_user: User = Depends(require_professor),
    db: Session = Depends(get_db),
):
    try:
        return await persona_service.refine_persona(
            db,
            current_user,
            body.avatarId,
            body.preferences.model_dump(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Persona refine failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
