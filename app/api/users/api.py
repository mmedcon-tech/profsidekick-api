import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.database.models import User, Session as SessionModel
from app.dependencies.auth import get_current_user, require_admin, auth_service
from app.schemas.schemas import (
    UserResponse, UserProfileUpdate, UserSessionsResponse, UserSessionSummary
)

# Set up logger
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])

@router.get("/profile", response_model=UserResponse)
async def get_user_profile(
    current_user: User = Depends(get_current_user)
):
    """Get current user profile"""
    try:
        return auth_service.user_to_response(current_user)
    except Exception as e:
        logger.error(f"❌ Error getting user profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.put("/profile", response_model=UserResponse)
async def update_user_profile(
    profile_update: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update current user profile"""
    try:
        # Convert field names to match database columns
        update_data = {}
        if profile_update.firstName is not None:
            update_data["first_name"] = profile_update.firstName
        if profile_update.lastName is not None:
            update_data["last_name"] = profile_update.lastName
        if profile_update.email is not None:
            # Check if email is already in use by another user
            existing_user = db.query(User).filter(
                User.email == profile_update.email,
                User.id != current_user.id
            ).first()
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already in use by another user"
                )
            update_data["email"] = profile_update.email
        
        updated_user = await auth_service.update_user_profile(db, str(current_user.id), update_data)
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return auth_service.user_to_response(updated_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating user profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.get("/sessions", response_model=UserSessionsResponse)
async def get_user_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all sessions for the current user"""
    try:
        sessions = db.query(SessionModel).filter(SessionModel.user_id == current_user.id).all()
        
        session_summaries = []
        for session in sessions:
            # Count slides
            slides_count = 0
            if session.slides_details and isinstance(session.slides_details, list):
                slides_count = len(session.slides_details)
            
            session_summaries.append(UserSessionSummary(
                sessionId=session.session_id,
                className=session.class_name or "",
                courseName=session.course_name or "",
                courseCode=session.course_code or "",
                createdAt=session.created_at,
                slidesCount=slides_count,
                duration=session.duration or 0
            ))
        
        return UserSessionsResponse(sessions=session_summaries)
    except Exception as e:
        logger.error(f"❌ Error getting user sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


# ══════════════════════════════════════════════════════════════════
# Admin — User management
# ══════════════════════════════════════════════════════════════════

class UserAdminResponse(UserResponse):
    is_approved: Optional[bool] = None
    email_verified: Optional[bool] = None

class UserListAdminResponse(UserResponse):
    is_approved: Optional[bool] = None
    email_verified: Optional[bool] = None

    class Config:
        from_attributes = True


@router.get("/admin/users", response_model=List[UserResponse])
async def admin_list_users(
    role: Optional[str] = Query(None, description="Filter by role: publisher, subscriber, admin"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin: list all users, optionally filtered by role."""
    try:
        query = db.query(User)
        if role:
            query = query.filter(User.role == role)
        users = query.order_by(User.created_at.desc()).all()
        return [auth_service.user_to_response(u) for u in users]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ admin_list_users error: {e}")
        raise HTTPException(status_code=500, detail="Error listing users")


@router.delete("/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_user(
    user_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin: delete any user account."""
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if str(user.id) == str(current_user.id):
            raise HTTPException(status_code=400, detail="Cannot delete your own account")
        db.delete(user)
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ admin_delete_user error: {e}")
        raise HTTPException(status_code=500, detail="Error deleting user")