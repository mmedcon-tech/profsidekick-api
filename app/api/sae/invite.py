"""
Public invitation routes — no authentication required.

GET  /api/sae/invite/{token}        → validate token, return student info
POST /api/sae/invite/{token}/setup  → choose username/password, activate account
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models.sae import SAEStudent
from app.schemas.sae import SAEInviteSetupRequest, SAESetupResponse, SAETokenValidationResponse
from app.services import sae_service
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/sae/invite", tags=["sae-invite"])

_auth = AuthService()


@router.get("/{token}", response_model=SAETokenValidationResponse)
def validate_token(token: str, db: Session = Depends(get_db)):
    """
    Check whether an invitation token is still valid.
    Returns student_code and display_name on success so the frontend can
    personalise the setup form. No sensitive data is exposed.
    """
    is_valid, reason, token_row = sae_service.validate_invitation_token(db, token)
    if not is_valid:
        # 410 Gone for consumed/expired; 404 for nonexistent
        code = (
            status.HTTP_410_GONE
            if "already been used" in reason or "expired" in reason
            else status.HTTP_404_NOT_FOUND
        )
        raise HTTPException(status_code=code, detail=reason)

    student = token_row.student
    return SAETokenValidationResponse(
        valid=True,
        student_code=student.student_code,
        display_name=student.display_name,
    )


@router.post("/{token}/setup", response_model=SAESetupResponse)
async def setup_account(
    token: str,
    body: SAEInviteSetupRequest,
    db: Session = Depends(get_db),
):
    """
    Activate a student account.

    Atomically:
      - Validates the invitation token (with a SELECT FOR UPDATE lock so
        two simultaneous requests cannot both succeed).
      - Creates a users row (email_verified=True, is_approved=True —
        no email verification or admin approval needed).
      - Links sae_students.user_id and marks is_activated=True.
      - Invalidates the token permanently.

    Returns a JWT so the student is immediately logged in after setup.
    No email is sent at any point.
    """
    success, error_msg, new_user = sae_service.activate_student_account(
        db=db,
        token_value=token,
        username=body.username.strip(),
        password=body.password,
        country_of_origin=body.country_of_origin,
        curriculum=body.curriculum,
    )

    if not success:
        if "already been used" in error_msg or "expired" in error_msg:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=error_msg)
        if "already taken" in error_msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    # Issue a JWT — same flow as /api/auth/login
    token_data = _auth.create_access_token(str(new_user.id), new_user.username)

    # Reload student to get the code/display_name
    sae_student = db.query(SAEStudent).filter(
        SAEStudent.user_id == new_user.id
    ).first()

    return SAESetupResponse(
        access_token=token_data["token"],
        student_code=sae_student.student_code if sae_student else "",
        display_name=sae_student.display_name if sae_student else new_user.first_name,
    )
