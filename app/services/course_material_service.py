import os
import uuid
from typing import List, Optional
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_
from fastapi import BackgroundTasks, HTTPException, UploadFile
from app.database.models import CourseMaterial, Course, SessionMaterial, MaterialType
from app.schemas.schemas import (
    CourseMaterialCreate, CourseMaterialUpdate, CourseMaterialResponse,
    SessionMaterialCreate, SessionMaterialUpdate, SessionMaterialResponse,
    FileUploadResponse
)
from app.config import settings
from app.services.file_processor import FileProcessor
from app.services.cloud_storage_service import cloud_storage
from app.services.rag_service import ingest_course_material_background


class CourseMaterialService:
    def __init__(self):
        self.file_processor = FileProcessor()
        self.materials_dir = Path(settings.upload_dir) / "course_materials"

    def _ensure_materials_dir(self) -> None:
        self.materials_dir.mkdir(parents=True, exist_ok=True)

    async def create_course_material(
        self, 
        db: Session, 
        material_data: CourseMaterialCreate, 
        user_id: str
    ) -> CourseMaterialResponse:
        """Create a new course material"""
        
        # Verify course ownership (course_id is string-based identifier)
        course = db.query(Course).filter(
            and_(Course.course_id == material_data.course_id, Course.user_id == user_id)
        ).first()
        
        if not course:
            raise HTTPException(status_code=404, detail="Course not found or access denied")
        
        # Create material record (use the UUID primary key for foreign key)
        db_material = CourseMaterial(
            course_id=course.id,
            title=material_data.title,
            description=material_data.description,
            material_type=material_data.material_type,
            url=material_data.url,
            author=material_data.author,
            publication_year=material_data.publication_year,
            publisher=material_data.publisher,
            isbn=material_data.isbn,
            doi=material_data.doi,
            additional_info=material_data.additional_info,
            is_required=material_data.is_required,
            is_active=material_data.is_active
        )
        
        db.add(db_material)
        db.commit()
        db.refresh(db_material)
        
        # Create response with string-based course_id
        return CourseMaterialResponse(
            id=db_material.id,
            course_id=course.course_id,  # Use string-based course_id
            title=db_material.title,
            description=db_material.description,
            material_type=db_material.material_type,
            file_path=db_material.file_path,
            file_name=db_material.file_name,
            file_size=db_material.file_size,
            file_type=db_material.file_type,
            url=db_material.url,
            author=db_material.author,
            publication_year=db_material.publication_year,
            publisher=db_material.publisher,
            isbn=db_material.isbn,
            doi=db_material.doi,
            additional_info=db_material.additional_info,
            is_required=db_material.is_required,
            is_active=db_material.is_active,
            created_at=db_material.created_at,
            updated_at=db_material.updated_at
        )

    async def upload_material_file(
        self, 
        db: Session, 
        material_id: str, 
        file: UploadFile, 
        user_id: str,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> FileUploadResponse:
        """Upload a file for a course material"""
        
        # Get material and verify ownership
        material = db.query(CourseMaterial).join(Course).filter(
            and_(
                CourseMaterial.id == material_id,
                Course.user_id == user_id
            )
        ).first()
        
        if not material:
            raise HTTPException(status_code=404, detail="Material not found or access denied")
        
        try:
            # Read file content
            file_content = await file.read()
            
            # Validate file
            is_valid, error_message = self.file_processor.validate_file(file_content, file.filename)
            if not is_valid:
                return FileUploadResponse(success=False, message=error_message)
            
            # Generate unique filename for path reference
            file_ext = Path(file.filename).suffix.lower()
            unique_filename = f"{uuid.uuid4()}_{file.filename}"
            material_dir = self.materials_dir / str(material_id)
            file_path = material_dir / unique_filename
            
            if settings.use_cloud_storage:
                # Upload to cloud storage
                try:
                    s3_key, public_url = await cloud_storage.upload_file(
                        file_content=file_content,
                        file_path=str(file_path),
                        content_type=file.content_type,
                        metadata={
                            'material_id': str(material_id),
                            'course_id': str(material.course_id),
                            'original_filename': file.filename or 'unknown',
                            'file_type': 'course_material'
                        }
                    )
                    
                    # Update material record with cloud storage info
                    material.file_path = public_url
                    material.file_name = file.filename
                    material.file_size = len(file_content)
                    material.file_type = file.content_type
                    
                except Exception as e:
                    print(f"Failed to upload to cloud storage: {e}")
                    # Fallback to local storage
                    material_dir.mkdir(parents=True, exist_ok=True)
                    with open(file_path, 'wb') as f:
                        f.write(file_content)
                    
                    material.file_path = str(file_path)
                    material.file_name = file.filename
                    material.file_size = len(file_content)
                    material.file_type = file.content_type
            else:
                # Save to local storage
                material_dir.mkdir(parents=True, exist_ok=True)
                with open(file_path, 'wb') as f:
                    f.write(file_content)
                
                material.file_path = str(file_path)
                material.file_name = file.filename
                material.file_size = len(file_content)
                material.file_type = file.content_type
            
            db.commit()
            db.refresh(material)

            if background_tasks is not None:
                background_tasks.add_task(
                    ingest_course_material_background,
                    material.course_id,
                    material.id,
                    file_content,
                    file.filename or "uploaded_material",
                )
            
            return FileUploadResponse(
                success=True,
                file_path=material.file_path,
                file_name=file.filename,
                file_size=len(file_content),
                file_type=file.content_type,
                message="File uploaded successfully"
            )
            
        except Exception as e:
            return FileUploadResponse(success=False, message=f"Upload failed: {str(e)}")

    async def get_course_materials(
        self, 
        db: Session, 
        course_id: str, 
        user_id: str,
        include_inactive: bool = False
    ) -> List[CourseMaterialResponse]:
        """Get all materials for a course"""
        
        # Verify course access (course_id is string-based identifier)
        course = db.query(Course).filter(
            and_(Course.course_id == course_id, Course.user_id == user_id)
        ).first()
        
        if not course:
            raise HTTPException(status_code=404, detail="Course not found or access denied")
        
        # Build query (use the UUID primary key for foreign key lookup)
        query = db.query(CourseMaterial).filter(CourseMaterial.course_id == course.id)
        
        if not include_inactive:
            query = query.filter(CourseMaterial.is_active == True)
        
        materials = query.all()
        
        # Create responses with string-based course_id
        responses = []
        for material in materials:
            response = CourseMaterialResponse(
                id=material.id,
                course_id=course.course_id,  # Use string-based course_id
                title=material.title,
                description=material.description,
                material_type=material.material_type,
                file_path=material.file_path,
                file_name=material.file_name,
                file_size=material.file_size,
                file_type=material.file_type,
                url=material.url,
                author=material.author,
                publication_year=material.publication_year,
                publisher=material.publisher,
                isbn=material.isbn,
                doi=material.doi,
                additional_info=material.additional_info,
                is_required=material.is_required,
                is_active=material.is_active,
                created_at=material.created_at,
                updated_at=material.updated_at
            )
            responses.append(response)
        
        return responses

    async def get_course_material(
        self, 
        db: Session, 
        material_id: str, 
        user_id: str
    ) -> CourseMaterialResponse:
        """Get a specific course material"""
        
        result = db.query(CourseMaterial, Course).join(Course).filter(
            and_(
                CourseMaterial.id == material_id,
                Course.user_id == user_id
            )
        ).first()
        
        if not result:
            raise HTTPException(status_code=404, detail="Material not found or access denied")
        
        material, course = result
        return CourseMaterialResponse(
            id=material.id,
            course_id=course.course_id,  # Use string-based course_id
            title=material.title,
            description=material.description,
            material_type=material.material_type,
            file_path=material.file_path,
            file_name=material.file_name,
            file_size=material.file_size,
            file_type=material.file_type,
            url=material.url,
            author=material.author,
            publication_year=material.publication_year,
            publisher=material.publisher,
            isbn=material.isbn,
            doi=material.doi,
            additional_info=material.additional_info,
            is_required=material.is_required,
            is_active=material.is_active,
            created_at=material.created_at,
            updated_at=material.updated_at
        )

    async def update_course_material(
        self, 
        db: Session, 
        material_id: str, 
        material_data: CourseMaterialUpdate, 
        user_id: str
    ) -> CourseMaterialResponse:
        """Update a course material"""
        
        result = db.query(CourseMaterial, Course).join(Course).filter(
            and_(
                CourseMaterial.id == material_id,
                Course.user_id == user_id
            )
        ).first()
        
        if not result:
            raise HTTPException(status_code=404, detail="Material not found or access denied")
        
        material, course = result
        
        # Update fields
        update_data = material_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(material, field, value)
        
        db.commit()
        db.refresh(material)
        
        return CourseMaterialResponse(
            id=material.id,
            course_id=course.course_id,  # Use string-based course_id
            title=material.title,
            description=material.description,
            material_type=material.material_type,
            file_path=material.file_path,
            file_name=material.file_name,
            file_size=material.file_size,
            file_type=material.file_type,
            url=material.url,
            author=material.author,
            publication_year=material.publication_year,
            publisher=material.publisher,
            isbn=material.isbn,
            doi=material.doi,
            additional_info=material.additional_info,
            is_required=material.is_required,
            is_active=material.is_active,
            created_at=material.created_at,
            updated_at=material.updated_at
        )

    async def delete_course_material(
        self, 
        db: Session, 
        material_id: str, 
        user_id: str
    ) -> dict:
        """Delete a course material"""
        
        material = db.query(CourseMaterial).join(Course).filter(
            and_(
                CourseMaterial.id == material_id,
                Course.user_id == user_id
            )
        ).first()
        
        if not material:
            raise HTTPException(status_code=404, detail="Material not found or access denied")
        
        # Delete associated file if exists
        if material.file_path:
            try:
                if settings.use_cloud_storage and material.file_path.startswith('https://'):
                    # Delete from cloud storage
                    # Extract S3 key from URL
                    url_parts = material.file_path.split('/')
                    if len(url_parts) > 3:
                        s3_key = '/'.join(url_parts[3:])  # Everything after domain
                        await cloud_storage.delete_file(s3_key)
                elif os.path.exists(material.file_path):
                    # Delete from local storage
                    os.remove(material.file_path)
                    # Try to remove directory if empty
                    material_dir = Path(material.file_path).parent
                    if material_dir.exists() and not any(material_dir.iterdir()):
                        material_dir.rmdir()
            except Exception as e:
                print(f"Warning: Could not delete file {material.file_path}: {e}")
        
        from app.database.models import KnowledgeChunk

        db.query(KnowledgeChunk).filter(
            KnowledgeChunk.course_id == material.course_id,
            KnowledgeChunk.source == f"course_material:{str(material.id)}",
        ).delete()

        db.delete(material)
        db.commit()
        
        return {"message": "Material deleted successfully"}

    # Session Materials methods
    async def create_session_material(
        self, 
        db: Session, 
        session_material_data: SessionMaterialCreate, 
        user_id: str
    ) -> SessionMaterialResponse:
        """Link a course material to a session"""
        
        # Verify session and material ownership through course
        from app.database.models import Session as SessionModel
        session = db.query(SessionModel).join(Course).filter(
            and_(
                SessionModel.session_id == session_material_data.session_id,
                Course.user_id == user_id
            )
        ).first()
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found or access denied")
        
        material = db.query(CourseMaterial).join(Course).filter(
            and_(
                CourseMaterial.id == session_material_data.course_material_id,
                Course.user_id == user_id
            )
        ).first()
        
        if not material:
            raise HTTPException(status_code=404, detail="Material not found or access denied")
        
        # Check if association already exists
        existing = db.query(SessionMaterial).filter(
            and_(
                SessionMaterial.session_id == session.id,
                SessionMaterial.course_material_id == session_material_data.course_material_id
            )
        ).first()
        
        if existing:
            raise HTTPException(status_code=400, detail="Material already linked to this session")
        
        # Create session material
        db_session_material = SessionMaterial(
            session_id=session.id,
            course_material_id=session_material_data.course_material_id,
            is_included=session_material_data.is_included,
            usage_instructions=session_material_data.usage_instructions
        )
        
        db.add(db_session_material)
        db.commit()
        db.refresh(db_session_material)
        
        # Create response with string-based session_id
        return SessionMaterialResponse(
            id=db_session_material.id,
            session_id=session.session_id,  # Use string-based session_id
            course_material_id=db_session_material.course_material_id,
            is_included=db_session_material.is_included,
            usage_instructions=db_session_material.usage_instructions,
            created_at=db_session_material.created_at,
            updated_at=db_session_material.updated_at,
            course_material=CourseMaterialResponse(
                id=material.id,
                course_id=material.course.course_id,  # Use string-based course_id
                title=material.title,
                description=material.description,
                material_type=material.material_type,
                file_path=material.file_path,
                file_name=material.file_name,
                file_size=material.file_size,
                file_type=material.file_type,
                url=material.url,
                author=material.author,
                publication_year=material.publication_year,
                publisher=material.publisher,
                isbn=material.isbn,
                doi=material.doi,
                additional_info=material.additional_info,
                is_required=material.is_required,
                is_active=material.is_active,
                created_at=material.created_at,
                updated_at=material.updated_at
            )
        )

    async def get_session_materials(
        self,
        db: Session,
        session_id: str,
        user_id: str,
        skip_ownership_check: bool = False,
    ) -> List[SessionMaterialResponse]:
        """Get all materials for a session.

        Admins pass skip_ownership_check=True to bypass the course-owner filter.
        """
        from app.database.models import Session as SessionModel

        if skip_ownership_check:
            session = db.query(SessionModel).filter(
                SessionModel.session_id == session_id
            ).first()
        else:
            session = db.query(SessionModel).join(Course).filter(
                and_(
                    SessionModel.session_id == session_id,
                    Course.user_id == user_id,
                )
            ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found or access denied")
        
        session_materials = db.query(SessionMaterial).filter(
            SessionMaterial.session_id == session.id  # Use UUID primary key
        ).all()
        
        # Build responses with proper session_id format
        responses = []
        for sm in session_materials:
            response = SessionMaterialResponse(
                id=sm.id,
                session_id=session.session_id,  # Use string-based session_id
                course_material_id=sm.course_material_id,
                is_included=sm.is_included,
                usage_instructions=sm.usage_instructions,
                created_at=sm.created_at,
                updated_at=sm.updated_at,
                course_material=CourseMaterialResponse(
                    id=sm.course_material.id,
                    course_id=sm.course_material.course.course_id,  # Use string-based course_id
                    title=sm.course_material.title,
                    description=sm.course_material.description,
                    material_type=sm.course_material.material_type,
                    file_path=sm.course_material.file_path,
                    file_name=sm.course_material.file_name,
                    file_size=sm.course_material.file_size,
                    file_type=sm.course_material.file_type,
                    url=sm.course_material.url,
                    author=sm.course_material.author,
                    publication_year=sm.course_material.publication_year,
                    publisher=sm.course_material.publisher,
                    isbn=sm.course_material.isbn,
                    doi=sm.course_material.doi,
                    additional_info=sm.course_material.additional_info,
                    is_required=sm.course_material.is_required,
                    is_active=sm.course_material.is_active,
                    created_at=sm.course_material.created_at,
                    updated_at=sm.course_material.updated_at
                )
            )
            responses.append(response)
        
        return responses

    async def update_session_material(
        self, 
        db: Session, 
        session_material_id: str, 
        session_material_data: SessionMaterialUpdate, 
        user_id: str
    ) -> SessionMaterialResponse:
        """Update a session material"""
        
        session_material = db.query(SessionMaterial).join(
            CourseMaterial
        ).join(Course).filter(
            and_(
                SessionMaterial.id == session_material_id,
                Course.user_id == user_id
            )
        ).first()
        
        if not session_material:
            raise HTTPException(status_code=404, detail="Session material not found or access denied")
        
        # Update fields
        update_data = session_material_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(session_material, field, value)
        
        db.commit()
        db.refresh(session_material)
        
        # Create response with proper string-based IDs
        return SessionMaterialResponse(
            id=session_material.id,
            session_id=session_material.session.session_id,  # Use string-based session_id
            course_material_id=session_material.course_material_id,
            is_included=session_material.is_included,
            usage_instructions=session_material.usage_instructions,
            created_at=session_material.created_at,
            updated_at=session_material.updated_at,
            course_material=CourseMaterialResponse(
                id=session_material.course_material.id,
                course_id=session_material.course_material.course.course_id,  # Use string-based course_id
                title=session_material.course_material.title,
                description=session_material.course_material.description,
                material_type=session_material.course_material.material_type,
                file_path=session_material.course_material.file_path,
                file_name=session_material.course_material.file_name,
                file_size=session_material.course_material.file_size,
                file_type=session_material.course_material.file_type,
                url=session_material.course_material.url,
                author=session_material.course_material.author,
                publication_year=session_material.course_material.publication_year,
                publisher=session_material.course_material.publisher,
                isbn=session_material.course_material.isbn,
                doi=session_material.course_material.doi,
                additional_info=session_material.course_material.additional_info,
                is_required=session_material.course_material.is_required,
                is_active=session_material.course_material.is_active,
                created_at=session_material.course_material.created_at,
                updated_at=session_material.course_material.updated_at
            )
        )

    async def delete_session_material(
        self, 
        db: Session, 
        session_material_id: str, 
        user_id: str
    ) -> dict:
        """Remove a material from a session"""
        
        session_material = db.query(SessionMaterial).join(
            CourseMaterial
        ).join(Course).filter(
            and_(
                SessionMaterial.id == session_material_id,
                Course.user_id == user_id
            )
        ).first()
        
        if not session_material:
            raise HTTPException(status_code=404, detail="Session material not found or access denied")
        
        db.delete(session_material)
        db.commit()
        
        return {"message": "Material removed from session successfully"}
