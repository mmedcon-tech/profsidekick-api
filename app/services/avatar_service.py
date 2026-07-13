import uuid
from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status
from app.database.models import (
    Avatar, AvatarTemplate, AvatarConfiguration,
    PublisherAvatarProfile,
    Rubric, KnowledgeDocument, ReferenceSolution,
    ProgramAvatar,
)
from app.services.prompt_generator import generate_teaching_persona_prompt
from app.schemas.schemas import (
    AvatarCreate, AvatarUpdate,
    AvatarConfigurationCreate, AvatarConfigurationUpdate,
    RubricCreate,
)


def _enrich_avatar(avatar: Avatar) -> Avatar:
    """Project computed fields onto the avatar so Pydantic serialises them."""
    avatar.template_image_url = (
        avatar.template.avatar_image_path
        if avatar.template and avatar.template.avatar_image_path
        else None
    )
    avatar.template_name = (
        avatar.template.name if avatar.template else None
    )
    return avatar


class AvatarService:

    # ── Ownership guard ──────────────────────────────────────────────────

    def _require_owner(self, avatar: Avatar, publisher_id) -> None:
        """Raises 403 if the requesting publisher does not own the avatar."""
        if str(avatar.publisher_id) != str(publisher_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this avatar",
            )

    # ── Avatar CRUD ──────────────────────────────────────────────────────

    def _load_one(self, db: Session, avatar_id) -> Optional[Avatar]:
        """Load a single avatar with template, configuration, and profile eagerly."""
        av = (
            db.query(Avatar)
            .options(
                joinedload(Avatar.template),
                joinedload(Avatar.profile),
                joinedload(Avatar.configuration)
                .joinedload(AvatarConfiguration.rubrics),
                joinedload(Avatar.configuration)
                .joinedload(AvatarConfiguration.knowledge_documents),
                joinedload(Avatar.configuration)
                .joinedload(AvatarConfiguration.reference_solutions),
            )
            .filter(Avatar.id == avatar_id)
            .first()
        )
        return _enrich_avatar(av) if av else None

    def _load_many(self, query) -> List[Avatar]:
        """Run a query that already has joinedload(Avatar.template) applied."""
        return [_enrich_avatar(av) for av in query.options(joinedload(Avatar.profile)).all()]

    async def create_avatar(
        self,
        db: Session,
        publisher_id,
        data: AvatarCreate,
    ) -> Avatar:
        template = db.query(AvatarTemplate).filter(
            AvatarTemplate.id == data.template_id,
            AvatarTemplate.is_active == True,
        ).first()
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Avatar template not found or inactive",
            )

        avatar = Avatar(
            id=uuid.uuid4(),
            template_id=data.template_id,
            publisher_id=publisher_id,
            name=data.name,
            description=data.description,
            is_published=False,
            subscription_cost=template.subscription_cost,
            template_version_id=template.current_version_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(avatar)
        db.commit()
        db.refresh(avatar)

        # Create teaching profile if preferences were supplied
        prefs = data.teaching_preferences
        if prefs:
            refined = generate_teaching_persona_prompt(
                avatar_name=data.name,
                avatar_description=data.description,
                teaching_pace=prefs.teaching_pace,
                questioning_style=prefs.questioning_style,
                formality_level=prefs.formality_level,
                depth_level=prefs.depth_level,
                encouragement_level=prefs.encouragement_level,
                language_level=prefs.language_level,
            )
            profile = PublisherAvatarProfile(
                id=uuid.uuid4(),
                publisher_avatar_id=avatar.id,
                teaching_pace=prefs.teaching_pace,
                questioning_style=prefs.questioning_style,
                formality_level=prefs.formality_level,
                depth_level=prefs.depth_level,
                encouragement_level=prefs.encouragement_level,
                language_level=prefs.language_level,
                refined_prompt=refined,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(profile)
            db.commit()

        # Link to program if program_id was supplied
        if data.program_id:
            db.add(
                ProgramAvatar(
                    id=uuid.uuid4(),
                    program_id=data.program_id,
                    avatar_id=avatar.id,
                    added_at=datetime.utcnow(),
                )
            )
            db.commit()

        return self._load_one(db, avatar.id)

    async def get_avatar(self, db: Session, avatar_id) -> Optional[Avatar]:
        return self._load_one(db, avatar_id)

    async def list_publisher_avatars(
        self, db: Session, publisher_id, program_id: Optional[UUID] = None
    ) -> Tuple[List[Avatar], int]:
        query = (
            db.query(Avatar)
            .options(joinedload(Avatar.template))
            .filter(Avatar.publisher_id == publisher_id)
        )
        if program_id:
            query = query.join(ProgramAvatar, ProgramAvatar.avatar_id == Avatar.id).filter(
                ProgramAvatar.program_id == program_id
            )
        avatars = self._load_many(query.order_by(Avatar.created_at.desc()))
        return avatars, len(avatars)

    async def list_published_avatars(
        self, db: Session
    ) -> Tuple[List[Avatar], int]:
        avatars = self._load_many(
            db.query(Avatar)
            .options(joinedload(Avatar.template))
            .filter(Avatar.is_published == True)
            .order_by(Avatar.created_at.desc())
        )
        return avatars, len(avatars)

    async def list_all_avatars(
        self, db: Session
    ) -> Tuple[List[Avatar], int]:
        avatars = self._load_many(
            db.query(Avatar)
            .options(joinedload(Avatar.template))
            .order_by(Avatar.created_at.desc())
        )
        return avatars, len(avatars)

    async def update_avatar(
        self,
        db: Session,
        avatar_id,
        publisher_id,
        data: AvatarUpdate,
    ) -> Avatar:
        avatar = await self.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        self._require_owner(avatar, publisher_id)

        if data.name is not None:
            avatar.name = data.name
        if data.description is not None:
            avatar.description = data.description

        avatar.updated_at = datetime.utcnow()
        db.commit()
        return self._load_one(db, avatar_id)

    async def publish_avatar(
        self, db: Session, avatar_id, publisher_id
    ) -> Avatar:
        avatar = await self.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        self._require_owner(avatar, publisher_id)

        if not avatar.configuration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Avatar must have a configuration before it can be published",
            )

        avatar.is_published = True
        avatar.updated_at = datetime.utcnow()
        db.commit()
        return self._load_one(db, avatar_id)

    async def delete_avatar(
        self, db: Session, avatar_id, publisher_id
    ) -> None:
        avatar = await self.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        self._require_owner(avatar, publisher_id)

        db.delete(avatar)
        db.commit()

    # ── AvatarConfiguration ──────────────────────────────────────────────

    async def create_configuration(
        self,
        db: Session,
        avatar_id,
        publisher_id,
        data: AvatarConfigurationCreate,
    ) -> AvatarConfiguration:
        avatar = await self.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        self._require_owner(avatar, publisher_id)

        if avatar.configuration:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Configuration already exists — use PUT to update",
            )

        config = AvatarConfiguration(
            id=uuid.uuid4(),
            avatar_id=avatar.id,
            voice=data.voice,
            language=data.language,
            difficulty_level=data.difficulty_level,
            additional_settings=data.additional_settings,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(config)
        db.commit()
        db.refresh(config)
        return config

    async def get_configuration(
        self, db: Session, avatar_id, publisher_id
    ) -> AvatarConfiguration:
        avatar = await self.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        self._require_owner(avatar, publisher_id)

        if not avatar.configuration:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")

        return avatar.configuration

    async def update_configuration(
        self,
        db: Session,
        avatar_id,
        publisher_id,
        data: AvatarConfigurationUpdate,
    ) -> AvatarConfiguration:
        avatar = await self.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        self._require_owner(avatar, publisher_id)

        if not avatar.configuration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Configuration not found — use POST to create",
            )

        config = avatar.configuration
        if data.voice is not None:
            config.voice = data.voice
        if data.language is not None:
            config.language = data.language
        if data.difficulty_level is not None:
            config.difficulty_level = data.difficulty_level
        if data.additional_settings is not None:
            config.additional_settings = data.additional_settings

        config.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(config)
        return config

    # ── Rubrics ──────────────────────────────────────────────────────────

    async def add_rubric(
        self,
        db: Session,
        avatar_id,
        publisher_id,
        data: RubricCreate,
    ) -> Rubric:
        avatar = await self.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        self._require_owner(avatar, publisher_id)
        if not avatar.configuration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Create an avatar configuration before adding rubrics",
            )

        rubric = Rubric(
            id=uuid.uuid4(),
            avatar_configuration_id=avatar.configuration.id,
            title=data.title,
            content=data.content,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(rubric)
        db.commit()
        db.refresh(rubric)
        return rubric

    async def delete_rubric(
        self, db: Session, avatar_id, rubric_id, publisher_id
    ) -> None:
        avatar = await self.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        self._require_owner(avatar, publisher_id)

        rubric = db.query(Rubric).filter(Rubric.id == rubric_id).first()
        if not rubric:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rubric not found")
        if not avatar.configuration or rubric.avatar_configuration_id != avatar.configuration.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Rubric does not belong to this avatar",
            )

        db.delete(rubric)
        db.commit()

    # ── Knowledge Documents ──────────────────────────────────────────────

    async def add_knowledge_document(
        self,
        db: Session,
        avatar_id,
        publisher_id,
        title: str,
        content_text: Optional[str] = None,
        file_path: Optional[str] = None,
        file_name: Optional[str] = None,
        file_size: Optional[int] = None,
        file_type: Optional[str] = None,
    ) -> KnowledgeDocument:
        avatar = await self.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        self._require_owner(avatar, publisher_id)
        if not avatar.configuration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Create an avatar configuration before adding knowledge documents",
            )

        doc = KnowledgeDocument(
            id=uuid.uuid4(),
            avatar_configuration_id=avatar.configuration.id,
            title=title,
            content_text=content_text,
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc

    async def delete_knowledge_document(
        self, db: Session, avatar_id, doc_id, publisher_id
    ) -> None:
        avatar = await self.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        self._require_owner(avatar, publisher_id)

        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge document not found")
        if not avatar.configuration or doc.avatar_configuration_id != avatar.configuration.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Document does not belong to this avatar",
            )

        db.delete(doc)
        db.commit()

    # ── Reference Solutions ──────────────────────────────────────────────

    async def add_reference_solution(
        self,
        db: Session,
        avatar_id,
        publisher_id,
        title: str,
        content_text: Optional[str] = None,
        file_path: Optional[str] = None,
        file_name: Optional[str] = None,
        file_size: Optional[int] = None,
        file_type: Optional[str] = None,
    ) -> ReferenceSolution:
        avatar = await self.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        self._require_owner(avatar, publisher_id)
        if not avatar.configuration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Create an avatar configuration before adding reference solutions",
            )

        solution = ReferenceSolution(
            id=uuid.uuid4(),
            avatar_configuration_id=avatar.configuration.id,
            title=title,
            content_text=content_text,
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(solution)
        db.commit()
        db.refresh(solution)
        return solution

    async def delete_reference_solution(
        self, db: Session, avatar_id, solution_id, publisher_id
    ) -> None:
        avatar = await self.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        self._require_owner(avatar, publisher_id)

        solution = db.query(ReferenceSolution).filter(ReferenceSolution.id == solution_id).first()
        if not solution:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reference solution not found")
        if not avatar.configuration or solution.avatar_configuration_id != avatar.configuration.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solution does not belong to this avatar",
            )

        db.delete(solution)
        db.commit()
