from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field


# ── Request schemas ────────────────────────────────────────────────────────────

class SAEAssessmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200,
                      description="e.g. 'Fall 2025 Placement Test'")
    description: Optional[str] = Field(None, max_length=2000)
    course_id: Optional[UUID] = Field(
        None,
        description="Link to an existing course. Omit for a standalone assessment."
    )


class SAEBatchCreateRequest(BaseModel):
    assessment_id: UUID = Field(..., description="The assessment to add students to")
    count: int = Field(..., ge=1, le=500,
                       description="How many student slots to generate")
    expires_days: Optional[int] = Field(
        None, ge=1, le=365,
        description="Days until invitation links expire. Omit for no expiry."
    )


class SAEInviteSetupRequest(BaseModel):
    """
    Used for both first-use (account creation) and second-use (credential change).
    Which fields are required depends on the token's use_count, enforced in the service:
      - First use:  username, password, country_of_origin, curriculum all required.
      - Second use: at least one of username / password required; education fields ignored.
    """
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    password: Optional[str] = Field(None, min_length=8)
    country_of_origin: Optional[str] = Field(None, min_length=1, max_length=100)
    curriculum: Optional[str] = Field(None, min_length=1, max_length=200)


class SAEQuestionEdit(BaseModel):
    id: str
    score: Optional[float] = None
    feedback: Optional[str] = None


class SAESubmissionEditRequest(BaseModel):
    overall_feedback: Optional[str] = None
    questions: Optional[List[SAEQuestionEdit]] = None


# ── Response schemas ───────────────────────────────────────────────────────────

class SAEAssessmentRow(BaseModel):
    id: UUID
    publisher_id: UUID
    course_id: Optional[UUID]
    name: str
    description: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class SAEStudentRow(BaseModel):
    id: UUID
    assessment_id: UUID
    student_number: int
    student_code: str
    display_name: str
    invitation_url: str
    invitation_token: str
    is_activated: bool
    activated_at: Optional[datetime]
    submission_count: int
    submitted_at: Optional[datetime]
    country_of_origin: Optional[str] = None
    curriculum: Optional[str] = None

    class Config:
        from_attributes = True


class SAEBatchCreateResponse(BaseModel):
    students: List[SAEStudentRow]
    total_created: int


class SAETokenValidationResponse(BaseModel):
    valid: bool
    student_code: str
    display_name: str
    is_first_use: bool  # False on second use — frontend shows credential-change form only


class SAESetupResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    student_code: str
    display_name: str


class SAESubmissionResult(BaseModel):
    """Student-facing submission result. Contains the effective (possibly edited) grading."""
    id: UUID
    submission_number: Optional[int] = None
    is_active: Optional[bool] = None
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
    submitted_at: Optional[datetime]
    submission_count: int
    submissions: List[SAESubmissionResultPublisher]

    class Config:
        from_attributes = True


class SAERegenerateResponse(BaseModel):
    invitation_url: str
    invitation_token: str


class SAEStudentMe(BaseModel):
    """
    Returned by GET /api/sae/student/me for any authenticated subscriber.
    is_enrolled=False means this user is a regular subscriber not in the SAE system;
    all other fields will be None in that case.
    """
    is_enrolled: bool
    id: Optional[UUID] = None
    student_number: Optional[int] = None
    student_code: Optional[str] = None
    display_name: Optional[str] = None
    is_activated: Optional[bool] = None
    submission_count: Optional[int] = None
    country_of_origin: Optional[str] = None
    curriculum: Optional[str] = None

    class Config:
        from_attributes = True
