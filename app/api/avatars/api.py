"""
Avatar routes.

Ownership rules enforced here:
  Publisher : create / edit / publish / delete their own avatars and content.
  Subscriber: browse published avatars; launch (create session) handled by
              existing session router — avatar_id is passed as part of sessionDetails.
  Admin     : read-only view of all avatars and configurations.

Prompt fields NEVER appear in any response from this router.
All AI prompts live in AvatarTemplate and are resolved at session-run time.
"""
import logging
import uuid
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Avatar, User, PublisherAvatarProfile
from app.dependencies.auth import require_admin, require_publisher, require_subscriber
from app.schemas.schemas import (
    AvatarConfigurationCreate,
    AvatarConfigurationResponse,
    AvatarConfigurationUpdate,
    AvatarCreate,
    AvatarListResponse,
    AvatarPricingUpdate,
    AvatarPublicListResponse,
    AvatarPublicResponse,
    AvatarResponse,
    AvatarSummary,
    AvatarUpdate,
    KnowledgeDocumentResponse,
    ProfileRefineRequest,
    PublisherAvatarProfileResponse,
    ReferenceSolutionResponse,
    RubricCreate,
    RubricResponse,
)
from app.services.avatar_service import AvatarService
from app.services.file_processor import FileProcessor
from app.services.openai_service import OpenAIService
from app.services.prompt_generator import generate_teaching_persona_prompt
from app.services.rag_service import ingest_avatar_knowledge_document_background

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["avatars"])

avatar_service = AvatarService()
file_processor = FileProcessor()
openai_service = OpenAIService()


# ══════════════════════════════════════════════════════════════════
# Publisher — Avatar CRUD
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/publisher/avatars",
    response_model=AvatarResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_avatar(
    data: AvatarCreate,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Owns resource: the calling publisher (publisher_id = current_user.id).
    Validation: template_id must reference an active template; name required.
    """
    try:
        return await avatar_service.create_avatar(db, current_user.id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ create_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating avatar: {e}")


@router.get(
    "/publisher/avatars",
    response_model=AvatarListResponse,
)
async def list_publisher_avatars(
    program_id: Optional[UUID] = Query(None, description="Filter avatars to those associated with this program."),
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Returns: only avatars owned by the calling publisher.
    If program_id is provided, returns only avatars linked to that program.
    """
    try:
        avatars, total = await avatar_service.list_publisher_avatars(db, current_user.id, program_id=program_id)
        return AvatarListResponse(
            avatars=[AvatarSummary.model_validate(a) for a in avatars],
            total=total,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ list_publisher_avatars error: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing avatars: {e}")


@router.get(
    "/publisher/avatars/{avatar_id}",
    response_model=AvatarResponse,
)
async def get_publisher_avatar(
    avatar_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Returns: avatar with full configuration (no prompts).
    """
    try:
        avatar = await avatar_service.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=404, detail="Avatar not found")
        if current_user.role != "admin" and str(avatar.publisher_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="You do not own this avatar")
        return avatar
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ get_publisher_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching avatar: {e}")


@router.put(
    "/publisher/avatars/{avatar_id}",
    response_model=AvatarResponse,
)
async def update_avatar(
    avatar_id: UUID,
    data: AvatarUpdate,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Validation: name and description only — no prompt fields allowed.
    """
    try:
        return await avatar_service.update_avatar(db, avatar_id, current_user.id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ update_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating avatar: {e}")


@router.patch(
    "/publisher/avatars/{avatar_id}/publish",
    response_model=AvatarResponse,
)
async def publish_avatar(
    avatar_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Validation: avatar must have an AvatarConfiguration before publish is allowed.
    """
    try:
        return await avatar_service.publish_avatar(db, avatar_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ publish_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error publishing avatar: {e}")


@router.delete(
    "/publisher/avatars/{avatar_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_avatar(
    avatar_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Action: hard delete — cascades to AvatarConfiguration, Rubric,
            KnowledgeDocument, ReferenceSolution.
    """
    try:
        await avatar_service.delete_avatar(db, avatar_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ delete_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting avatar: {e}")


# ══════════════════════════════════════════════════════════════════
# Publisher — AvatarConfiguration
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/publisher/avatars/{avatar_id}/configuration",
    response_model=AvatarConfigurationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_configuration(
    avatar_id: UUID,
    data: AvatarConfigurationCreate,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Validation: avatar must not already have a configuration (use PUT to update).
    No prompt fields — configuration holds only behavioral settings.
    """
    try:
        return await avatar_service.create_configuration(db, avatar_id, current_user.id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ create_configuration error: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating configuration: {e}")


@router.get(
    "/publisher/avatars/{avatar_id}/configuration",
    response_model=AvatarConfigurationResponse,
)
async def get_configuration(
    avatar_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    """
    try:
        return await avatar_service.get_configuration(db, avatar_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ get_configuration error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching configuration: {e}")


@router.put(
    "/publisher/avatars/{avatar_id}/configuration",
    response_model=AvatarConfigurationResponse,
)
async def update_configuration(
    avatar_id: UUID,
    data: AvatarConfigurationUpdate,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Validation: configuration must already exist (use POST to create).
    """
    try:
        return await avatar_service.update_configuration(db, avatar_id, current_user.id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ update_configuration error: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating configuration: {e}")


# ══════════════════════════════════════════════════════════════════
# Publisher — Rubrics
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/publisher/avatars/{avatar_id}/configuration/rubrics",
    response_model=RubricResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_rubric(
    avatar_id: UUID,
    data: RubricCreate,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Validation: AvatarConfiguration must exist first; content is a JSON dict.
    """
    try:
        return await avatar_service.add_rubric(db, avatar_id, current_user.id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ add_rubric error: {e}")
        raise HTTPException(status_code=500, detail=f"Error adding rubric: {e}")


@router.delete(
    "/publisher/avatars/{avatar_id}/configuration/rubrics/{rubric_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_rubric(
    avatar_id: UUID,
    rubric_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar; rubric must belong to this avatar.
    """
    try:
        await avatar_service.delete_rubric(db, avatar_id, rubric_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ delete_rubric error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting rubric: {e}")


# ══════════════════════════════════════════════════════════════════
# Publisher — Knowledge Documents
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/publisher/avatars/{avatar_id}/configuration/knowledge-documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_knowledge_document(
    background_tasks: BackgroundTasks,
    avatar_id: UUID,
    title: str = Form(...),
    content_text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Accepts: multipart form with title + optional file upload or content_text.
    Validation: AvatarConfiguration must exist first.
    """
    try:
        file_path = file_name = file_type = None
        file_size = None
        file_content_bytes: Optional[bytes] = None

        if file and file.filename:
            file_content_bytes = await file.read()
            file_path = await file_processor.save_uploaded_file(
                file_content_bytes, file.filename, f"avatar_{avatar_id}"
            )
            file_name = file.filename
            file_size = len(file_content_bytes)
            file_type = file.content_type

        doc = await avatar_service.add_knowledge_document(
            db, avatar_id, current_user.id,
            title=title,
            content_text=content_text,
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
        )

        # Trigger background RAG ingestion if a file was uploaded.
        if file_content_bytes and file_name:
            background_tasks.add_task(
                ingest_avatar_knowledge_document_background,
                doc.id,
                doc.avatar_configuration_id,
                file_content_bytes,
                file_name,
            )

        return doc
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ add_knowledge_document error: {e}")
        raise HTTPException(status_code=500, detail=f"Error adding knowledge document: {e}")


@router.delete(
    "/publisher/avatars/{avatar_id}/configuration/knowledge-documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_knowledge_document(
    avatar_id: UUID,
    doc_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar; document must belong to this avatar.
    """
    try:
        await avatar_service.delete_knowledge_document(db, avatar_id, doc_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ delete_knowledge_document error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting knowledge document: {e}")


# ══════════════════════════════════════════════════════════════════
# Publisher — Reference Solutions
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/publisher/avatars/{avatar_id}/configuration/reference-solutions",
    response_model=ReferenceSolutionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_reference_solution(
    avatar_id: UUID,
    title: str = Form(...),
    content_text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar.
    Accepts: multipart form with title + optional file upload or content_text.
    Validation: AvatarConfiguration must exist first.
    """
    try:
        file_path = file_name = file_type = None
        file_size = None

        if file and file.filename:
            file_content = await file.read()
            file_path = await file_processor.save_uploaded_file(
                file_content, file.filename, f"avatar_{avatar_id}"
            )
            file_name = file.filename
            file_size = len(file_content)
            file_type = file.content_type

        return await avatar_service.add_reference_solution(
            db, avatar_id, current_user.id,
            title=title,
            content_text=content_text,
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ add_reference_solution error: {e}")
        raise HTTPException(status_code=500, detail=f"Error adding reference solution: {e}")


@router.delete(
    "/publisher/avatars/{avatar_id}/configuration/reference-solutions/{solution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_reference_solution(
    avatar_id: UUID,
    solution_id: UUID,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher or Admin.
    Authorization: publisher must own the avatar; solution must belong to this avatar.
    """
    try:
        await avatar_service.delete_reference_solution(db, avatar_id, solution_id, current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ delete_reference_solution error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting reference solution: {e}")


# ══════════════════════════════════════════════════════════════════
# Publisher — Persona Refinement
# ══════════════════════════════════════════════════════════════════

@router.post(
    "/publisher/avatars/{avatar_id}/profile/refine",
    response_model=PublisherAvatarProfileResponse,
)
async def refine_avatar_persona(
    avatar_id: UUID,
    data: ProfileRefineRequest,
    current_user: User = Depends(require_publisher),
    db: Session = Depends(get_db),
):
    """
    Who can call: Publisher (or Admin).
    What it does:
      1. Validates the publisher owns this avatar.
      2. Builds a draft teaching-persona prompt from teaching_preferences.
      3. Calls gpt-4o-mini to refine the draft into a concise, instructional persona.
      4. Upserts PublisherAvatarProfile with the refined prompt and preferences.
      5. Returns the updated profile.
    """
    try:
        # ── Ownership check ────────────────────────────────────────────────────
        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
        if current_user.role != "admin" and str(avatar.publisher_id) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this avatar",
            )

        prefs = data.teaching_preferences

        # ── Validate enum values ───────────────────────────────────────────────
        from app.schemas.schemas import (
            VALID_TEACHING_PACE, VALID_QUESTIONING_STYLE, VALID_FORMALITY_LEVEL,
            VALID_DEPTH_LEVEL, VALID_ENCOURAGEMENT_LEVEL, VALID_LANGUAGE_LEVEL,
        )
        validation_errors = []
        if prefs.teaching_pace and prefs.teaching_pace not in VALID_TEACHING_PACE:
            validation_errors.append(f"teaching_pace must be one of {sorted(VALID_TEACHING_PACE)}")
        if prefs.questioning_style and prefs.questioning_style not in VALID_QUESTIONING_STYLE:
            validation_errors.append(f"questioning_style must be one of {sorted(VALID_QUESTIONING_STYLE)}")
        if prefs.formality_level and prefs.formality_level not in VALID_FORMALITY_LEVEL:
            validation_errors.append(f"formality_level must be one of {sorted(VALID_FORMALITY_LEVEL)}")
        if prefs.depth_level and prefs.depth_level not in VALID_DEPTH_LEVEL:
            validation_errors.append(f"depth_level must be one of {sorted(VALID_DEPTH_LEVEL)}")
        if prefs.encouragement_level and prefs.encouragement_level not in VALID_ENCOURAGEMENT_LEVEL:
            validation_errors.append(f"encouragement_level must be one of {sorted(VALID_ENCOURAGEMENT_LEVEL)}")
        if prefs.language_level and prefs.language_level not in VALID_LANGUAGE_LEVEL:
            validation_errors.append(f"language_level must be one of {sorted(VALID_LANGUAGE_LEVEL)}")
        if validation_errors:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=validation_errors)

        # ── Build draft prompt from preferences ────────────────────────────────
        draft = generate_teaching_persona_prompt(
            avatar_name=avatar.name,
            avatar_description=avatar.description,
            teaching_pace=prefs.teaching_pace,
            questioning_style=prefs.questioning_style,
            formality_level=prefs.formality_level,
            depth_level=prefs.depth_level,
            encouragement_level=prefs.encouragement_level,
            language_level=prefs.language_level,
        )

        # ── Refine with gpt-4o-mini ────────────────────────────────────────────
        refined_prompt = await openai_service.refine_persona_prompt(draft, data.additional_context)

        # ── Upsert PublisherAvatarProfile ──────────────────────────────────────
        profile = (
            db.query(PublisherAvatarProfile)
            .filter(PublisherAvatarProfile.publisher_avatar_id == avatar_id)
            .first()
        )
        if profile:
            profile.teaching_pace = prefs.teaching_pace
            profile.questioning_style = prefs.questioning_style
            profile.formality_level = prefs.formality_level
            profile.depth_level = prefs.depth_level
            profile.encouragement_level = prefs.encouragement_level
            profile.language_level = prefs.language_level
            profile.refined_prompt = refined_prompt
            profile.updated_at = datetime.utcnow()
        else:
            profile = PublisherAvatarProfile(
                id=uuid.uuid4(),
                publisher_avatar_id=avatar.id,
                teaching_pace=prefs.teaching_pace,
                questioning_style=prefs.questioning_style,
                formality_level=prefs.formality_level,
                depth_level=prefs.depth_level,
                encouragement_level=prefs.encouragement_level,
                language_level=prefs.language_level,
                refined_prompt=refined_prompt,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(profile)

        db.commit()
        db.refresh(profile)
        return PublisherAvatarProfileResponse.model_validate(profile)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ refine_avatar_persona error: {e}")
        raise HTTPException(status_code=500, detail=f"Error refining persona: {e}")


# ══════════════════════════════════════════════════════════════════
# Subscriber — Browse published avatars
# ══════════════════════════════════════════════════════════════════

@router.get(
    "/avatars",
    response_model=AvatarPublicListResponse,
)
async def browse_published_avatars(
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """
    Who can call: Any authenticated user (subscriber, publisher, admin).
    Returns: published avatars only; no configuration or template metadata.
    Use the returned avatar id as avatar_id when creating a session.
    """
    try:
        avatars, total = await avatar_service.list_published_avatars(db)
        return AvatarPublicListResponse(
            avatars=[AvatarPublicResponse.model_validate(a) for a in avatars],
            total=total,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ browse_published_avatars error: {e}")
        raise HTTPException(status_code=500, detail=f"Error browsing avatars: {e}")


@router.get(
    "/avatars/{avatar_id}",
    response_model=AvatarPublicResponse,
)
async def get_published_avatar(
    avatar_id: UUID,
    current_user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """
    Who can call: Any authenticated user.
    Returns: single published avatar without configuration details.
    """
    try:
        avatar = await avatar_service.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=404, detail="Avatar not found")
        if not avatar.is_published:
            raise HTTPException(status_code=404, detail="Avatar not found")
        return avatar
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ get_published_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching avatar: {e}")


# ══════════════════════════════════════════════════════════════════
# Admin — Full visibility across all avatars
# ══════════════════════════════════════════════════════════════════

@router.get(
    "/admin/avatars",
    response_model=AvatarListResponse,
)
async def admin_list_all_avatars(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Who can call: Admin only.
    Returns: all avatars regardless of owner or publish state.
    """
    try:
        avatars, total = await avatar_service.list_all_avatars(db)
        return AvatarListResponse(
            avatars=[AvatarSummary.model_validate(a) for a in avatars],
            total=total,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ admin_list_all_avatars error: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing avatars: {e}")


@router.get(
    "/admin/avatars/{avatar_id}",
    response_model=AvatarResponse,
)
async def admin_get_avatar(
    avatar_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Who can call: Admin only.
    Returns: full avatar with configuration and all content assets.
    """
    try:
        avatar = await avatar_service.get_avatar(db, avatar_id)
        if not avatar:
            raise HTTPException(status_code=404, detail="Avatar not found")
        return avatar
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ admin_get_avatar error: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching avatar: {e}")


@router.patch(
    "/admin/avatars/{avatar_id}/pricing",
    response_model=AvatarResponse,
)
async def admin_set_avatar_pricing(
    avatar_id: UUID,
    data: AvatarPricingUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Override the subscription cost on a specific avatar (admin only)."""
    try:
        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            raise HTTPException(status_code=404, detail="Avatar not found")
        avatar.subscription_cost = data.subscription_cost
        db.commit()
        return await avatar_service.get_avatar(db, avatar_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ admin_set_avatar_pricing error: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating pricing: {e}")
