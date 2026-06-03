import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import get_current_user
from app.schemas.schemas import (
    PromptsResponse,
    SavedPromptCreate,
    SavedPrompt,
    SavedPromptUpdate,
)
from app.services.prompt_service import PromptService

# Set up logger
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["prompts"])


@router.get("/prompts", response_model=PromptsResponse)
async def get_prompts(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    category: Optional[str] = None,
    search: Optional[str] = None,
    include_public: bool = Query(True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        prompt_service = PromptService()
        prompts = await prompt_service.get_prompts(
            db, page, limit, category, search, include_public, current_user
        )
        return prompts
    except Exception as e:
        logger.error(f"❌ Error getting prompts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting prompts: {e}",
        )


@router.post("/prompts", response_model=SavedPrompt)
async def create_prompt(
    prompt_data: SavedPromptCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        prompt_service = PromptService()
        prompt = await prompt_service.create_prompt(db, prompt_data, current_user)
        return prompt
    except Exception as e:
        logger.error(f"❌ Error creating prompt: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating prompt: {e}",
        )


@router.put("/prompts/{prompt_id}", response_model=SavedPrompt)
async def update_prompt(
    prompt_id: str,
    prompt_data: SavedPromptUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        prompt_service = PromptService()
        prompt = await prompt_service.update_prompt(
            db, prompt_id, prompt_data, current_user
        )
        return prompt
    except Exception as e:
        logger.error(f"❌ Error updating prompt: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating prompt: {e}",
        )


@router.delete("/prompts/{prompt_id}", response_model=SavedPrompt)
async def delete_prompt(
    prompt_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        prompt_service = PromptService()
        prompt = await prompt_service.delete_prompt(db, prompt_id, current_user)
        return prompt
    except Exception as e:
        logger.error(f"❌ Error deleting prompt: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting prompt: {e}",
        )
