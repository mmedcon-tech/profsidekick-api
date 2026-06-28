from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field


# ── Request schemas ────────────────────────────────────────────────────────────

class SAEBatchCreateRequest(BaseModel):
    count: int = Field(..., ge=1, le=500,
                       description="How many student slots to generate")
    expires_days: Optional[int] = Field(
        None, ge=1, le=365,
        description="Days until invitation links expire. Omit for no expiry."
    )


class SAEInviteSetupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)


class SAEQuestionEdit(BaseModel):
    id: str
    score: Optional[float] = None
    feedback: Optional[str] = None


class SAESubmissionEditRequest(BaseModel):
    overall_feedback: Optional[str] = None
    questions: Optional[List[SAEQuestionEdit]] = None


# ── Response schemas ───────────────────────────────────────────────────────────

class SAEStudentRow(BaseModel):
    id: UUID
    student_number: int
    student_code: str
    display_name: str
    invitation_url: str
    invitation_token: str
    is_activated: bool
    activated_at: Optional[datetime]
    has_submitted: bool
    submitted_at: Optional[datetime]

    class Config:
        from_attributes = True


class SAEBatchCreateResponse(BaseModel):
    students: List[SAEStudentRow]
    total_created: int


class SAETokenValidationResponse(BaseModel):
    valid: bool
    student_code: str
    display_name: str


class SAESetupResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    student_code: str
    display_name: str


class SAESubmissionResult(BaseModel):
    """Student-facing submission result. Contains the effective (possibly edited) grading."""
    id: UUID
    score: Optional[int]
    overall_confidence: Optional[str]
    review_required: bool
    result_json: Optional[dict]
    submitted_by_publisher: bool
    created_at: datetime
    handwritten_filename: Optional[str] = None
    webassign_filename: Optional[str] = None

    class Config:
        from_attributes = True


class SAESubmissionResultPublisher(SAESubmissionResult):
    """Publisher-facing submission result. Extends the base result with edit metadata."""
    is_edited: bool
    last_edited_at: Optional[datetime]


class SAEStudentDetail(BaseModel):
    id: UUID
    student_number: int
    student_code: str
    display_name: str
    invitation_url: str
    invitation_token: str
    is_activated: bool
    activated_at: Optional[datetime]
    has_submitted: bool
    submitted_at: Optional[datetime]
    submission: Optional[SAESubmissionResultPublisher]

    class Config:
        from_attributes = True


class SAEStudentMe(BaseModel):
    id: UUID
    student_number: int
    student_code: str
    display_name: str
    is_activated: bool
    has_submitted: bool

    class Config:
        from_attributes = True
