import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.database.models import User
from app.schemas.schemas import (
    CourseMaterialCreate,
    CourseMaterialUpdate,
    CourseMaterialResponse,
    CourseMaterialsListResponse,
    SessionMaterialCreate,
    SessionMaterialUpdate,
    SessionMaterialResponse,
    SessionMaterialsListResponse,
    FileUploadResponse,
    MaterialType,
)
from app.services.course_material_service import CourseMaterialService
from app.dependencies.auth import get_current_user

router = APIRouter(prefix="/api/course-materials", tags=["course-materials"])

course_material_service = CourseMaterialService()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Course Materials Endpoints


@router.get("/courses/{course_id}", response_model=CourseMaterialsListResponse)
async def get_course_materials(
    course_id: str,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all materials for a course"""
    try:
        materials = await course_material_service.get_course_materials(
            db, course_id, current_user.id, include_inactive
        )
        return CourseMaterialsListResponse(materials=materials, total=len(materials))
    except Exception as e:
        logger.error(f"❌ Error getting course materials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting course materials: {e}",
        )


@router.post("/courses/{course_id}", response_model=CourseMaterialResponse)
async def create_course_material(
    course_id: str,
    material_data: CourseMaterialCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new course material"""
    try:
        # Set the course_id from the URL
        material_data.course_id = course_id
        material = await course_material_service.create_course_material(
            db, material_data, current_user.id
        )
        return material
    except Exception as e:
        logger.error(f"❌ Error creating course material: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating course material: {e}",
        )


@router.get("/{material_id}", response_model=CourseMaterialResponse)
async def get_course_material(
    material_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific course material"""
    try:
        material = await course_material_service.get_course_material(
            db, material_id, current_user.id
        )
        return material
    except Exception as e:
        logger.error(f"❌ Error getting course material: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting course material: {e}",
        )


@router.put("/{material_id}", response_model=CourseMaterialResponse)
async def update_course_material(
    material_id: str,
    material_data: CourseMaterialUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a course material"""
    try:
        material = await course_material_service.update_course_material(
            db, material_id, material_data, current_user.id
        )
        return material
    except Exception as e:
        logger.error(f"❌ Error updating course material: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating course material: {e}",
        )


@router.delete("/{material_id}")
async def delete_course_material(
    material_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a course material"""
    try:
        result = await course_material_service.delete_course_material(
            db, material_id, current_user.id
        )
        return result
    except Exception as e:
        logger.error(f"❌ Error deleting course material: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting course material: {e}",
        )


@router.post("/{material_id}/upload", response_model=FileUploadResponse)
async def upload_material_file(
    material_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a file for a course material"""
    try:
        result = await course_material_service.upload_material_file(
            db, material_id, file, current_user.id
        )
        return result
    except Exception as e:
        logger.error(f"❌ Error uploading material file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading material file: {e}",
        )


# Quick create endpoint for materials with file upload
@router.post("/courses/{course_id}/upload", response_model=CourseMaterialResponse)
async def create_material_with_file(
    course_id: str,
    title: str = Form(...),
    material_type: MaterialType = Form(...),
    description: str = Form(None),
    author: str = Form(None),
    publication_year: int = Form(None),
    publisher: str = Form(None),
    isbn: str = Form(None),
    doi: str = Form(None),
    is_required: bool = Form(True),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a course material and upload file in one step"""
    try:
        # Create material first
        material_data = CourseMaterialCreate(
            course_id=course_id,
            title=title,
            description=description,
            material_type=material_type,
            author=author,
            publication_year=publication_year,
            publisher=publisher,
            isbn=isbn,
            doi=doi,
            is_required=is_required,
        )

        material = await course_material_service.create_course_material(
            db, material_data, current_user.id
        )

        # Upload file
        await course_material_service.upload_material_file(
            db, str(material.id), file, current_user.id
        )

        # Return updated material with file info
        updated_material = await course_material_service.get_course_material(
            db, str(material.id), current_user.id
        )

        return updated_material
    except Exception as e:
        logger.error(f"❌ Error creating material with file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating material with file: {e}",
        )


# Session Materials Endpoints


@router.get("/sessions/{session_id}", response_model=SessionMaterialsListResponse)
async def get_session_materials(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all materials for a session"""
    try:
        session_materials = await course_material_service.get_session_materials(
            db, session_id, current_user.id
        )
        return SessionMaterialsListResponse(
            session_materials=session_materials, total=len(session_materials)
        )
    except Exception as e:
        logger.error(f"❌ Error getting session materials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting session materials: {e}",
        )


@router.post("/sessions/{session_id}", response_model=SessionMaterialResponse)
async def create_session_material(
    session_id: str,
    session_material_data: SessionMaterialCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Link a course material to a session"""
    try:
        # Set session_id from URL
        session_material_data.session_id = session_id
        session_material = await course_material_service.create_session_material(
            db, session_material_data, current_user.id
        )
        return session_material
    except Exception as e:
        logger.error(f"❌ Error creating session material: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating session material: {e}",
        )


@router.put(
    "/session-links/{session_material_id}", response_model=SessionMaterialResponse
)
async def update_session_material(
    session_material_id: str,
    session_material_data: SessionMaterialUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a session material"""
    try:
        session_material = await course_material_service.update_session_material(
            db, session_material_id, session_material_data, current_user.id
        )
        return session_material
    except Exception as e:
        logger.error(f"❌ Error updating session material: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating session material: {e}",
        )


@router.delete("/session-links/{session_material_id}")
async def delete_session_material(
    session_material_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a material from a session"""
    try:
        result = await course_material_service.delete_session_material(
            db, session_material_id, current_user.id
        )
        return result
    except Exception as e:
        logger.error(f"❌ Error deleting session material: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting session material: {e}",
        )
