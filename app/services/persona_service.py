import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.constants.avatars import AVATARS
from app.database.models import ProfessorPersona, User

logger = logging.getLogger(__name__)


class PersonaService:
    def list_avatars(self) -> List[Dict[str, Any]]:
        return AVATARS

    def _get_avatar(self, avatar_id: str) -> Dict[str, Any]:
        for avatar in AVATARS:
            if avatar["id"] == avatar_id:
                return avatar
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown avatar id: {avatar_id}",
        )

    def get_persona(
        self, db: Session, user: User
    ) -> Optional[ProfessorPersona]:  # noqa: E501
        return (
            db.query(ProfessorPersona)
            .filter(ProfessorPersona.user_id == user.id)
            .first()
        )

    def persona_to_dict(self, persona: ProfessorPersona) -> Dict[str, Any]:
        avatar = self._get_avatar(persona.avatar_id)
        return {
            "id": str(persona.id),
            "userId": str(persona.user_id),
            "avatarId": persona.avatar_id,
            "avatar": avatar,
            "preferences": persona.preferences or {},
            "refinedPrompt": persona.refined_prompt or "",
            "createdAt": (
                persona.created_at.isoformat() if persona.created_at else None
            ),
            "updatedAt": (
                persona.updated_at.isoformat() if persona.updated_at else None
            ),
        }

    def upsert_persona(
        self,
        db: Session,
        user: User,
        avatar_id: str,
        preferences: Dict[str, Any],
        refined_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._get_avatar(avatar_id)
        persona = self.get_persona(db, user)
        if persona is None:
            persona = ProfessorPersona(
                user_id=user.id,
                avatar_id=avatar_id,
                preferences=preferences,
                refined_prompt=refined_prompt or "",
            )
            db.add(persona)
        else:
            persona.avatar_id = avatar_id
            persona.preferences = preferences
            if refined_prompt is not None:
                persona.refined_prompt = refined_prompt
            persona.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(persona)
        return self.persona_to_dict(persona)

    def _build_refined_prompt(
        self,
        avatar: Dict[str, Any],
        preferences: Dict[str, Any],
    ) -> str:
        teaching_style = preferences.get("teachingStyle", "collaborative")
        tone = preferences.get("tone", "encouraging")
        pace = preferences.get("pace", "moderate")
        interaction = preferences.get("interactionLevel", "high")
        focus = preferences.get("subjectFocus", "conceptual understanding")

        name = avatar["name"]
        desc = avatar["description"]
        return f"""# Teaching Persona — {name}

## Identity
You are {name}, an AI teaching assistant.
Personality: {desc}

## Teaching approach
- Style: {teaching_style}
- Tone: {tone}
- Pace: {pace}
- Student interaction: {interaction}
- Primary focus: {focus}

## Behavior
- Stay in character for the entire session.
- Adapt explanations to student level; invite questions often.
- Reference slides explicitly when teaching presentation content.
"""

    async def refine_persona(
        self,
        db: Session,
        user: User,
        avatar_id: str,
        preferences: Dict[str, Any],
    ) -> Dict[str, Any]:
        avatar = self._get_avatar(avatar_id)
        refined = self._build_refined_prompt(avatar, preferences)

        if settings.openai_api_key:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=settings.openai_api_key)
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You refine teaching-assistant prompts. "
                                "Output only the final prompt text, "
                                "no markdown fences."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                "Improve this teaching persona prompt for "
                                f"voice sessions:\n\n{refined}"
                            ),
                        },
                    ],
                    temperature=0.7,
                    max_tokens=1200,
                )
                content = response.choices[0].message.content
                if content and content.strip():
                    refined = content.strip()
            except Exception as exc:
                logger.warning("OpenAI refine failed, using template: %s", exc)

        persona = self.upsert_persona(
            db,
            user,
            avatar_id,
            preferences,
            refined_prompt=refined,
        )
        return persona
