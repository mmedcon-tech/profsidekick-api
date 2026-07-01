"""
Public invitation routes — no authentication required.

GET  /api/sae/invite/{token}        → validate token, return student info + use_count state
POST /api/sae/invite/{token}/setup  → set or update credentials, activate account

The link is usable at most twice:
  First use  (use_count == 0): student creates username + password.
  Second use (use_count == 1): student may update username and/or password.
  After the second successful use the link is permanently expired (is_used=True).
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
    Returns student_code, display_name, and is_first_use so the frontend can
    show the full setup form (first use) or the credential-change form (second use).
    No sensitive data is exposed.
    """
    is_valid, reason, token_row = sae_service.validate_invitation_token(db, token)
    if not is_valid:
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
        is_first_use=(token_row.use_count == 0),
    )


@router.post("/{token}/setup", response_model=SAESetupResponse)
async def setup_account(
    token: str,
    body: SAEInviteSetupRequest,
    db: Session = Depends(get_db),
):
    """
    Activate or update a student account via invitation link.

    First use  (is_first_use=True):
      username, password, country_of_origin, and curriculum are all required.
      Atomically creates a users row, links it to the student, and consumes one use.

    Second use (is_first_use=False):
      At least one of username or password must be supplied.
      Updates whichever credential(s) were provided, increments token_version
      (which invalidates JWTs issued before this moment on other devices),
      and permanently expires the link.

    Returns a fresh JWT so the student is immediately logged in regardless of use.
    No email is ever sent at any point.
    """
    success, error_msg, new_user = sae_service.activate_student_account(
        db=db,
        token_value=token,
        username=body.username.strip() if body.username else None,
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

    # Issue a fresh JWT with the current token_version so the student is
    # immediately logged in and any stale tokens on other devices are rejected.
    token_data = _auth.create_access_token(str(new_user.id), new_user.username, new_user.token_version or 1)

    sae_student = db.query(SAEStudent).filter(
        SAEStudent.user_id == new_user.id
    ).first()

    return SAESetupResponse(
        access_token=token_data["token"],
        student_code=sae_student.student_code if sae_student else "",
        display_name=sae_student.display_name if sae_student else new_user.first_name,
    )
