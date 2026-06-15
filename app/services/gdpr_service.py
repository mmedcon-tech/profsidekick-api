"""W2C: GDPR compliance — user agreement recording, data export, and erasure."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database.models import User, UserAgreement

_VALID_AGREEMENT_TYPES = {"terms", "privacy", "gdpr", "marketing"}


def record_agreement(
    user: User,
    agreement_type: str,
    db: Session,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> UserAgreement:
    if agreement_type not in _VALID_AGREEMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"agreement_type must be one of: {sorted(_VALID_AGREEMENT_TYPES)}",
        )

    now = datetime.utcnow()
    agreement = UserAgreement(
        user_id=user.id,
        agreement_type=agreement_type,
        agreed_at=now,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(agreement)

    # Mirror timestamp on the User row for quick lookups
    if agreement_type == "terms":
        user.terms_accepted_at = now
    elif agreement_type == "privacy":
        user.privacy_accepted_at = now
    elif agreement_type == "gdpr":
        user.gdpr_consent_at = now
    elif agreement_type == "marketing":
        user.marketing_emails_opt_in = True

    user.updated_at = now
    db.commit()
    db.refresh(agreement)
    return agreement


def erase_user(user: User, db: Session) -> None:
    now = datetime.utcnow()
    user.is_deleted = True
    user.deleted_at = now
    user.updated_at = now
    # Anonymise PII while retaining the row for FK integrity
    user.email = f"deleted+{user.id}@erased.local"
    user.username = f"deleted_{user.id}"
    user.first_name = "Deleted"
    user.last_name = "User"
    user.password_hash = ""
    user.email_verification_token = None
    user.approval_token = None
    db.commit()


def export_user_data(user: User, db: Session) -> dict[str, Any]:
    agreements = (
        db.query(UserAgreement)
        .filter(UserAgreement.user_id == user.id)
        .order_by(UserAgreement.agreed_at)
        .all()
    )
    return {
        "user": {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "terms_accepted_at": user.terms_accepted_at.isoformat() if user.terms_accepted_at else None,
            "privacy_accepted_at": user.privacy_accepted_at.isoformat() if user.privacy_accepted_at else None,
            "gdpr_consent_at": user.gdpr_consent_at.isoformat() if user.gdpr_consent_at else None,
            "marketing_emails_opt_in": user.marketing_emails_opt_in,
        },
        "agreements": [
            {
                "type": a.agreement_type,
                "agreed_at": a.agreed_at.isoformat(),
                "ip_address": a.ip_address,
            }
            for a in agreements
        ],
    }
