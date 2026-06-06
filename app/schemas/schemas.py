from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Any
from pydantic import BaseModel, Field, EmailStr
import uuid
from uuid import UUID
from enum import Enum


class SlideData(BaseModel):
    id: int
    slideNumber: int
    title: Optional[str] = None
    content: Optional[str] = None
    imagePath: Optional[str] = None
    thumbnailPath: Optional[str] = None
    visionInstructions: Optional[str] = None
    visionModel: Optional[str] = None


class PresentationData(BaseModel):
    filename: str
    filePath: str
    fileSize: int
    fileType: str


class EphemeralTokenResponse(BaseModel):
    client_secret: dict


class InputAudioNoiseReduction(BaseModel):
    type: str


class InputAudioTranscription(BaseModel):
    language: str
    model: str


class TurnDetection(BaseModel):
    type: str
    threshold: float | None = None
    silence_duration_ms: int | None = None
    prefix_padding_ms: int | None = None
    suffix_padding_ms: int | None = None
    eagerness: str | None = None


class ToolFunctionParameter(BaseModel):
    type: str
    properties: dict
    required: list
    additionalProperties: bool | None = None


class ToolFunction(BaseModel):
    name: str
    description: str
    parameters: Optional[ToolFunctionParameter] = None


class Tool(BaseModel):
    type: str
    function: Optional[ToolFunction] = None


class AssistantParameters(BaseModel):
    input_audio_format: str
    input_audio_noise_reduction: Optional[InputAudioNoiseReduction] = None
    input_audio_transcription: Optional[InputAudioTranscription] = None
    instructions: str
    model: str
    output_audio_format: str
    temperature: float
    tool_choice: str
    tools: list
    turn_detection: Optional[TurnDetection] = None
    voice: str


class SessionDetails(BaseModel):
    sessionId: str
    userId: str
    username: str
    presentationDetails: PresentationData
    slidesDetails: List[SlideData]
    courseId: str = Field(..., description="Course ID that this session belongs to")
    courseName: str = Field(..., min_length=1, max_length=200)
    className: str = Field(..., min_length=1, max_length=200)
    courseCode: str = Field(..., min_length=1, max_length=50)
    sessionNumber: Optional[int] = None
    sessionDate: Optional[datetime] = None
    description: Optional[str] = None
    duration: int = Field(..., gt=0, le=480)  # Max 8 hours
    assistantParameters: Optional[AssistantParameters] = None


class SessionCreateRequest(BaseModel):
    courseId: str = Field(..., description="Course ID that this session belongs to")
    sessionNumber: Optional[int] = None
    sessionDate: Optional[datetime] = None
    className: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    duration: int = Field(..., gt=0, le=480)  # Max 8 hours
    visionInstructions: Optional[str] = None
    visionModel: Optional[str] = None


class SessionUpdateDetails(BaseModel):
    # courseName: str = Field(..., min_length=1, max_length=200)
    # className: str = Field(..., min_length=1, max_length=200)
    # courseCode: str = Field(..., min_length=1, max_length=50)
    # description: Optional[str] = None
    # duration: int = Field(..., gt=0, le=480)  # Max 8 hours
    assistantParameters: Optional[AssistantParameters] = None


class SessionRunDetails(BaseModel):
    sessionRunId: str
    sessionId: str
    userId: str
    username: str
    sessionRunMetadata: Optional[dict] = None
    assistantParameters: AssistantParameters
    status: str

    courseName: str
    className: str
    courseCode: str
    description: str
    duration: int
    presentationDetails: PresentationData
    slidesDetails: List[SlideData]

    startTime: datetime
    endTime: Optional[datetime] = None


# Authentication Schemas
class UserRegistration(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)
    firstName: str = Field(..., min_length=1, max_length=100)
    lastName: str = Field(..., min_length=1, max_length=100)
    role: str = Field(..., min_length=1, max_length=100)


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    firstName: str
    lastName: str
    role: str
    createdAt: datetime


class AuthResponse(BaseModel):
    success: bool
    user: Optional[UserResponse] = None
    token: Optional[str] = None
    expiresAt: Optional[datetime] = None
    message: Optional[str] = None


class TokenVerifyResponse(BaseModel):
    success: bool
    user: Optional[UserResponse] = None
    expiresAt: Optional[datetime] = None
    message: Optional[str] = None


class RefreshTokenResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    expiresAt: Optional[datetime] = None


class LogoutResponse(BaseModel):
    success: bool
    message: str


class UserProfileUpdate(BaseModel):
    firstName: Optional[str] = Field(None, min_length=1, max_length=100)
    lastName: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None


class UserSessionSummary(BaseModel):
    sessionId: str
    className: str
    courseName: str
    courseCode: str
    createdAt: datetime
    slidesCount: int
    duration: int


class UserSessionsResponse(BaseModel):
    sessions: List[UserSessionSummary]


# New schemas for GET /api/sessions endpoint
class ClassDetails(BaseModel):
    className: str
    courseName: str
    courseCode: str
    description: Optional[str] = None
    duration: int


class SessionSummary(BaseModel):
    sessionId: str
    classDetails: ClassDetails
    status: str
    totalSlides: int
    createdAt: datetime
    updatedAt: datetime
    lastAccessedAt: Optional[datetime] = None
    runCount: int
    lastRunAt: Optional[datetime] = None


class PaginationInfo(BaseModel):
    page: int
    limit: int
    total: int
    totalPages: int


class SessionsListResponse(BaseModel):
    sessions: List[SessionSummary]
    pagination: PaginationInfo


# New schemas for GET /api/sessions/{sessionId}/runs endpoint
class SessionRunFeedback(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5)
    general_feedback: Optional[str] = None
    issues_encountered: Optional[str] = None
    suggestions: Optional[str] = None


class SessionRunSummary(BaseModel):
    sessionRunId: str
    sessionId: str
    status: str
    startedAt: datetime
    endedAt: Optional[datetime] = None
    duration: Optional[int] = None  # Duration in minutes
    feedback: Optional[SessionRunFeedback] = None
    slidesCompleted: Optional[int] = None
    totalSlides: int


class SessionRunsListResponse(BaseModel):
    runs: List[SessionRunSummary]
    total: int


class SavedPrompt(BaseModel):
    model_config = {"from_attributes": True}
    id: Optional[UUID] = None
    name: str
    description: str
    content: str
    category: str
    tags: str
    is_default: bool = False
    is_public: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    usage_count: int = 0
    user_id: Optional[UUID] = None  # None for default prompts


class PromptsResponse(BaseModel):
    prompts: List[SavedPrompt]  # User's custom prompts
    default_prompts: List[SavedPrompt]  # System default prompts
    pagination: PaginationInfo


class SavedPromptCreate(BaseModel):
    name: str
    description: str
    content: str
    category: str
    tags: str
    is_default: bool = False
    is_public: bool = False
    user_id: Optional[UUID] = None  # None for default prompts


class SavedPromptUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    is_default: Optional[bool] = None
    is_public: Optional[bool] = None
    user_id: Optional[UUID] = None  # None for default prompts


class CourseDetails(BaseModel):
    id: Optional[UUID] = None
    course_id: str
    user_id: Optional[UUID] = None
    username: Optional[str] = None
    owner_name: Optional[str] = None
    enrollment_count: Optional[int] = None
    name: Optional[str] = None
    code: Optional[str] = None
    section: Optional[str] = None
    description: Optional[str] = None
    department: Optional[str] = None
    semester: Optional[str] = None
    year: Optional[int] = None
    syllabus_details: Optional[dict] = None
    is_active: Optional[bool] = None
    is_deleted: Optional[bool] = None
    is_public: Optional[bool] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CourseCreate(BaseModel):
    user_id: Optional[UUID] = None
    name: Optional[str] = None
    code: Optional[str] = None
    section: Optional[str] = None
    description: Optional[str] = None
    department: Optional[str] = None
    semester: Optional[str] = None
    year: Optional[int] = None
    syllabus_details: Optional[dict] = None
    is_active: Optional[bool] = None
    is_deleted: Optional[bool] = None
    is_public: Optional[bool] = None


class CourseUpdate(BaseModel):
    user_id: Optional[UUID] = None
    name: Optional[str] = None
    code: Optional[str] = None
    section: Optional[str] = None
    description: Optional[str] = None
    department: Optional[str] = None
    semester: Optional[str] = None
    year: Optional[int] = None
    syllabus_details: Optional[dict] = None
    is_active: Optional[bool] = None
    is_deleted: Optional[bool] = None
    is_public: Optional[bool] = None


class CourseEnrollment(BaseModel):
    email: str = Field(..., description="Email of the student to enroll")


class CourseStudent(BaseModel):
    id: UUID
    username: str
    email: str
    firstName: str
    lastName: str
    enrollment_date: datetime


class CourseWithStudents(BaseModel):
    course: CourseDetails
    students: List[CourseStudent]


class CourseSessionSummary(BaseModel):
    sessionId: str
    session_number: Optional[int] = None
    session_date: Optional[datetime] = None
    class_name: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[int] = None
    created_at: datetime
    updated_at: datetime


# Course Materials Schemas
class MaterialType(str, Enum):
    BOOK = "book"
    ARTICLE = "article"
    VIDEO = "video"
    DOCUMENT = "document"
    LINK = "link"
    OTHER = "other"


class CourseMaterialBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    material_type: MaterialType
    url: Optional[str] = Field(None, max_length=500)
    author: Optional[str] = Field(None, max_length=255)
    publication_year: Optional[int] = Field(None, ge=1800, le=2030)
    publisher: Optional[str] = Field(None, max_length=255)
    isbn: Optional[str] = Field(None, max_length=20)
    doi: Optional[str] = Field(None, max_length=100)
    additional_info: Optional[dict] = None
    is_required: bool = True
    is_active: bool = True


class CourseMaterialCreate(CourseMaterialBase):
    course_id: str


class CourseMaterialUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    material_type: Optional[MaterialType] = None
    url: Optional[str] = Field(None, max_length=500)
    author: Optional[str] = Field(None, max_length=255)
    publication_year: Optional[int] = Field(None, ge=1800, le=2030)
    publisher: Optional[str] = Field(None, max_length=255)
    isbn: Optional[str] = Field(None, max_length=20)
    doi: Optional[str] = Field(None, max_length=100)
    additional_info: Optional[dict] = None
    is_required: Optional[bool] = None
    is_active: Optional[bool] = None


class CourseMaterialResponse(CourseMaterialBase):
    id: UUID
    course_id: str
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    rag_status: Optional[str] = None   # pending|processing|complete|failed
    rag_error: Optional[str] = None
    rag_chunks: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CourseMaterialsListResponse(BaseModel):
    materials: List[CourseMaterialResponse]
    total: int


# Session Materials Schemas
class SessionMaterialBase(BaseModel):
    is_included: bool = True
    usage_instructions: Optional[str] = None


class SessionMaterialCreate(SessionMaterialBase):
    session_id: str
    course_material_id: UUID


class SessionMaterialUpdate(BaseModel):
    is_included: Optional[bool] = None
    usage_instructions: Optional[str] = None


class SessionMaterialResponse(SessionMaterialBase):
    id: UUID
    session_id: str
    course_material_id: UUID
    course_material: CourseMaterialResponse
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SessionMaterialsListResponse(BaseModel):
    session_materials: List[SessionMaterialResponse]
    total: int


# File Upload Schema
class FileUploadResponse(BaseModel):
    success: bool
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    message: Optional[str] = None


# ─── Billing Schemas ───────────────────────────────────────────────────────────


class BalanceResponse(BaseModel):
    source: str  # "access_code" | "purchased" | "none"
    balance: Decimal
    access_code: Optional[str] = None
    issued_by: Optional[str] = None


class RedeemCodeRequest(BaseModel):
    code: str = Field(..., min_length=1)


class RedeemCodeResponse(BaseModel):
    success: bool
    credits_available: Decimal
    code: str
    issued_by: str
    message: str


class AddCreditsRequest(BaseModel):
    amount_usd: Decimal = Field(
        ..., gt=0, description="Amount in USD to convert to credits"
    )


class AddCreditsResponse(BaseModel):
    success: bool
    credits_added: Decimal
    new_balance: Decimal
    message: str


class UsageRecordResponse(BaseModel):
    id: UUID
    operation_type: str
    input_tokens: int
    output_tokens: int
    raw_cost_usd: Decimal
    platform_fee_usd: Decimal
    total_cost_usd: Decimal
    credits_charged: Decimal
    funded_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class UsageHistoryResponse(BaseModel):
    records: List[UsageRecordResponse]
    total: int
    pagination: PaginationInfo


class PricingConfigResponse(BaseModel):
    id: UUID
    operation_type: str
    cost_per_1k_input_tokens: Decimal
    cost_per_1k_output_tokens: Decimal
    platform_fee_multiplier: Decimal
    minimum_charge_credits: Decimal
    updated_at: datetime

    class Config:
        from_attributes = True


class PricingConfigUpdate(BaseModel):
    cost_per_1k_input_tokens: Optional[Decimal] = None
    cost_per_1k_output_tokens: Optional[Decimal] = None
    platform_fee_multiplier: Optional[Decimal] = Field(None, ge=1.0)
    minimum_charge_credits: Optional[Decimal] = None


class AccessCodeCreateRequest(BaseModel):
    issued_by: str = Field(..., min_length=1)
    total_credits: Decimal = Field(..., gt=0)
    max_redemptions: int = Field(1, ge=1)
    expires_at: Optional[datetime] = None
    code: Optional[str] = None  # Auto-generated when omitted


class AccessCodeResponse(BaseModel):
    id: UUID
    code: str
    total_credits: Decimal
    remaining_credits: Decimal
    issued_by: str
    max_redemptions: int
    redemptions_used: int
    expires_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AccessCodesListResponse(BaseModel):
    codes: List[AccessCodeResponse]
    total: int
