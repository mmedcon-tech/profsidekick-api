from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import User, SavedPrompt
from app.schemas.schemas import PaginationInfo, PromptsResponse, SavedPromptCreate, SavedPromptUpdate, SavedPrompt as SavedPromptSchema
from fastapi import HTTPException, status
import logging

logger = logging.getLogger(__name__)

class PromptService:
    def __init__(self):
        self.cache_ttl = 3600 * 24  # 24 hours

    async def get_prompts(
            self,
            db: Session,
            page: int,
            limit: int,
            category: Optional[str],
            search: Optional[str],
            include_public: bool,
            current_user: User
        ) -> PromptsResponse:
        try:
            db_prompts = db.query(SavedPrompt).filter(SavedPrompt.user_id == current_user.id).all()
            default_prompts = db.query(SavedPrompt).filter(SavedPrompt.is_default == True).all()
            for db_prompt in db_prompts:
                SavedPromptSchema.model_validate(db_prompt)
            logger.info(f"🔍 Prompts found: {db_prompts}")
            return PromptsResponse(prompts=db_prompts, default_prompts=default_prompts, pagination=PaginationInfo(page=page, limit=limit, total=len(db_prompts), totalPages=len(db_prompts)//limit))
        except Exception as e:
            logger.error(f"❌ Error getting prompts: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error getting prompts: {e}"
            )
        
    async def create_prompt(self, db: Session, prompt_data: SavedPromptCreate, current_user: User) -> SavedPrompt:
        try:
            new_prompt = SavedPrompt(
                name=prompt_data.name,
                description=prompt_data.description,
                content=prompt_data.content,
                category=prompt_data.category,
                tags=prompt_data.tags,
                is_default=prompt_data.is_default,
                is_public=prompt_data.is_public,
                user_id=current_user.id)
            db.add(new_prompt)
            db.commit()
            db.refresh(new_prompt)
            return new_prompt
        except Exception as e:
            logger.error(f"❌ Error creating prompt: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error creating prompt: {e}"
            )
        
    async def update_prompt(self, db: Session, prompt_id: str, prompt_data: SavedPromptUpdate, current_user: User) -> SavedPrompt:
        try:
            prompt = db.query(SavedPrompt).filter(SavedPrompt.id == prompt_id, SavedPrompt.user_id == current_user.id).first()
            if not prompt:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Prompt not found"
                )
            prompt.name = prompt_data.name or prompt.name
            prompt.description = prompt_data.description or prompt.description
            prompt.content = prompt_data.content or prompt.content
            prompt.category = prompt_data.category or prompt.category
            prompt.tags = prompt_data.tags or prompt.tags
            prompt.is_public = prompt_data.is_public or prompt.is_public
            prompt.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(prompt)
            return prompt
        except Exception as e:
            logger.error(f"❌ Error updating prompt: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error updating prompt: {e}"
            )
        
    async def delete_prompt(self, db: Session, prompt_id: str, current_user: User) -> SavedPrompt:
        try:
            prompt = db.query(SavedPrompt).filter(SavedPrompt.id == prompt_id, SavedPrompt.user_id == current_user.id).first()
            if not prompt:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Prompt not found"
                )
            db.delete(prompt)
            db.commit()
            return prompt
        except Exception as e:
            logger.error(f"❌ Error deleting prompt: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error deleting prompt: {e}"
            )