import jwt
import bcrypt
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status
from app.database.models import User
from app.schemas.schemas import UserRegistration, UserResponse, AuthResponse
from app.config import settings
from app.services.email_service import email_service
import uuid


class AuthService:
    """Service for handling authentication operations"""
    
    def __init__(self):
        self.algorithm = "HS256"
        self.access_token_expire_hours = 24
    
    def hash_password(self, password: str) -> str:
        """Hash a password using bcrypt"""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    def verify_password(self, password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
    
    def create_access_token(self, user_id: str, username: str) -> Dict[str, Any]:
        """Create a JWT access token"""
        expires_at = datetime.utcnow() + timedelta(hours=self.access_token_expire_hours)
        payload = {
            "user_id": user_id,
            "username": username,
            "exp": expires_at,
            "iat": datetime.utcnow()
        }
        token = jwt.encode(payload, settings.secret_key, algorithm=self.algorithm)
        return {
            "token": token,
            "expires_at": expires_at
        }
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify and decode a JWT token"""
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        except jwt.PyJWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
    
    def user_to_response(self, user: User) -> UserResponse:
        """Convert User model to UserResponse schema"""
        return UserResponse(
            id=str(user.id),
            username=user.username,
            email=user.email,
            firstName=user.first_name,
            lastName=user.last_name,
            role=user.role,
            createdAt=user.created_at
        )
    
    def generate_token(self) -> str:
        """Generate a secure random token"""
        return secrets.token_urlsafe(32)
    
    async def register_user(self, db: Session, registration_data: UserRegistration) -> AuthResponse:
        """Register a new user with email verification"""
        # Check if username already exists
        existing_user = db.query(User).filter(User.username == registration_data.username).first()
        if existing_user:
            return AuthResponse(
                success=False,
                message="Username already exists"
            )
        
        # Check if email already exists
        existing_email = db.query(User).filter(User.email == registration_data.email).first()
        if existing_email:
            return AuthResponse(
                success=False,
                message="Email already registered"
            )
        
        # Check if role is valid
        if registration_data.role not in ["publisher", "subscriber", "admin"]:
            return AuthResponse(
                success=False,
                message="Invalid role. Must be publisher, subscriber, or admin."
            )
        
        # Generate email verification token
        verification_token = self.generate_token()
        
        # Create new user with email_verified=False and is_approved=False
        hashed_password = self.hash_password(registration_data.password)
        new_user = User(
            id=uuid.uuid4(),
            username=registration_data.username,
            email=registration_data.email,
            password_hash=hashed_password,
            first_name=registration_data.firstName,
            last_name=registration_data.lastName,
            role=registration_data.role,
            email_verified=settings.bypass_email_verification,
            email_verification_token=verification_token,
            email_verification_sent_at=datetime.utcnow(),
            is_approved=settings.bypass_email_verification
        )
        
        try:
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
        except IntegrityError:
            db.rollback()
            return AuthResponse(
                success=False,
                message="Username or email already registered"
            )

        # Send verification email via configured SMTP / provider
        user_name = f"{new_user.first_name} {new_user.last_name}"
        email_sent = await email_service.send_verification_email(
            new_user.email,
            user_name,
            verification_token
        )

        if not email_sent:
            # Keep the account; user can request support / re-register after SMTP is fixed
            return AuthResponse(
                success=True,
                message=(
                    "Registration successful, but we could not send the verification email. "
                    "Please contact support or try again later."
                ),
                user=self.user_to_response(new_user),
            )
        
        return AuthResponse(
            success=True,
            message="Registration successful! Please check your email to verify your account.",
            user=self.user_to_response(new_user)
        )
    
    async def login_user(self, db: Session, username: str, password: str) -> AuthResponse:
        """Authenticate user and return token"""
        user = db.query(User).filter(User.username == username).first()
        
        if not user or not self.verify_password(password, user.password_hash):
            return AuthResponse(
                success=False,
                message="Invalid username or password"
            )
        
        # Check if email is verified (skip check if email_verified is None for old accounts)
        if user.email_verified is False:
            return AuthResponse(
                success=False,
                message="Please verify your email address before logging in. Check your email for the verification link."
            )
        
        # Check if account is approved (skip check if is_approved is None for old accounts)
        if user.is_approved is False:
            return AuthResponse(
                success=False,
                message="Your account is pending approval. You will receive an email once your account is approved."
            )
        
        # Create access token
        token_data = self.create_access_token(str(user.id), user.username)
        
        return AuthResponse(
            success=True,
            user=self.user_to_response(user),
            token=token_data["token"],
            expiresAt=token_data["expires_at"]
        )
    
    async def get_user_by_id(self, db: Session, user_id: str) -> Optional[User]:
        """Get user by ID"""
        return db.query(User).filter(User.id == user_id).first()
    
    async def update_user_profile(self, db: Session, user_id: str, update_data: Dict[str, Any]) -> Optional[User]:
        """Update user profile"""
        user = await self.get_user_by_id(db, user_id)
        if not user:
            return None
        
        for field, value in update_data.items():
            if hasattr(user, field) and value is not None:
                setattr(user, field, value)
        
        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
        return user
    
    async def verify_email(self, db: Session, token: str) -> Dict[str, Any]:
        """Verify user email with token"""
        user = db.query(User).filter(User.email_verification_token == token).first()
        
        if not user:
            return {
                "success": False,
                "message": "Invalid or expired verification token"
            }
        
        if user.email_verified:
            return {
                "success": False,
                "message": "Email already verified"
            }
        
        # Mark email as verified
        user.email_verified = True
        user.email_verification_token = None  # Clear the token
        user.updated_at = datetime.utcnow()

        professor_emails = settings.professor_approval_emails or []
        if not professor_emails:
            # No approvers configured — auto-approve so SMTP verification alone unlocks login
            user.is_approved = True
            user.approval_token = None
            user.approved_at = datetime.utcnow()
            user.approved_by = "auto"
            db.commit()
            db.refresh(user)
            return {
                "success": True,
                "message": "Email verified successfully! You can now sign in.",
            }

        # Generate approval token and send to professor
        approval_token = self.generate_token()
        user.approval_token = approval_token
        user.approval_request_sent_at = datetime.utcnow()
        
        db.commit()
        db.refresh(user)
        
        # Send approval request to professor
        user_name = f"{user.first_name} {user.last_name}"
        email_sent = await email_service.send_approval_request_email(
            user.email,
            user_name,
            user.role,
            approval_token
        )
        
        if not email_sent:
            return {
                "success": True,
                "message": "Email verified, but failed to send approval request. Please contact support."
            }
        
        return {
            "success": True,
            "message": "Email verified successfully! Your account has been sent for approval. You'll receive an email once approved."
        }
    
    async def approve_user(self, db: Session, token: str, approver_email: str = None) -> Dict[str, Any]:
        """Approve a user account with token"""
        user = db.query(User).filter(User.approval_token == token).first()
        
        if not user:
            return {
                "success": False,
                "message": "Invalid or expired approval token"
            }
        
        if not user.email_verified:
            return {
                "success": False,
                "message": "User email is not verified"
            }
        
        if user.is_approved:
            return {
                "success": False,
                "message": "User account is already approved"
            }
        
        # Mark account as approved
        user.is_approved = True
        user.approval_token = None  # Clear the token
        user.approved_at = datetime.utcnow()
        user.approved_by = approver_email or ', '.join(settings.professor_approval_emails)
        user.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(user)
        
        # Send confirmation email to user
        user_name = f"{user.first_name} {user.last_name}"
        email_sent = await email_service.send_approval_confirmation_email(
            user.email,
            user_name
        )
        
        if not email_sent:
            return {
                "success": True,
                "message": "Account approved, but failed to send confirmation email."
            }
        
        return {
            "success": True,
            "message": "User account approved successfully! The user has been notified.",
            "user": self.user_to_response(user)
        }

    async def request_password_reset(self, db: Session, email: str) -> Dict[str, Any]:
        """
        Create a password-reset token and email it.
        Always returns a generic success message to avoid email enumeration.
        """
        generic = {
            "success": True,
            "message": "If an account exists for that email, a password reset link has been sent.",
        }
        user = db.query(User).filter(User.email == email.strip().lower()).first()
        if not user:
            # Case-insensitive fallback (emails may have been stored with original casing)
            user = db.query(User).filter(User.email.ilike(email.strip())).first()
        if not user:
            return generic

        reset_token = self.generate_token()
        user.password_reset_token = reset_token
        user.password_reset_sent_at = datetime.utcnow()
        user.updated_at = datetime.utcnow()
        db.commit()

        user_name = f"{user.first_name} {user.last_name}".strip() or user.username
        await email_service.send_password_reset_email(user.email, user_name, reset_token)
        return generic

    async def reset_password(self, db: Session, token: str, new_password: str) -> Dict[str, Any]:
        """Reset password using a one-time token (valid for 1 hour)."""
        user = db.query(User).filter(User.password_reset_token == token).first()
        if not user or not user.password_reset_sent_at:
            return {
                "success": False,
                "message": "Invalid or expired reset token",
            }

        age = datetime.utcnow() - user.password_reset_sent_at
        if age > timedelta(hours=1):
            user.password_reset_token = None
            user.password_reset_sent_at = None
            db.commit()
            return {
                "success": False,
                "message": "Invalid or expired reset token",
            }

        user.password_hash = self.hash_password(new_password)
        user.password_reset_token = None
        user.password_reset_sent_at = None
        user.updated_at = datetime.utcnow()
        db.commit()

        return {
            "success": True,
            "message": "Password updated successfully. You can now sign in.",
        }

