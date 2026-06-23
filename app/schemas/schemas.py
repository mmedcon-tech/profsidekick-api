from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field, EmailStr, field_validator
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
    source: Optional[str] = None  # "student" | "solution" — solution slides are never rendered in the UI

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
    courseName: Optional[str] = None
    className: Optional[str] = None
    courseCode: Optional[str] = None
    sessionNumber: Optional[int] = None
    sessionDate: Optional[datetime] = None
    description: Optional[str] = None
    duration: int = Field(..., gt=0, le=480)  # Max 8 hours
    assistantParameters: Optional[AssistantParameters] = None
    sessionMode: Optional[str] = "teaching"   # 'teaching' | 'examination'
    subscriberRuntimeMode: Optional[str] = "avatar"  # 'avatar' | 'chat' | 'choice'

class SessionCreateRequest(BaseModel):
    courseId: str = Field(..., description="Course ID that this session belongs to")
    sessionNumber: Optional[int] = None
    sessionDate: Optional[datetime] = None
    className: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    duration: int = Field(..., gt=0, le=480)  # Max 8 hours
    visionInstructions: Optional[str] = None
    visionModel: Optional[str] = None
    # Role selection at session creation
    selectedRoleId: Optional[UUID] = None
    roleLabel: Optional[str] = None
    # Session mode: determines which template prompt is loaded
    sessionMode: Optional[str] = Field("teaching", pattern="^(teaching|examination)$")
    # Subscriber runtime mode: determines what experience subscribers get
    subscriberRuntimeMode: Optional[str] = Field("avatar", pattern="^(avatar|chat|choice)$")

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

    courseId: Optional[str] = None
    courseName: Optional[str] = None
    className: Optional[str] = None
    courseCode: Optional[str] = None
    description: Optional[str] = None
    duration: int
    presentationDetails: PresentationData
    slidesDetails: List[SlideData]

    startTime: datetime
    endTime: Optional[datetime] = None
    runtimeModeUsed: Optional[str] = None  # 'avatar' | 'chat'

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
    courseId: Optional[str] = None   # the course_id slug used in URLs (e.g. "crs_abc123")
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
    sessionMode: Optional[str] = "teaching"   # 'teaching' | 'examination'
    avatarId: Optional[str] = None
    selectedRoleId: Optional[str] = None
    roleLabel: Optional[str] = None

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
    avatarId: Optional[str] = None
    avatarName: Optional[str] = None
    roleAtStart: Optional[str] = None
    sessionMode: Optional[str] = None
    className: Optional[str] = None

class SessionRunsListResponse(BaseModel):
    runs: List[SessionRunSummary]
    total: int

class SavedPrompt(BaseModel):
    model_config = {
        "from_attributes": True
    }
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
    session_count: Optional[int] = None
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
    allow_subscriber_sessions: Optional[bool] = None
    enrolled: Optional[bool] = None   # subscriber-only: True if caller is enrolled
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
    allow_subscriber_sessions: Optional[bool] = False
    program_id: Optional[UUID] = None

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
    allow_subscriber_sessions: Optional[bool] = None

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

# Realtime Feedback Schemas
class FeedbackAnalysisRequest(BaseModel):
    question: str
    response: str
    slide_number: Optional[int] = None

class FeedbackCardResponse(BaseModel):
    severity: str  # "green" | "amber" | "red"
    observation: str
    keywords: List[str]
    turn_number: Optional[int] = None


# ═══════════════════════════════════════════════════════════════════
# Avatar layer — prompts live ONLY in AvatarTemplate (admin-owned).
# Avatar, AvatarConfiguration, and Session contain NO prompt fields.
# ═══════════════════════════════════════════════════════════════════

# ── Avatar Template Version ───────────────────────────────────────

class AvatarTemplateVersionCreate(BaseModel):
    conversation_prompt: Optional[str] = None       # LEGACY — kept for backward compat
    teaching_prompt: Optional[str] = None           # Used when session_mode = 'teaching'
    examination_prompt: Optional[str] = None        # Used when session_mode = 'examination'
    document_analysis_prompt: Optional[str] = None
    change_notes: Optional[str] = None

class AvatarTemplateVersionResponse(BaseModel):
    id: UUID
    template_id: UUID
    version_number: int
    conversation_prompt: Optional[str] = None       # LEGACY
    teaching_prompt: Optional[str] = None
    examination_prompt: Optional[str] = None
    document_analysis_prompt: Optional[str] = None
    status: str  # draft | published | archived
    change_notes: Optional[str] = None
    created_by: UUID
    created_at: datetime
    published_at: Optional[datetime] = None
    published_by: Optional[UUID] = None

    class Config:
        from_attributes = True

# ── Avatar Template Role ──────────────────────────────────────────

class AvatarTemplateRoleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    prompt_context: Optional[str] = None

class AvatarTemplateRoleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    prompt_context: Optional[str] = None
    is_enabled: Optional[bool] = None
    sort_order: Optional[int] = None

class AvatarTemplateRoleResponse(BaseModel):
    id: UUID
    template_id: UUID
    name: str
    description: Optional[str] = None
    prompt_context: Optional[str] = None
    is_enabled: bool
    sort_order: int
    # W2A additions — HeyGen overrides and 3-D model suggestion
    heygen_avatar_id: Optional[str] = None
    heygen_voice_id: Optional[str] = None
    default_language: Optional[str] = None
    suggested_3d_model_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class RoleReorderRequest(BaseModel):
    role_ids: List[UUID]  # ordered list — first element gets sort_order 0

# ── Avatar Template ──────────────────────────────────────────

class AvatarTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    subscription_cost: Optional[Decimal] = Decimal("3")

class AvatarTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None

class AvatarTemplatePricingUpdate(BaseModel):
    subscription_cost: Decimal = Field(..., ge=0)

class AvatarTemplateResponse(BaseModel):
    """Full admin-only response — includes current version prompts."""
    id: UUID
    created_by: UUID
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    is_active: bool
    subscription_cost: Decimal = Decimal("3")
    avatar_image_url: Optional[str] = None
    current_version_id: Optional[UUID] = None
    current_version: Optional[AvatarTemplateVersionResponse] = None
    published_state: str  # "unpublished" | "draft" | "published"
    version_count: int = 0
    roles: List[AvatarTemplateRoleResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AvatarTemplateSummary(BaseModel):
    """Prompt-free — safe for publisher template browsing."""
    id: UUID
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    is_active: bool
    subscription_cost: Optional[Decimal] = None
    published_state: str = "unpublished"
    avatar_image_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AvatarTemplateDetailResponse(AvatarTemplateResponse):
    """Extended detail view — includes full version history."""
    versions: List[AvatarTemplateVersionResponse] = []

# ── Rubric ───────────────────────────────────────────────────────

class RubricCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: dict

class RubricResponse(BaseModel):
    id: UUID
    avatar_configuration_id: UUID
    title: str
    content: dict
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ── Knowledge Document ───────────────────────────────────────────

class KnowledgeDocumentResponse(BaseModel):
    id: UUID
    avatar_configuration_id: UUID
    title: str
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    content_text: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ── Reference Solution ───────────────────────────────────────────

class ReferenceSolutionResponse(BaseModel):
    id: UUID
    avatar_configuration_id: UUID
    title: str
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    content_text: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ── Avatar Configuration ─────────────────────────────────────────

class AvatarConfigurationCreate(BaseModel):
    voice: Optional[str] = Field(None, max_length=100)
    language: Optional[str] = Field(None, max_length=50)
    difficulty_level: Optional[str] = Field(None, max_length=50)
    additional_settings: Optional[dict] = None

class AvatarConfigurationUpdate(BaseModel):
    voice: Optional[str] = Field(None, max_length=100)
    language: Optional[str] = Field(None, max_length=50)
    difficulty_level: Optional[str] = Field(None, max_length=50)
    additional_settings: Optional[dict] = None

class AvatarConfigurationResponse(BaseModel):
    id: UUID
    avatar_id: UUID
    voice: Optional[str] = None
    language: Optional[str] = None
    difficulty_level: Optional[str] = None
    additional_settings: Optional[dict] = None
    rubrics: List[RubricResponse] = []
    knowledge_documents: List[KnowledgeDocumentResponse] = []
    reference_solutions: List[ReferenceSolutionResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ── Teaching Preferences ────────────────────────────────────────

VALID_TEACHING_PACE        = {"thorough", "balanced", "fast"}
VALID_QUESTIONING_STYLE    = {"socratic", "direct", "guided"}
VALID_FORMALITY_LEVEL      = {"casual", "balanced", "formal"}
VALID_DEPTH_LEVEL          = {"surface", "standard", "deep"}
VALID_ENCOURAGEMENT_LEVEL  = {"high", "neutral", "minimal"}
VALID_LANGUAGE_LEVEL       = {"introductory", "intermediate", "advanced", "adaptive"}


class TeachingPreferences(BaseModel):
    teaching_pace:       Optional[str] = Field(None, description="thorough | balanced | fast")
    questioning_style:   Optional[str] = Field(None, description="socratic | direct | guided")
    formality_level:     Optional[str] = Field(None, description="casual | balanced | formal")
    depth_level:         Optional[str] = Field(None, description="surface | standard | deep")
    encouragement_level: Optional[str] = Field(None, description="high | neutral | minimal")
    language_level:      Optional[str] = Field(None, description="introductory | intermediate | advanced | adaptive")


class PublisherAvatarProfileResponse(BaseModel):
    id: UUID
    publisher_avatar_id: UUID
    teaching_pace:       Optional[str] = None
    questioning_style:   Optional[str] = None
    formality_level:     Optional[str] = None
    depth_level:         Optional[str] = None
    encouragement_level: Optional[str] = None
    language_level:      Optional[str] = None
    refined_prompt:      Optional[str] = None
    post_session_quiz_enabled: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProfileRefineRequest(BaseModel):
    teaching_preferences: TeachingPreferences
    additional_context: Optional[str] = Field(
        None, max_length=1000, description="Optional freeform context the publisher wants included in the persona."
    )


# ── Avatar ───────────────────────────────────────────────────────

class AvatarCreate(BaseModel):
    template_id: UUID
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    teaching_preferences: Optional[TeachingPreferences] = None
    program_id: Optional[UUID] = None

class AvatarUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None

class AvatarSummary(BaseModel):
    """List response — includes profile but no heavy configuration payload."""
    id: UUID
    template_id: UUID
    publisher_id: UUID
    name: str
    description: Optional[str] = None
    is_published: bool
    subscription_cost: Optional[Decimal] = None
    template_image_url: Optional[str] = None   # inherited from AvatarTemplate.avatar_image_path
    template_name: Optional[str] = None        # inherited from AvatarTemplate.name
    profile: Optional[PublisherAvatarProfileResponse] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AvatarPricingUpdate(BaseModel):
    subscription_cost: Decimal = Field(..., ge=0)

class AvatarResponse(BaseModel):
    """Single-avatar detail — includes configuration and profile."""
    id: UUID
    template_id: UUID
    publisher_id: UUID
    name: str
    description: Optional[str] = None
    is_published: bool
    subscription_cost: Optional[Decimal] = None
    template_image_url: Optional[str] = None   # inherited from AvatarTemplate.avatar_image_path
    template_name: Optional[str] = None        # inherited from AvatarTemplate.name
    configuration: Optional[AvatarConfigurationResponse] = None
    profile: Optional[PublisherAvatarProfileResponse] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AvatarPublicResponse(BaseModel):
    """Subscriber-facing — no configuration, no template metadata."""
    id: UUID
    name: str
    description: Optional[str] = None
    is_published: bool
    subscription_cost: Optional[Decimal] = None
    template_image_url: Optional[str] = None   # inherited from AvatarTemplate.avatar_image_path
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AvatarListResponse(BaseModel):
    avatars: List[AvatarSummary]
    total: int

class AvatarPublicListResponse(BaseModel):
    avatars: List[AvatarPublicResponse]
    total: int


# ═══════════════════════════════════════════════════════════════════
# Publisher Learning System schemas
# ═══════════════════════════════════════════════════════════════════

# ── Chat ─────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    conversation_id: Optional[UUID] = None
    avatar_id: Optional[UUID] = None
    session_id: Optional[str] = None   # string slug e.g. "sess_abc123"; loads slide content
    message: str = Field(..., min_length=1, max_length=8000)
    preferences: Optional[dict] = None
    selected_content: Optional[str] = None

class ChatOptionsRequest(BaseModel):
    conversation_id: Optional[UUID] = None
    avatar_id: Optional[UUID] = None
    session_id: Optional[str] = None
    message: str = Field(..., min_length=1, max_length=8000)
    n: int = Field(3, ge=1, le=5)
    preferences: Optional[dict] = None

class ResponseOption(BaseModel):
    option_id: str   # "A", "B", "C", ...
    content: str

class ChatOptionsResponse(BaseModel):
    conversation_id: UUID  # pre-created so frontend can reference it
    options: List[ResponseOption]

class ChatSelectRequest(BaseModel):
    """Commit a chosen option to conversation history and record feedback."""
    conversation_id: UUID
    avatar_id: Optional[UUID] = None
    user_message: str
    selected_response: str
    rejected_responses: List[str] = Field(default_factory=list)
    feedback_notes: Optional[str] = None

class ChatSelectResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    feedback_id: UUID
    created_at: datetime

class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    reply: str
    turn_number: int
    created_at: datetime

class MessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True

class ConversationSummary(BaseModel):
    id: UUID
    avatar_id: Optional[UUID] = None
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ConversationDetail(BaseModel):
    id: UUID
    avatar_id: Optional[UUID] = None
    title: str
    messages: List[MessageResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ConversationListResponse(BaseModel):
    conversations: List[ConversationSummary]
    total: int

# ── Feedback ──────────────────────────────────────────────────────

class FeedbackCreate(BaseModel):
    avatar_id: Optional[UUID] = None
    prompt: str = Field(..., min_length=1)
    selected_response: str = Field(..., min_length=1)
    rejected_responses: List[str] = Field(default_factory=list)
    feedback_notes: Optional[str] = None

class FeedbackResponse(BaseModel):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

# ── Preferences ───────────────────────────────────────────────────

class PreferenceUpsert(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    value: Any

class PreferenceResponse(BaseModel):
    publisher_id: UUID
    key: str
    value: Any
    updated_at: datetime

    class Config:
        from_attributes = True

class PreferenceListResponse(BaseModel):
    preferences: List[PreferenceResponse]


# ── Chat Start (AI-initiated opening) ─────────────────────────────

class ChatStartRequest(BaseModel):
    """
    Start a new conversation with an AI-generated opening message.
    The backend assembles the full system prompt and calls the LLM
    with no user turn, so the AI speaks first.
    """
    avatar_id: Optional[UUID] = None
    session_id: Optional[str] = None
    preferences: Optional[dict] = None   # e.g. selected_role

class ChatStartResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    opening_message: str
    created_at: datetime


# ── Per-message feedback ──────────────────────────────────────────

# ── Template Image ────────────────────────────────────────────────

class TemplateImageResponse(BaseModel):
    id: UUID
    avatar_image_url: Optional[str] = None


# ── Admin Template Dashboard Stats ───────────────────────────────

class TemplateDashboardStats(BaseModel):
    template_id: UUID
    name: str
    avatar_image_url: Optional[str] = None
    published_state: str
    version_count: int
    publisher_count: int   # number of publishers who created avatars from this template
    course_count: int      # distinct courses with sessions using these avatars
    session_count: int     # total sessions
    session_run_count: int # total session runs

class TemplatePublisherRow(BaseModel):
    publisher_id: UUID
    username: str
    email: str
    avatar_id: UUID
    avatar_name: str
    is_published: bool
    created_at: datetime

class TemplateCourseRow(BaseModel):
    course_id: str
    name: Optional[str] = None
    code: Optional[str] = None
    publisher_username: str
    session_count: int
    is_active: bool

class TemplateSessionRunRow(BaseModel):
    run_id: UUID
    session_id: str
    session_name: Optional[str] = None
    publisher_username: str
    status: str
    start_time: datetime
    end_time: Optional[datetime] = None
    role_at_start: Optional[str] = None


# ── Per-message feedback (kept for backward compat during migration) ──────────
# These schemas are deprecated; new edits use ResponseEditCreate / ResponseEditResponse.

class MessageFeedbackCreate(BaseModel):
    rating: Optional[str] = Field(None, pattern="^(good|needs_improvement)$")
    comment: Optional[str] = Field(None, max_length=2000)
    avatar_id: Optional[UUID] = None

class MessageFeedbackResponse(BaseModel):
    id: UUID
    message_id: UUID
    rating: Optional[str] = None
    comment: Optional[str] = None


# ── Editable AI Responses (publisher_refinement) ──────────────────

class ResponseEditCreate(BaseModel):
    edited_content: str = Field(..., min_length=1, max_length=16000)
    original_content: str = Field(..., min_length=1, max_length=16000)
    avatar_id: Optional[UUID] = None
    session_id: Optional[str] = None

class ResponseEditResponse(BaseModel):
    id: UUID
    message_id: UUID
    original_content: str
    edited_content: str
    edit_type: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Avatar Subscriptions ───────────────────────────────────────────

class SubscriptionResponse(BaseModel):
    id: UUID
    subscriber_id: UUID
    avatar_id: UUID
    subscribed_at: datetime
    is_active: bool = True
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SubscriptionListResponse(BaseModel):
    subscriptions: List[SubscriptionResponse]
    total: int


class SubscriptionStatusResponse(BaseModel):
    subscribed: bool
    subscription: Optional[SubscriptionResponse] = None


# ═══════════════════════════════════════════════════════════════════
# Billing & Credits Schemas
# ═══════════════════════════════════════════════════════════════════

from decimal import Decimal


class BalanceResponse(BaseModel):
    source: str          # "access_code" | "purchased" | "none"
    balance: Decimal
    access_code: Optional[str] = None
    issued_by: Optional[str] = None


class RedeemCodeRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)


class RedeemCodeResponse(BaseModel):
    success: bool
    credits_available: Decimal
    code: str
    issued_by: Optional[str] = None
    message: str


class AddCreditsRequest(BaseModel):
    amount_usd: Decimal = Field(..., gt=0)


class AddCreditsResponse(BaseModel):
    success: bool
    credits_added: Decimal
    new_balance: Decimal
    message: str


class UsageRecordResponse(BaseModel):
    id: UUID
    user_id: UUID
    session_run_id: Optional[UUID] = None
    operation_type: str
    input_tokens: int
    output_tokens: int
    raw_cost_usd: Decimal
    platform_fee_usd: Decimal
    total_cost_usd: Decimal
    credits_charged: Decimal
    funded_by: str
    access_code_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UsageHistoryResponse(BaseModel):
    records: List[UsageRecordResponse]
    total: int
    pagination: PaginationInfo


# ── Admin billing ─────────────────────────────────────────────────

class AccessCodeCreateRequest(BaseModel):
    issued_by: str = Field(..., min_length=1, max_length=255)
    total_credits: Decimal = Field(..., gt=0)
    max_redemptions: int = Field(1, ge=1)
    expires_at: Optional[datetime] = None
    code: Optional[str] = Field(None, min_length=1, max_length=50)


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
    updated_at: datetime

    class Config:
        from_attributes = True


class AccessCodesListResponse(BaseModel):
    codes: List[AccessCodeResponse]
    total: int


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
    platform_fee_multiplier: Optional[Decimal] = None
    minimum_charge_credits: Optional[Decimal] = None


class AdminAdjustBalanceRequest(BaseModel):
    delta_credits: Decimal  # positive = grant, negative = deduct
    reason: str = Field(..., min_length=1, max_length=500)


class AdminAdjustBalanceResponse(BaseModel):
    previous_balance: Decimal
    new_balance: Decimal
    delta_credits: Decimal
    reason: str


# ═══════════════════════════════════════════════════════════════════
# Course Access Code (enrollment) Schemas
# ═══════════════════════════════════════════════════════════════════

class CourseAccessCodeCreate(BaseModel):
    max_uses: Optional[int] = Field(None, ge=1)
    expires_at: Optional[datetime] = None


class CourseAccessCodeResponse(BaseModel):
    id: UUID
    course_id: UUID
    code: str
    created_by: UUID
    max_uses: Optional[int] = None
    uses_count: int
    is_active: bool
    expires_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CourseAccessCodesListResponse(BaseModel):
    codes: List[CourseAccessCodeResponse]
    total: int


class CourseJoinRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)


class CourseJoinResponse(BaseModel):
    course_id: str
    course_name: Optional[str] = None
    message: str


# ═══════════════════════════════════════════════════════════════════
# Subscriber Chat Schemas
# ═══════════════════════════════════════════════════════════════════

class SubscriberChatMessageRequest(BaseModel):
    session_run_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=8000)


class SubscriberChatMessage(BaseModel):
    id: str
    role: str   # "user" | "assistant"
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class SubscriberChatHistoryResponse(BaseModel):
    session_run_id: str
    messages: List[SubscriberChatMessage]
    total: int


# ═══════════════════════════════════════════════════════════════════
# Wave 2A — 3-D Model Catalog & Avatar Variants
# ═══════════════════════════════════════════════════════════════════

class Avatar3DModelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    # Accept either the legacy DB column names or the frontend-friendly aliases
    file_path: Optional[str] = Field(None, max_length=500)
    preview_image_path: Optional[str] = Field(None, max_length=500)
    model_url: Optional[str] = Field(None, max_length=500)
    thumbnail_url: Optional[str] = Field(None, max_length=500)
    model_type: Optional[str] = Field(None, max_length=50)
    gender: Optional[str] = Field(None, max_length=20)
    supported_languages: Optional[List[str]] = None
    sort_order: Optional[int] = 0
    is_active: Optional[bool] = True

    def resolved_file_path(self) -> Optional[str]:
        return self.file_path or self.model_url

    def resolved_preview_image_path(self) -> Optional[str]:
        return self.preview_image_path or self.thumbnail_url


class Avatar3DModelUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    file_path: Optional[str] = Field(None, max_length=500)
    preview_image_path: Optional[str] = Field(None, max_length=500)
    model_url: Optional[str] = Field(None, max_length=500)
    thumbnail_url: Optional[str] = Field(None, max_length=500)
    model_type: Optional[str] = Field(None, max_length=50)
    gender: Optional[str] = Field(None, max_length=20)
    supported_languages: Optional[List[str]] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class Avatar3DModelResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    file_path: Optional[str] = None
    preview_image_path: Optional[str] = None
    model_type: Optional[str] = None
    gender: Optional[str] = None
    supported_languages: Optional[List[str]] = None
    sort_order: int = 0
    is_active: bool
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    @property
    def model_url(self) -> Optional[str]:
        return self.file_path

    @property
    def thumbnail_url(self) -> Optional[str]:
        return self.preview_image_path

    def model_dump(self, **kwargs) -> Dict[str, Any]:
        data = super().model_dump(**kwargs)
        data["model_url"] = self.file_path
        data["thumbnail_url"] = self.preview_image_path
        return data

    class Config:
        from_attributes = True


class Avatar3DModelsListResponse(BaseModel):
    models: List[Avatar3DModelResponse]
    total: int


class AvatarVariantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    model_3d_id: Optional[UUID] = None
    heygen_avatar_id: Optional[str] = Field(None, max_length=200)
    heygen_voice_id: Optional[str] = Field(None, max_length=200)
    language: Optional[str] = Field("en", max_length=50)
    is_default: bool = False
    sort_order: int = Field(0, ge=0)


class AvatarVariantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    model_3d_id: Optional[UUID] = None
    heygen_avatar_id: Optional[str] = Field(None, max_length=200)
    heygen_voice_id: Optional[str] = Field(None, max_length=200)
    language: Optional[str] = Field(None, max_length=50)
    is_default: Optional[bool] = None
    sort_order: Optional[int] = Field(None, ge=0)


class AvatarVariantResponse(BaseModel):
    id: UUID
    avatar_id: UUID
    name: str
    description: Optional[str] = None
    model_3d_id: Optional[UUID] = None
    heygen_avatar_id: Optional[str] = None
    heygen_voice_id: Optional[str] = None
    language: Optional[str] = None
    is_default: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AvatarVariantsListResponse(BaseModel):
    variants: List[AvatarVariantResponse]
    total: int


# ═══════════════════════════════════════════════════════════════════
# Wave 2B — Programs System
# ═══════════════════════════════════════════════════════════════════

class ProgramCreate(BaseModel):
    name: Dict[str, str] = Field(..., description="Program name in multiple languages, e.g. {'en': '...', 'ar': '...'}")
    slug: str = Field(..., min_length=1, max_length=200)
    description: Optional[Dict[str, str]] = None
    theme_config: Optional[Dict[str, Any]] = None
    is_public: Optional[bool] = False


class ProgramUpdate(BaseModel):
    name: Optional[Dict[str, str]] = None
    slug: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[Dict[str, str]] = None
    theme_config: Optional[Dict[str, Any]] = None
    is_public: Optional[bool] = None
    is_active: Optional[bool] = None


class ProgramResponse(BaseModel):
    id: UUID
    name: Dict[str, str]
    slug: Optional[str] = None
    description: Optional[Dict[str, str]] = None
    theme_config: Optional[Dict[str, Any]] = None
    is_public: Optional[bool] = False
    publisher_id: Optional[UUID] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("name", mode="before")
    @classmethod
    def coerce_name(cls, v: Any) -> Dict[str, str]:
        if isinstance(v, str):
            return {"en": v, "ar": v}
        return v

    @field_validator("description", mode="before")
    @classmethod
    def coerce_description(cls, v: Any) -> Optional[Dict[str, str]]:
        if isinstance(v, str):
            return {"en": v, "ar": v}
        return v

    class Config:
        from_attributes = True


class ProgramsListResponse(BaseModel):
    programs: List[ProgramResponse]
    total: int


class ProgramMembershipResponse(BaseModel):
    id: UUID
    program_id: UUID
    user_id: UUID
    role: str
    joined_at: datetime

    class Config:
        from_attributes = True


class ProgramAvatarResponse(BaseModel):
    id: UUID
    program_id: UUID
    avatar_id: UUID
    added_at: datetime

    class Config:
        from_attributes = True


class ProgramCourseResponse(BaseModel):
    id: UUID
    program_id: UUID
    course_id: UUID
    added_at: datetime

    class Config:
        from_attributes = True


class ProgramAddAvatarRequest(BaseModel):
    avatar_id: UUID


class ProgramAddCourseRequest(BaseModel):
    course_id: UUID


class SetUserProgramRequest(BaseModel):
    program_id: Optional[UUID] = None


class AdminSetUserRoleRequest(BaseModel):
    role: str = Field(..., pattern="^(admin|publisher|subscriber)$")


# ═══════════════════════════════════════════════════════════════════
# Wave 2C — GDPR Compliance
# ═══════════════════════════════════════════════════════════════════

class UserAgreementCreate(BaseModel):
    agreement_type: str = Field(..., description="terms | privacy | gdpr | marketing")


class UserAgreementResponse(BaseModel):
    id: UUID
    user_id: UUID
    agreement_type: str
    agreed_at: datetime
    ip_address: Optional[str] = None

    class Config:
        from_attributes = True


class UserDataExportResponse(BaseModel):
    user: dict
    agreements: List[dict]


# ═══════════════════════════════════════════════════════════════════
# Wave 3 — Avatar–Course Join + Access Codes
# ═══════════════════════════════════════════════════════════════════

# ── Avatar–Course join (R50) ──────────────────────────────────────

class AvatarCourseAddRequest(BaseModel):
    course_id: UUID
    sort_order: int = Field(0, ge=0)


class AvatarCourseResponse(BaseModel):
    id: UUID
    avatar_id: UUID
    course_id: UUID
    sort_order: int
    added_at: datetime

    class Config:
        from_attributes = True


class AvatarCoursesListResponse(BaseModel):
    courses: List[AvatarCourseResponse]
    total: int


# ── Avatar access codes (R46, R47, R49) ──────────────────────────

class AvatarAccessCodeCreate(BaseModel):
    max_users: int = Field(..., ge=1, description="Maximum number of subscribers who may redeem this code")
    credits_per_user: Decimal = Field(Decimal("0"), ge=0, description="Credits granted to each subscriber on redemption")
    expires_at: Optional[datetime] = None


class AvatarAccessCodeUpdate(BaseModel):
    max_users: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None


class AvatarAccessCodeResponse(BaseModel):
    id: UUID
    avatar_id: UUID
    created_by: Optional[UUID] = None
    code: str
    max_users: int
    users_count: int
    credits_per_user: Decimal
    is_active: bool
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AvatarAccessCodesListResponse(BaseModel):
    codes: List[AvatarAccessCodeResponse]
    total: int


# ── Avatar access code redemption (R48) ──────────────────────────

class AvatarCodeRedeemRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)


class AvatarCodeRedeemResponse(BaseModel):
    success: bool
    code: str
    avatar_id: UUID
    subscription_created: bool
    credits_granted: Decimal
    courses_enrolled: List[UUID]
    programs_enrolled: List[UUID]
    message: str


# ═══════════════════════════════════════════════════════════════════
# Wave 4 — Variant-Based Session Runtime (Phase 5)
# ═══════════════════════════════════════════════════════════════════

class SearchKnowledgeRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(5, ge=1, le=20)


class KnowledgeChunk(BaseModel):
    slide_number: Optional[int] = None
    chunk_index: Optional[int] = None
    content: str
    score: float
    source: str  # "slide" | "course_material"


class SearchKnowledgeResponse(BaseModel):
    query: str
    results: List[KnowledgeChunk]
    total: int


class FlagTopicRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    context: Optional[str] = Field(None, max_length=2000)


class FlagTopicResponse(BaseModel):
    session_run_id: str
    topic: str
    flagged_at: datetime
    message: str


class PatchSessionRoleRequest(BaseModel):
    """Request body for PATCH /sessions/{id}/role — at least one of role_id or variant_id required."""
    role_id: Optional[str] = None
    variant_id: Optional[UUID] = None
    session_run_id: Optional[str] = None


class VariantSwitchRequest(BaseModel):
    variant_id: UUID
    session_run_id: Optional[str] = None  # when provided, logs to session_persona_switches


class VariantSwitchResponse(BaseModel):
    session_id: str
    variant_id: UUID
    variant_name: str
    language: Optional[str] = None
    switched_at: datetime


# ── Wave 6: Feedback ─────────────────────────────────────────────────────────

class SessionFeedbackRequest(BaseModel):
    overall_rating: Optional[int] = Field(None, ge=1, le=5)
    clarity_rating: Optional[int] = Field(None, ge=1, le=5)
    helpfulness_rating: Optional[int] = Field(None, ge=1, le=5)
    engagement_rating: Optional[int] = Field(None, ge=1, le=5)
    comments: Optional[str] = Field(None, max_length=2000)
    tags: Optional[List[str]] = None


class SessionFeedbackResponse(BaseModel):
    id: UUID
    session_run_id: UUID
    user_id: UUID
    overall_rating: Optional[int] = None
    clarity_rating: Optional[int] = None
    helpfulness_rating: Optional[int] = None
    engagement_rating: Optional[int] = None
    comments: Optional[str] = None
    tags: Optional[List[str]] = None
    created_at: datetime


class TranscriptFeedbackRequest(BaseModel):
    turn_index: int = Field(..., ge=0)
    rating: Optional[str] = Field(None, pattern="^(helpful|incorrect|unclear|other)$")
    comment: Optional[str] = Field(None, max_length=1000)


class TranscriptFeedbackResponse(BaseModel):
    id: UUID
    session_run_id: UUID
    user_id: UUID
    turn_index: int
    rating: Optional[str] = None
    comment: Optional[str] = None
    created_at: datetime


# ── Wave 6: Analytics ────────────────────────────────────────────────────────

class CourseProgressSummary(BaseModel):
    course_id: UUID
    course_name: str
    completion_pct: float
    time_spent_sec: int
    last_session_at: Optional[datetime] = None


class AssessmentSummary(BaseModel):
    session_run_id: UUID
    score: Optional[float] = None
    question_count: int
    generated_at: datetime


class MonthlyCompletion(BaseModel):
    month: str
    value: int


class CoursePerformance(BaseModel):
    name: dict[str, str]
    completion: int
    subscribers: int


class AtRiskSubscriber(BaseModel):
    name: dict[str, str]
    course: dict[str, str]
    progress: int


class SubscriberAnalyticsResponse(BaseModel):
    user_id: UUID
    total_sessions_completed: int
    total_time_spent_sec: int
    course_progress: List[CourseProgressSummary]
    recent_assessments: List[AssessmentSummary]
    average_session_rating: Optional[float] = None


class AvatarAnalyticsSummary(BaseModel):
    avatar_id: UUID
    avatar_name: str
    total_subscribers: int
    active_subscribers: int
    total_session_runs: int
    avg_session_duration_sec: Optional[float] = None
    avg_rating: Optional[float] = None


class CourseAnalyticsSummary(BaseModel):
    course_id: UUID
    course_name: str
    enrolled_count: int
    avg_completion_pct: float
    total_session_runs: int


class PublisherAnalyticsResponse(BaseModel):
    publisher_id: UUID
    total_avatars: int
    total_courses: int
    avatar_stats: List[AvatarAnalyticsSummary]
    course_stats: List[CourseAnalyticsSummary]
    total_credits_earned: float
    monthly_completions: List[MonthlyCompletion] = []
    course_performance: List[CoursePerformance] = []
    at_risk_learners: List[AtRiskSubscriber] = []


class AdminAnalyticsResponse(BaseModel):
    total_users: int
    total_publishers: int
    total_subscribers: int
    total_avatars: int
    total_courses: int
    total_session_runs: int
    total_credits_issued: float
    total_credits_consumed: float
    sessions_last_7_days: int
    sessions_last_30_days: int
    monthly_completions: List[MonthlyCompletion] = []
    course_performance: List[CoursePerformance] = []
    at_risk_learners: List[AtRiskSubscriber] = []


# ── Wave 7: AI Navigation Assistant ──────────────────────────────────────────

class AssistantMessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class AssistantConversationSummary(BaseModel):
    id: UUID
    title: str
    context_type: str
    avatar_id: Optional[UUID] = None
    program_id: Optional[UUID] = None
    message_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AssistantConversationDetail(BaseModel):
    id: UUID
    title: str
    context_type: str
    avatar_id: Optional[UUID] = None
    program_id: Optional[UUID] = None
    messages: List[AssistantMessageResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AssistantConversationListResponse(BaseModel):
    conversations: List[AssistantConversationSummary]
    total: int


class AssistantConversationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    avatar_id: Optional[UUID] = None
    program_id: Optional[UUID] = None
    context_type: str = Field("auto", pattern="^(publisher|subscriber|admin|auto)$")


class AssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    conversation_id: Optional[UUID] = None
    avatar_id: Optional[UUID] = None
    program_id: Optional[UUID] = None


class AssistantChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    reply: str
    turn_number: int
    created_at: datetime