import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import get_current_user, auth_service
from app.schemas.schemas import (
    UserRegistration, UserLogin, AuthResponse, TokenVerifyResponse, 
    RefreshTokenResponse, LogoutResponse, UserResponse, UserProfileUpdate,
    UserSessionsResponse, UserSessionSummary
)

# Set up logger
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["authentication"])

@router.post("/register", response_model=AuthResponse)
async def register_user(
    registration_data: UserRegistration,
    db: Session = Depends(get_db)
):
    """Register a new user"""
    try:
        result = await auth_service.register_user(db, registration_data)
        
        if not result.success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST if "already" in result.message else status.HTTP_409_CONFLICT,
                detail=result.message
            )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error registering user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during registration"
        )

@router.post("/login", response_model=AuthResponse)
async def login_user(
    login_data: UserLogin,
    db: Session = Depends(get_db)
):
    """Authenticate user and return JWT token"""
    try:
        result = await auth_service.login_user(db, login_data.username, login_data.password)
        
        if not result.success:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=result.message
            )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error during login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during login"
        )

@router.get("/verify-token", response_model=TokenVerifyResponse)
async def verify_token(
    current_user: User = Depends(get_current_user)
):
    """Verify JWT token and return user information"""
    try:
        # If we reach here, token is valid (dependency handled verification)
        user_response = auth_service.user_to_response(current_user)
        
        return TokenVerifyResponse(
            success=True,
            user=user_response,
            expiresAt=None  # Could add token expiry extraction if needed
        )
    except Exception as e:
        logger.error(f"❌ Error verifying token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during token verification"
        )

@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    current_user: User = Depends(get_current_user)
):
    """Refresh JWT token"""
    try:
        # Generate new token for current user
        token_data = auth_service.create_access_token(str(current_user.id), current_user.username)
        
        return RefreshTokenResponse(
            success=True,
            token=token_data["token"],
            expiresAt=token_data["expires_at"]
        )
    except Exception as e:
        logger.error(f"❌ Error refreshing token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during token refresh"
        )

@router.post("/logout", response_model=LogoutResponse)
async def logout_user(
    current_user: User = Depends(get_current_user)
):
    """Logout user (token-based, so just return success)"""
    # In a stateless JWT system, logout is handled client-side by discarding the token
    # For enhanced security, you could implement a token blacklist here
    return LogoutResponse(
        success=True,
        message="Logged out successfully"
    )

@router.get("/verify-email")
async def verify_email(
    token: str,
    db: Session = Depends(get_db)
):
    """Verify user email with token"""
    try:
        result = await auth_service.verify_email(db, token)
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["message"]
            )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error verifying email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during email verification"
        )

@router.get("/approve-user")
async def approve_user(
    token: str,
    db: Session = Depends(get_db)
):
    """Approve a user account"""
    try:
        result = await auth_service.approve_user(db, token)
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["message"]
            )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error approving user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during user approval"
        ) 