import logging
from PIL import Image
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
import requests
from io import BytesIO
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Session, SessionRun, SessionRunStatus, User
from app.schemas.schemas import SessionDetails, SlideData, PresentationData, AssistantParameters, SessionRunDetails, EphemeralTokenResponse, SessionUpdateDetails, SessionsListResponse, SessionRunsListResponse, SessionCreateRequest
from app.services.file_processor import FileProcessor
from app.services.openai_service import OpenAIService
from app.services.session_service import SessionService
from app.dependencies.auth import get_current_user
from app.config import settings

# Set up logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/api", tags=["sessions"])

# Initialize services
file_processor = FileProcessor()
openai_service = OpenAIService()
session_service = SessionService()


@router.post("/sessions/create", response_model=SessionDetails)
async def create_session(
    presentation: UploadFile = File(...),
    sessionDetails: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new session
    """
    try:
        # Parse session details
        logger.info(f"📋 Parsing session details: {sessionDetails}")
        session_details_dict = json.loads(sessionDetails)
        
        # Validate that courseId is present
        if 'courseId' not in session_details_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="courseId is required in session details"
            )

        # Read file content
        logger.info(f"📂 Reading file content: {presentation.filename}")
        file_content = await presentation.read()
        logger.info(f"✅ File read successfully, size: {len(file_content)} bytes")
        
        # Validate file
        logger.info(f"🔍 Validating file: {presentation.filename}")
        is_valid, error_message = file_processor.validate_file(file_content, presentation.filename)
        if not is_valid:
            logger.error(f"❌ File validation failed: {error_message}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File validation failed: {error_message}"
            )

        # Generate session ID
        logger.info(f"🆔 Generating session ID")
        session_id = session_service.generate_session_id()
        logger.info(f"✅ Session ID generated: {session_id}")
        
        # Save uploaded file
        file_path = await file_processor.save_uploaded_file(file_content, presentation.filename, session_id)
        logger.info(f"✅ File saved to: {file_path}")

        presentation_details_dict = {
            "filename": presentation.filename,
            "filePath": file_path,
            "fileSize": len(file_content),
            "fileType": Path(presentation.filename).suffix.lower(),
        }

        # Convert presentation to images
        logger.info(f"⚙️ Converting presentation to images")
        slide_images, images_paths = await file_processor.convert_presentation_to_images(
            file_path, session_id
        )
        logger.info(f"✅ Presentation converted to images, {len(slide_images)} slides extracted")

        # Vision-based slide processing
        logger.info(f"⚙️ Processing slides with Vision API")
        slides_details = await openai_service.process_slides_with_vision(slide_images, images_paths, session_id, session_details_dict.get('visionInstructions'), session_details_dict.get('visionModel'), user_id=current_user.id, db=db)
        logger.info(f"✅ Slides processed with Vision API")

        # Create session with slides
        logger.info(f"📚 Creating session with slides")
        session_id = await session_service.create_session(
            db,
            current_user.id,
            session_id,
            presentation_details_dict,
            session_details_dict,
            slides_details,
        )
        logger.info(f"✅ Session created with ID: {session_id}")

        # Format slides for response
        logger.info(f"📋 Formatting slides for response")
        response_slides = []
        for slide_details in slides_details:
            response_slides.append(SlideData(
                id=slide_details.get('slideNumber'),
                slideNumber=slide_details.get('slideNumber'),
                title=slide_details.get('title'),
                imagePath=slide_details.get('imagePath', ''),
                thumbnailPath=slide_details.get('thumbnailPath', ''),
                content=slide_details.get('content'),
                visionInstructions=slide_details.get('visionInstructions', ''),
                visionModel=slide_details.get('visionModel', ''),
            ))

        presentation_details = PresentationData(
            filename=presentation_details_dict.get('filename'),
            filePath=presentation_details_dict.get('filePath'),
            fileSize=presentation_details_dict.get('fileSize'),
            fileType=presentation_details_dict.get('fileType'),
        )
        
        # Get the created session from database to return complete information
        created_session = await session_service.get_session(db, session_id)
        if not created_session:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve created session"
            )
        
        logger.info(f"🎉 Returning successful response with {len(response_slides)} slides")
        return created_session
    except Exception as e:
        logger.error(f"❌ Error creating session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating session: {e}"
        )

@router.get("/sessions/{session_id}", response_model=SessionDetails)
async def get_session(
    session_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a session by ID
    """
    try:
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return session
    except Exception as e:
        logger.error(f"❌ Error getting session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting session: {e}"
        )


@router.post("/sessions/{session_id}/update", response_model=SessionDetails)
async def update_session(
    session_id: str,
    request_data: dict,
    db: Session = Depends(get_db)
):
    """
    Update a session by ID
    """
    try:
        if not request_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request data is required"
            )

        session_details = SessionUpdateDetails(**request_data)
        session = await session_service.update_session(db, session_id, session_details)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return session
    except ValueError as e:
        logger.error(f"❌ Invalid request data: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid request data: {str(e)}"
        )
    except Exception as e:
        logger.error(f"❌ Error updating session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating session: {e}"
        )

@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: Session = Depends(get_db)
):
    try:
        deleted = await session_service.delete_session(db, session_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return {"message": "Session deleted successfully"}
    except Exception as e:
        logger.error(f"❌ Error deleting session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting session: {e}"
        )

@router.post("/sessions/{session_id}/run/start", response_model=SessionRunDetails)
async def start_session_run(
    session_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Start a session run
    """
    try:
        print(f"Starting session run for session_id: {session_id}")
        assistant_parameters_dict = request_data.get("assistant_parameters")
        
        if not assistant_parameters_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required field: assistant_parameters"
            )
        
        assistant_parameters = AssistantParameters(**assistant_parameters_dict)
        
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        print(f"Session found")
        session_run = await session_service.start_session_run(db, session_id, str(current_user.id), assistant_parameters)
        if not session_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        print(f"Current user: {current_user.id}")
        print(f"Current user: {current_user.username}")
        return SessionRunDetails(
            sessionRunId=str(session_run.session_run_id),
            sessionId=str(session_id),
            userId=str(current_user.id),
            username=current_user.username,
            sessionRunMetadata=session_run.session_run_metadata,
            assistantParameters=AssistantParameters(**session_run.assistant_parameters),
            status=session_run.status,
            courseName=session.courseName,
            className=session.className,
            courseCode=session.courseCode,
            description=session.description,
            duration=session.duration,
            presentationDetails=session.presentationDetails,
            slidesDetails=session.slidesDetails,
            startTime=session_run.start_time,
            endTime=session_run.end_time
        )
    except Exception as e:
        logger.error(f"❌ Error starting session run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error starting session run: {e}"
        )

@router.post("/sessions/{session_id}/run/start/guest", response_model=SessionRunDetails)
async def start_session_run(
    session_id: str,
    request_data: dict,
    # current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Start a session run
    """
    try:
        guest_user_id = "8e3957ae-78b8-411f-85c9-a2640fa541f8"
        print(f"Starting session run for session_id: {session_id}")
        assistant_parameters_dict = request_data.get("assistant_parameters")
        
        if not assistant_parameters_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required field: assistant_parameters"
            )
        
        assistant_parameters = AssistantParameters(**assistant_parameters_dict)
        
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        print(f"Session found")
        session_run = await session_service.start_session_run(db, session_id, guest_user_id, assistant_parameters)
        if not session_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return SessionRunDetails(
            sessionRunId=str(session_run.session_run_id),
            sessionId=str(session_id),
            userId=guest_user_id,
            username="guest",
            sessionRunMetadata=session_run.session_run_metadata,
            assistantParameters=AssistantParameters(**session_run.assistant_parameters),
            status=session_run.status,
            courseName=session.courseName,
            className=session.className,
            courseCode=session.courseCode,
            description=session.description,
            duration=session.duration,
            presentationDetails=session.presentationDetails,
            slidesDetails=session.slidesDetails,
            startTime=session_run.start_time,
            endTime=session_run.end_time
        )
    except Exception as e:
        logger.error(f"❌ Error starting session run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error starting session run: {e}"
        )


@router.post("/sessions/{session_id}/run/{session_run_id}/stop", response_model=SessionRunDetails)
async def stop_session_run(
    session_id: str,
    session_run_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Stop a session run
    """
    try:
        session_run_metadata = request_data.get("session_run_metadata")
        
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        session_run = await session_service.stop_session_run(db, session_id, session_run_id, session_run_metadata)
        if not session_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return SessionRunDetails(
            sessionRunId=str(session_run.session_run_id),
            sessionId=str(session.sessionId),
            userId=str(current_user.id),
            username=current_user.username,
            sessionRunMetadata=session_run.session_run_metadata,
            assistantParameters=AssistantParameters(**session_run.assistant_parameters),
            status=session_run.status,
            courseName=session.courseName,
            className=session.className,
            courseCode=session.courseCode,
            description=session.description,
            duration=session.duration,
            presentationDetails=session.presentationDetails,
            slidesDetails=session.slidesDetails,
            startTime=session_run.start_time,
            endTime=session_run.end_time
        )
    except Exception as e:
        logger.error(f"❌ Error stopping session run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error stopping session run: {e}"
        )

@router.post("/sessions/{session_id}/run/{session_run_id}/stop/guest", response_model=SessionRunDetails)
async def stop_session_run(
    session_id: str,
    session_run_id: str,
    request_data: dict,
    # current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Stop a session run
    """
    try:
        session_run_metadata = request_data.get("session_run_metadata")
        
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        session_run = await session_service.stop_session_run(db, session_id, session_run_id, session_run_metadata)
        if not session_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return SessionRunDetails(
            sessionRunId=str(session_run.session_run_id),
            sessionId=str(session.sessionId),
            userId="8e3957ae-78b8-411f-85c9-a2640fa541f8",
            username="guest",
            sessionRunMetadata=session_run.session_run_metadata,
            assistantParameters=AssistantParameters(**session_run.assistant_parameters),
            status=session_run.status,
            courseName=session.courseName,
            className=session.className,
            courseCode=session.courseCode,
            description=session.description,
            duration=session.duration,
            presentationDetails=session.presentationDetails,
            slidesDetails=session.slidesDetails,
            startTime=session_run.start_time,
            endTime=session_run.end_time
        )
    except Exception as e:
        logger.error(f"❌ Error stopping session run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error stopping session run: {e}"
        )
    
@router.get("/sessions/{session_id}/run/{session_run_id}", response_model=SessionRunDetails)
async def get_session_run(
    session_id: str,
    session_run_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a session run by ID
    """
    try:
        logger.info(f"Getting session run for session_id: {session_id} and session_run_id: {session_run_id}")
        session_run = await session_service.get_session_run(db, session_id, session_run_id)
        if not session_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session run not found"
            )
        logger.info(f"Session run found")
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        logger.info(f"Session found")
        user = await session_service.get_user_by_id(db, session_run.user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        return SessionRunDetails(
            sessionRunId=str(session_run.session_run_id),
            sessionId=str(session.sessionId),
            userId=str(user.id),
            username=user.username,
            sessionRunMetadata=session_run.session_run_metadata,
            assistantParameters=AssistantParameters(**session_run.assistant_parameters),
            status=session_run.status,
            courseName=session.courseName,
            className=session.className,
            courseCode=session.courseCode,
            description=session.description,
            duration=session.duration,
            presentationDetails=session.presentationDetails,
            slidesDetails=session.slidesDetails,
            startTime=session_run.start_time,
            endTime=session_run.end_time
        )
    except Exception as e:
        logger.error(f"❌ Error getting session run: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting session run: {e}"
        )


@router.get("/session/ephemeral", response_model=EphemeralTokenResponse)
async def get_ephemeral_token(
    session_id: str,
    session_run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate an ephemeral token for OpenAI Realtime API
    
    Returns:
        EphemeralTokenResponse with client_secret containing token and expiration
        
    Raises:
        HTTPException: If token generation fails
    """
    try:
        print(f"Getting session slides for session_id: {session_id}")
        session_run = await session_service.get_session_run(db, session_id, session_run_id)
        if not session_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session run not found"
            )
        print(f"Session run status: {session_run.status}")
        if session_run.status != SessionRunStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session run is not active"
            )

        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )

        token_data = await openai_service.generate_ephemeral_token(session_run.assistant_parameters, session.slidesDetails, user_id=current_user.id, session_run_id=session_run.id, db=db)
        return EphemeralTokenResponse(client_secret=token_data["client_secret"])
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate ephemeral token: {str(e)}"
        )

@router.get("/sessions", response_model=SessionsListResponse)
async def get_sessions(
    page: int = Query(1, ge=1, description="Page number for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Number of sessions per page"),
    session_status: Optional[str] = Query(None, pattern="^(active|completed|draft)$", description="Filter by session status", alias="status"),
    sort: str = Query("created_desc", pattern="^(created_desc|created_asc|updated_desc|updated_asc)$", description="Sort order"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get paginated list of sessions for the authenticated user
    """
    try:
        sessions, pagination = await session_service.get_sessions_paginated(
            db=db,
            user_id=str(current_user.id),
            page=page,
            limit=limit,
            status=session_status,
            sort=sort
        )
        
        return SessionsListResponse(
            sessions=sessions,
            pagination=pagination
        )
    except Exception as e:
        logger.error(f"❌ Error getting sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting sessions: {e}"
        )

@router.get("/sessions/{session_id}/runs", response_model=SessionRunsListResponse)
async def get_session_runs(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all runs for a specific session
    """
    try:
        runs, total = await session_service.get_session_runs(
            db=db,
            session_id=session_id,
            user_id=str(current_user.id)
        )
        
        return SessionRunsListResponse(
            runs=runs,
            total=total
        )
    except Exception as e:
        logger.error(f"❌ Error getting session runs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting session runs: {e}"
        )
    
@router.post("/sessions/{session_id}/slides/{slide_id}/vision", response_model=SessionDetails)
async def update_slide_vision(
    session_id: str,
    slide_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        for slide in session.slidesDetails:
            logger.info(f"Slide ID: {slide.id}")
            if slide.id == int(slide_id):
                logger.info(f"Updating slide vision for slide_id: {slide_id}")
                slide.visionInstructions = request_data.get('visionInstructions')
                slide.visionModel = request_data.get('visionModel')
                logger.info(f"Slide vision instructions: {slide.visionInstructions}")
                
                # Handle both S3 URLs and local file paths
                logger.info(f"Slide image path: {slide.imagePath}")
                
                # Check if the path is an S3 URL
                if slide.imagePath.startswith('http://') or slide.imagePath.startswith('https://'):
                    # Download image from S3 URL
                    logger.info(f"Downloading image from S3 URL: {slide.imagePath}")
                    try:
                        response = requests.get(slide.imagePath, timeout=30)
                        response.raise_for_status()
                        slide_image = Image.open(BytesIO(response.content))
                        logger.info(f"Successfully downloaded image from S3")
                    except requests.RequestException as e:
                        logger.error(f"Failed to download image from S3: {e}")
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Failed to download slide image from S3: {str(e)}"
                        )
                else:
                    # Handle local file paths
                    if slide.imagePath.startswith('/uploads/'):
                        # Remove the leading '/uploads/' and use the upload_dir setting
                        relative_path = slide.imagePath[9:]  # Remove '/uploads/'
                        actual_file_path = Path(settings.upload_dir) / relative_path
                    else:
                        # Fallback: try the path as-is, removing leading '/'
                        actual_file_path = Path(slide.imagePath.lstrip('/'))
                    
                    logger.info(f"Local file path: {actual_file_path}")
                    
                    if not actual_file_path.exists():
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Slide image file not found: {actual_file_path}"
                        )
                    
                    slide_image = Image.open(actual_file_path)
                
                # Process the slide with vision API
                slide_details = await openai_service.process_slide_with_vision(slide_image, slide.visionInstructions, slide.visionModel, user_id=current_user.id, db=db)
                slide.content = slide_details.get('content')
                slide.title = slide_details.get('title')
                logger.info(f"Successfully updated slide vision for slide {slide_id}")
                break
        # Convert SlideData objects to dictionaries for JSON serialization
        slides_dict_list = []
        for slide in session.slidesDetails:
            slides_dict_list.append(slide.model_dump() if hasattr(slide, 'model_dump') else slide.dict())
        
        updated_session = await session_service.update_session_slides(db, session_id, slides_dict_list)
        if not updated_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return updated_session

    except Exception as e:
        logger.error(f"❌ Error updating slide vision: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating slide vision: {e}"
        )
    
@router.put("/sessions/{session_id}/slides/{slide_id}/content", response_model=SessionDetails)
async def update_slide_content(
    session_id: str,
    slide_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        print(f"Updating slide content for session_id: {session_id} and slide_id: {slide_id}")
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        for slide in session.slidesDetails:
            if slide.id == int(slide_id):
                slide.content = request_data.get('content')
                slide.title = request_data.get('title')
                break
        # Convert SlideData objects to dictionaries for JSON serialization
        slides_dict_list = []
        for slide in session.slidesDetails:
            slides_dict_list.append(slide.model_dump() if hasattr(slide, 'model_dump') else slide.dict())
        
        updated_session = await session_service.update_session_slides(db, session_id, slides_dict_list)
        if not updated_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        return updated_session
    except Exception as e:
        logger.error(f"❌ Error updating slide content: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating slide content: {e}"
        )

@router.post("/sessions/{session_id}/slides/add", response_model=SessionDetails)
async def add_new_slide(
    session_id: str,
    slide_image: UploadFile = File(...),
    vision_instructions: str = Form(None),
    vision_model: str = Form("gpt-4o"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        logger.info(f"Adding new slide to session: {session_id}")
        
        # Get session
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        # Read image file
        image_content = await slide_image.read()
        slide_image_pil = Image.open(BytesIO(image_content))
        
        # Determine next slide number
        max_slide_number = max([slide.slideNumber for slide in session.slidesDetails]) if session.slidesDetails else 0
        new_slide_number = max_slide_number + 1
        
        # Create session-specific directory paths
        session_dir = Path(settings.upload_dir) / session_id
        session_slides_dir = session_dir / "slides"
        session_slides_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filenames
        image_filename = f"slide_{new_slide_number - 1}.png"
        thumbnail_filename = f"thumb_{new_slide_number - 1}.png"
        
        # Save full-size image
        full_image_path = session_slides_dir / image_filename
        slide_image_pil.save(full_image_path, 'PNG')
        logger.info(f"Saved slide image: {full_image_path}")
        
        # Create and save thumbnail
        thumbnail_image = slide_image_pil.copy()
        thumbnail_image.thumbnail((256, 192), Image.Resampling.LANCZOS)
        thumbnail_path = session_slides_dir / thumbnail_filename
        thumbnail_image.save(thumbnail_path, 'PNG')
        logger.info(f"Saved thumbnail: {thumbnail_path}")
        
        # Handle cloud storage or local paths
        if settings.use_cloud_storage:
            from app.services.cloud_storage_service import cloud_storage
            
            # Convert images to bytes
            full_image_buffer = BytesIO()
            slide_image_pil.save(full_image_buffer, format='PNG')
            full_image_bytes = full_image_buffer.getvalue()
            
            thumbnail_buffer = BytesIO()
            thumbnail_image.save(thumbnail_buffer, format='PNG')
            thumbnail_bytes = thumbnail_buffer.getvalue()
            
            # Upload to S3
            full_s3_key, full_public_url = await cloud_storage.upload_image(
                image_data=full_image_bytes,
                file_path=str(full_image_path),
                content_type='image/png',
                metadata={
                    'session_id': session_id,
                    'slide_number': str(new_slide_number),
                    'image_type': 'full_size'
                }
            )
            
            thumbnail_s3_key, thumbnail_public_url = await cloud_storage.upload_image(
                image_data=thumbnail_bytes,
                file_path=str(thumbnail_path),
                content_type='image/png',
                metadata={
                    'session_id': session_id,
                    'slide_number': str(new_slide_number),
                    'image_type': 'thumbnail'
                }
            )
            
            image_path = full_public_url
            thumbnail_path_url = thumbnail_public_url
        else:
            image_path = f"/uploads/{session_id}/slides/{image_filename}"
            thumbnail_path_url = f"/uploads/{session_id}/slides/{thumbnail_filename}"
        
        # Process with vision API
        if not vision_instructions:
            vision_instructions = "You are a helpful assistant that can analyze the slide image and provide a detailed description of the content."
        
        slide_details = await openai_service.process_slide_with_vision(
            slide_image_pil,
            vision_instructions,
            vision_model,
            user_id=current_user.id,
            db=db,
        )

        # Create new slide object
        new_slide = {
            "id": new_slide_number,
            "slideNumber": new_slide_number,
            "title": slide_details.get('title'),
            "content": slide_details.get('content'),
            "imagePath": image_path,
            "thumbnailPath": thumbnail_path_url,
            "visionInstructions": vision_instructions,
            "visionModel": vision_model
        }
        
        # Add to session slides
        slides_dict_list = []
        for slide in session.slidesDetails:
            slides_dict_list.append(slide.model_dump() if hasattr(slide, 'model_dump') else slide.dict())
        slides_dict_list.append(new_slide)
        
        # Update session
        updated_session = await session_service.update_session_slides(db, session_id, slides_dict_list)
        logger.info(f"✅ Successfully added new slide {new_slide_number} to session {session_id}")
        
        return updated_session
        
    except Exception as e:
        logger.error(f"❌ Error adding new slide: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error adding new slide: {e}"
        )

@router.delete("/sessions/{session_id}/slides/{slide_id}", response_model=SessionDetails)
async def delete_slide(
    session_id: str,
    slide_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        logger.info(f"Deleting slide {slide_id} from session: {session_id}")
        
        # Get session
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        # Find and remove the slide
        slide_to_delete = None
        remaining_slides = []
        for slide in session.slidesDetails:
            if slide.id == int(slide_id):
                slide_to_delete = slide
            else:
                remaining_slides.append(slide)
        
        if not slide_to_delete:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Slide not found"
            )
        
        # Reorganize slide numbers
        slides_dict_list = []
        for idx, slide in enumerate(remaining_slides, start=1):
            slide_dict = slide.model_dump() if hasattr(slide, 'model_dump') else slide.dict()
            slide_dict['id'] = idx
            slide_dict['slideNumber'] = idx
            slides_dict_list.append(slide_dict)
        
        # Update session
        updated_session = await session_service.update_session_slides(db, session_id, slides_dict_list)
        logger.info(f"✅ Successfully deleted slide and reorganized slide numbers")
        
        return updated_session
        
    except Exception as e:
        logger.error(f"❌ Error deleting slide: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting slide: {e}"
        )

@router.put("/sessions/{session_id}/slides/{slide_id}/replace-image", response_model=SessionDetails)
async def replace_slide_image(
    session_id: str,
    slide_id: str,
    slide_image: UploadFile = File(...),
    vision_instructions: str = Form(None),
    vision_model: str = Form("gpt-4o"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        logger.info(f"Replacing image for slide {slide_id} in session: {session_id}")
        
        # Get session
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        # Find the slide
        target_slide = None
        for slide in session.slidesDetails:
            if slide.id == int(slide_id):
                target_slide = slide
                break
        
        if not target_slide:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Slide not found"
            )
        
        # Read new image file
        image_content = await slide_image.read()
        slide_image_pil = Image.open(BytesIO(image_content))
        
        # Create session-specific directory paths
        session_dir = Path(settings.upload_dir) / session_id
        session_slides_dir = session_dir / "slides"
        session_slides_dir.mkdir(parents=True, exist_ok=True)
        
        # Use existing filenames based on slide number
        image_filename = f"slide_{target_slide.slideNumber - 1}.png"
        thumbnail_filename = f"thumb_{target_slide.slideNumber - 1}.png"
        
        # Save full-size image (overwrite existing)
        full_image_path = session_slides_dir / image_filename
        slide_image_pil.save(full_image_path, 'PNG')
        logger.info(f"Replaced slide image: {full_image_path}")
        
        # Create and save thumbnail
        thumbnail_image = slide_image_pil.copy()
        thumbnail_image.thumbnail((256, 192), Image.Resampling.LANCZOS)
        thumbnail_path = session_slides_dir / thumbnail_filename
        thumbnail_image.save(thumbnail_path, 'PNG')
        logger.info(f"Replaced thumbnail: {thumbnail_path}")
        
        # Handle cloud storage or local paths
        if settings.use_cloud_storage:
            from app.services.cloud_storage_service import cloud_storage
            
            # Convert images to bytes
            full_image_buffer = BytesIO()
            slide_image_pil.save(full_image_buffer, format='PNG')
            full_image_bytes = full_image_buffer.getvalue()
            
            thumbnail_buffer = BytesIO()
            thumbnail_image.save(thumbnail_buffer, format='PNG')
            thumbnail_bytes = thumbnail_buffer.getvalue()
            
            # Upload to S3 (overwrite existing)
            full_s3_key, full_public_url = await cloud_storage.upload_image(
                image_data=full_image_bytes,
                file_path=str(full_image_path),
                content_type='image/png',
                metadata={
                    'session_id': session_id,
                    'slide_number': str(target_slide.slideNumber),
                    'image_type': 'full_size'
                }
            )
            
            thumbnail_s3_key, thumbnail_public_url = await cloud_storage.upload_image(
                image_data=thumbnail_bytes,
                file_path=str(thumbnail_path),
                content_type='image/png',
                metadata={
                    'session_id': session_id,
                    'slide_number': str(target_slide.slideNumber),
                    'image_type': 'thumbnail'
                }
            )
            
            image_path = full_public_url
            thumbnail_path_url = thumbnail_public_url
        else:
            image_path = f"/uploads/{session_id}/slides/{image_filename}"
            thumbnail_path_url = f"/uploads/{session_id}/slides/{thumbnail_filename}"
        
        # Use provided vision instructions or existing ones
        if not vision_instructions:
            vision_instructions = target_slide.visionInstructions or "You are a helpful assistant that can analyze the slide image and provide a detailed description of the content."
        
        # Process with vision API
        slide_details = await openai_service.process_slide_with_vision(
            slide_image_pil,
            vision_instructions,
            vision_model,
            user_id=current_user.id,
            db=db,
        )

        # Update slide
        target_slide.imagePath = image_path
        target_slide.thumbnailPath = thumbnail_path_url
        target_slide.title = slide_details.get('title')
        target_slide.content = slide_details.get('content')
        target_slide.visionInstructions = vision_instructions
        target_slide.visionModel = vision_model
        
        # Convert slides to dictionaries
        slides_dict_list = []
        for slide in session.slidesDetails:
            slides_dict_list.append(slide.model_dump() if hasattr(slide, 'model_dump') else slide.dict())
        
        # Update session
        updated_session = await session_service.update_session_slides(db, session_id, slides_dict_list)
        logger.info(f"✅ Successfully replaced image and regenerated content for slide {slide_id}")
        
        return updated_session
        
    except Exception as e:
        logger.error(f"❌ Error replacing slide image: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error replacing slide image: {e}"
        )

@router.put("/sessions/{session_id}/slides/reorder", response_model=SessionDetails)
async def reorder_slides(
    session_id: str,
    request_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        logger.info(f"Reordering slides for session: {session_id}")
        
        # Get session
        session = await session_service.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        slide_order = request_data.get('slideOrder', [])
        if not slide_order:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="slideOrder is required"
            )
        
        # Create a mapping of old IDs to slides
        slides_by_id = {}
        for slide in session.slidesDetails:
            slides_by_id[slide.id] = slide
        
        # Reorder slides
        reordered_slides = []
        for new_position, old_id in enumerate(slide_order, start=1):
            if old_id not in slides_by_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid slide ID: {old_id}"
                )
            
            slide = slides_by_id[old_id]
            slide_dict = slide.model_dump() if hasattr(slide, 'model_dump') else slide.dict()
            slide_dict['id'] = new_position
            slide_dict['slideNumber'] = new_position
            reordered_slides.append(slide_dict)
        
        # Update session
        updated_session = await session_service.update_session_slides(db, session_id, reordered_slides)
        logger.info(f"✅ Successfully reordered slides")
        
        return updated_session
        
    except Exception as e:
        logger.error(f"❌ Error reordering slides: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reordering slides: {e}"
        )