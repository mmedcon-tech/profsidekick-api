import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import text
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Enum as SQLEnum, Boolean, BigInteger, Numeric, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.database.connection import Base


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class SessionRunStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"

class MaterialType(str, Enum):
    BOOK = "book"
    ARTICLE = "article"
    VIDEO = "video"
    DOCUMENT = "document"
    LINK = "link"
    OTHER = "other"

class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)  # Renamed from password
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    role = Column(String(50), default="teacher", nullable=False)
    
    # Email verification fields
    email_verified = Column(Boolean, nullable=True, default=False)
    email_verification_token = Column(String(255), nullable=True)
    email_verification_sent_at = Column(DateTime, nullable=True)

    # Password reset fields
    password_reset_token = Column(String(255), nullable=True)
    password_reset_sent_at = Column(DateTime, nullable=True)
    
    # Professor approval fields
    is_approved = Column(Boolean, nullable=True, default=False)
    approval_token = Column(String(255), nullable=True)
    approval_request_sent_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(255), nullable=True)  # Email of approver
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    onboarding_completed_at = Column(DateTime, nullable=True)  # first-run guide finished or skipped
    
    # Relationships
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    session_runs = relationship("SessionRun", back_populates="user", cascade="all, delete-orphan")
    prompts = relationship("SavedPrompt", back_populates="user", cascade="all, delete-orphan")
    courses_created = relationship("Course", back_populates="user", cascade="all, delete-orphan")
    courses_enrolled = relationship("Course", secondary="course_students", back_populates="students")
    avatar_templates_created = relationship("AvatarTemplate", back_populates="creator", foreign_keys="[AvatarTemplate.created_by]")
    avatars_published = relationship("Avatar", back_populates="publisher", foreign_keys="[Avatar.publisher_id]")

class Course(Base):
    __tablename__ = "courses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(200))
    code = Column(String(50), nullable=True)
    section = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    department = Column(String(200), nullable=True)
    semester = Column(String(50), nullable=True)
    year = Column(Integer, nullable=True)
    syllabus_details = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True)
    is_deleted = Column(Boolean, default=False)
    is_public = Column(Boolean, default=False)
    allow_subscriber_sessions = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="courses_created")
    sessions = relationship("Session", back_populates="course", cascade="all, delete-orphan")
    students = relationship("User", secondary="course_students", back_populates="courses_enrolled")
    course_materials = relationship("CourseMaterial", back_populates="course", cascade="all, delete-orphan")
    access_codes = relationship("CourseAccessCode", back_populates="course", cascade="all, delete-orphan")

class CourseMaterial(Base):
    __tablename__ = "course_materials"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    material_type = Column(SQLEnum(MaterialType), nullable=False)
    file_path = Column(String(500), nullable=True)  # For uploaded files
    file_name = Column(String(255), nullable=True)  # Original filename
    file_size = Column(BigInteger, nullable=True)  # File size in bytes
    file_type = Column(String(50), nullable=True)  # MIME type
    url = Column(String(500), nullable=True)  # For external links
    author = Column(String(255), nullable=True)  # Book/article author
    publication_year = Column(Integer, nullable=True)
    publisher = Column(String(255), nullable=True)
    isbn = Column(String(20), nullable=True)  # For books
    doi = Column(String(100), nullable=True)  # For academic articles
    additional_info = Column(JSONB, nullable=True)  # For additional flexible data
    is_required = Column(Boolean, default=True)  # Required vs recommended material
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    course = relationship("Course", back_populates="course_materials")
    session_materials = relationship("SessionMaterial", back_populates="course_material", cascade="all, delete-orphan")

class CourseStudent(Base):
    __tablename__ = "course_students"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    enrollment_date = Column(DateTime, default=datetime.utcnow)


class CourseAccessCode(Base):
    __tablename__ = "course_access_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(32), nullable=False, unique=True, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    max_uses = Column(Integer, nullable=True)
    uses_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    course = relationship("Course", back_populates="access_codes")
    creator = relationship("User", foreign_keys=[created_by])
    
class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(50), unique=True, nullable=False, index=True)
    session_number = Column(Integer, nullable=True)
    session_date = Column(DateTime, nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    class_name = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    duration = Column(Integer, nullable=True)  # Duration in minutes
    presentation_details = Column(JSONB, nullable=True)
    slides_details = Column(JSONB, nullable=True)
    assistant_parameters = Column(JSONB, nullable=True)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=True)
    # Role selected at session creation — FK set after avatar_template_roles is created
    selected_role_id = Column(UUID(as_uuid=True),
                               ForeignKey("avatar_template_roles.id", use_alter=True,
                                          name="fk_sessions_selected_role",
                                          ondelete="SET NULL"),
                               nullable=True)
    role_label = Column(String(100), nullable=True)  # snapshot of role name
    session_mode = Column(String(20), nullable=False, default="teaching", server_default="teaching")  # teaching | examination
    subscriber_runtime_mode = Column(String(20), nullable=False, default="avatar", server_default="avatar")  # avatar | chat | choice

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    session_runs = relationship("SessionRun", back_populates="session", cascade="all, delete-orphan")
    user = relationship("User", back_populates="sessions")
    course = relationship("Course", back_populates="sessions")
    session_materials = relationship("SessionMaterial", back_populates="session", cascade="all, delete-orphan")
    avatar = relationship("Avatar", back_populates="sessions")
    selected_role = relationship("AvatarTemplateRole", foreign_keys=[selected_role_id])
class SessionRun(Base):
    __tablename__ = "session_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_run_id = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    session_run_metadata = Column(JSONB)
    assistant_parameters = Column(JSONB)
    status = Column(SQLEnum(SessionRunStatus), default=SessionRunStatus.ACTIVE)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    # Post-session AI-generated summary (produced by SummarizationService on stop)
    ai_summary = Column(Text, nullable=True)
    # Snapshot of the role name when this run started (denormalized for history)
    role_at_start = Column(String(100), nullable=True)
    # Which runtime was actually used for this run (avatar | chat)
    runtime_mode_used = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    session = relationship("Session", back_populates="session_runs")
    user = relationship("User", back_populates="session_runs")


class CreditBalance(Base):
    __tablename__ = "credit_balances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    balance_credits = Column(Numeric(12, 6), nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class AccessCode(Base):
    __tablename__ = "access_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), nullable=False, unique=True, index=True)
    total_credits = Column(Numeric(12, 6), nullable=False)
    remaining_credits = Column(Numeric(12, 6), nullable=False)
    issued_by = Column(String(255), nullable=False)
    max_redemptions = Column(Integer, nullable=False, default=1)
    redemptions_used = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    redemptions = relationship("AccessCodeRedemption", back_populates="access_code")
    usage_records = relationship("UsageRecord", back_populates="access_code")


class AccessCodeRedemption(Base):
    __tablename__ = "access_code_redemptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    access_code_id = Column(UUID(as_uuid=True), ForeignKey("access_codes.id"), nullable=False)
    redeemed_at = Column(DateTime, default=datetime.utcnow)
    credits_at_redemption = Column(Numeric(12, 6), nullable=False)

    user = relationship("User")
    access_code = relationship("AccessCode", back_populates="redemptions")


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_run_id = Column(UUID(as_uuid=True), ForeignKey("session_runs.id"), nullable=True)
    operation_type = Column(String(50), nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    raw_cost_usd = Column(Numeric(12, 6), nullable=False)
    platform_fee_usd = Column(Numeric(12, 6), nullable=False)
    total_cost_usd = Column(Numeric(12, 6), nullable=False)
    credits_charged = Column(Numeric(12, 6), nullable=False)
    funded_by = Column(String(20), nullable=False)
    access_code_id = Column(UUID(as_uuid=True), ForeignKey("access_codes.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    session_run = relationship("SessionRun")
    access_code = relationship("AccessCode", back_populates="usage_records")


class PricingConfig(Base):
    __tablename__ = "pricing_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_type = Column(String(50), nullable=False, unique=True, index=True)
    cost_per_1k_input_tokens = Column(Numeric(12, 6), nullable=False, default=0)
    cost_per_1k_output_tokens = Column(Numeric(12, 6), nullable=False, default=0)
    platform_fee_multiplier = Column(Numeric(5, 4), nullable=False, default=1)
    minimum_charge_credits = Column(Numeric(12, 6), nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class SessionMaterial(Base):
    __tablename__ = "session_materials"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    course_material_id = Column(UUID(as_uuid=True), ForeignKey("course_materials.id"), nullable=False)
    is_included = Column(Boolean, default=True)  # Whether this material is included in the session
    usage_instructions = Column(Text, nullable=True)  # How to use this material in the session
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    session = relationship("Session", back_populates="session_materials")
    course_material = relationship("CourseMaterial", back_populates="session_materials")

class SavedPrompt(Base):
    __tablename__ = "saved_prompts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200))
    description = Column(Text)
    category = Column(String(100))
    content = Column(Text)
    tags = Column(String(255))
    is_default = Column(Boolean, default=False)
    is_public = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    usage_count = Column(Integer, default=0)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    
    # Relationships
    user = relationship("User", back_populates="prompts")


class AvatarTemplate(Base):
    __tablename__ = "avatar_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)

    # Visual identity — image shown across all platform listings for this template
    avatar_image_path = Column(String(500), nullable=True)

    # Legacy prompt columns — kept for backwards compatibility.
    # New prompts live in AvatarTemplateVersion rows.
    hidden_system_prompt = Column(Text, nullable=True)
    default_realtime_prompt = Column(Text, nullable=True)
    default_vision_prompt = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)
    subscription_cost = Column(Numeric(12, 6), nullable=False, default=3, server_default="3")
    # Points to the currently published version; NULL until first publish
    current_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatar_template_versions.id", use_alter=True,
                   name="fk_avatar_templates_current_version"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User", back_populates="avatar_templates_created", foreign_keys=[created_by])
    avatars = relationship("Avatar", back_populates="template", cascade="all, delete-orphan")
    versions = relationship(
        "AvatarTemplateVersion",
        back_populates="template",
        primaryjoin="AvatarTemplate.id == AvatarTemplateVersion.template_id",
        cascade="all, delete-orphan",
        order_by="AvatarTemplateVersion.version_number",
    )
    roles = relationship(
        "AvatarTemplateRole",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="AvatarTemplateRole.sort_order",
    )
    current_version = relationship(
        "AvatarTemplateVersion",
        foreign_keys=[current_version_id],
        post_update=True,
    )


class AvatarTemplateVersion(Base):
    """
    Immutable prompt snapshot for a template.
    Each Save Draft or Publish creates a new row — existing rows are never
    overwritten so publisher avatars remain frozen at the version they
    were created from (Option A).
    status: draft | published | archived
    """
    __tablename__ = "avatar_template_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("avatar_templates.id", ondelete="CASCADE"), nullable=False)
    version_number = Column(Integer, nullable=False)
    conversation_prompt = Column(Text, nullable=True)        # LEGACY: kept for backward compat; prefer teaching_prompt
    teaching_prompt = Column(Text, nullable=True)            # Used when session_mode = 'teaching'
    examination_prompt = Column(Text, nullable=True)         # Used when session_mode = 'examination'
    document_analysis_prompt = Column(Text, nullable=True)   # replaces default_vision_prompt
    status = Column(String(20), nullable=False, default="draft")  # draft | published | archived
    change_notes = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)
    published_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    template = relationship(
        "AvatarTemplate",
        back_populates="versions",
        foreign_keys=[template_id],
    )
    creator = relationship("User", foreign_keys=[created_by])
    publisher_user = relationship("User", foreign_keys=[published_by])


class AvatarTemplateRole(Base):
    """
    Roles defined by admin for a template.
    Not yet selectable by publisher/subscriber — this is preparation for
    future role-selection workflows.
    """
    __tablename__ = "avatar_template_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("avatar_templates.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    prompt_context = Column(Text, nullable=True)
    is_enabled = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    template = relationship("AvatarTemplate", back_populates="roles")


class Avatar(Base):
    __tablename__ = "avatars"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("avatar_templates.id"), nullable=False)
    publisher_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    is_published = Column(Boolean, default=False)
    subscription_cost = Column(Numeric(12, 6), nullable=False, default=3, server_default="3")
    # Frozen at creation — NULL for pre-versioning avatars (they fall back to legacy prompts)
    template_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatar_template_versions.id", name="fk_avatars_template_version"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    template = relationship("AvatarTemplate", back_populates="avatars")
    template_version = relationship("AvatarTemplateVersion", foreign_keys=[template_version_id])
    publisher = relationship("User", back_populates="avatars_published", foreign_keys=[publisher_id])
    configuration = relationship("AvatarConfiguration", back_populates="avatar", uselist=False, cascade="all, delete-orphan")
    profile = relationship("PublisherAvatarProfile", back_populates="avatar", uselist=False, cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="avatar")


class PublisherAvatarProfile(Base):
    """Structured teaching preferences + generated persona prompt for a publisher avatar."""
    __tablename__ = "publisher_avatar_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publisher_avatar_id = Column(
        UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False, unique=True
    )
    teaching_pace       = Column(String(50),  nullable=True)   # thorough | balanced | fast
    questioning_style   = Column(String(50),  nullable=True)   # socratic | direct | guided
    formality_level     = Column(String(50),  nullable=True)   # casual | balanced | formal
    depth_level         = Column(String(50),  nullable=True)   # surface | standard | deep
    encouragement_level = Column(String(50),  nullable=True)   # high | neutral | minimal
    language_level      = Column(String(50),  nullable=True)   # introductory | intermediate | advanced | adaptive
    refined_prompt      = Column(Text,        nullable=True)   # generated teaching persona prompt
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    avatar = relationship("Avatar", back_populates="profile")


class AvatarConfiguration(Base):
    __tablename__ = "avatar_configurations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False, unique=True)
    voice = Column(String(100), nullable=True)
    language = Column(String(50), nullable=True)
    difficulty_level = Column(String(50), nullable=True)
    additional_settings = Column(JSONB, nullable=True)
    # HeyGen LiveAvatar avatar UUID shown in live sessions (LITE mode).
    heygen_avatar_id = Column(String(100), nullable=True)
    # Who speaks the avatar's replies: 'openai' (Realtime voice in `voice`) or
    # 'elevenlabs' (`elevenlabs_voice_id`, a stock voice or an instant clone).
    voice_provider = Column(String(20), nullable=True)
    elevenlabs_voice_id = Column(String(100), nullable=True)
    # Set only for a clone made on this platform: the publisher's consent time.
    voice_clone_consent_at = Column(DateTime, nullable=True)
    voice_clone_name = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    avatar = relationship("Avatar", back_populates="configuration")
    rubrics = relationship("Rubric", back_populates="avatar_configuration", cascade="all, delete-orphan")
    knowledge_documents = relationship("KnowledgeDocument", back_populates="avatar_configuration", cascade="all, delete-orphan")
    reference_solutions = relationship("ReferenceSolution", back_populates="avatar_configuration", cascade="all, delete-orphan")


class Avatar3DModel(Base):
    __tablename__ = "avatar_3d_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    model_type = Column(String(50), nullable=False, default="three_js")
    model_url = Column(String(500), nullable=False)
    thumbnail_url = Column(String(500), nullable=True)
    gender = Column(String(20), nullable=False, default="neutral")
    supported_languages = Column(JSONB, nullable=False, default=list)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class Rubric(Base):
    __tablename__ = "rubrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_configuration_id = Column(UUID(as_uuid=True), ForeignKey("avatar_configurations.id"), nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    avatar_configuration = relationship("AvatarConfiguration", back_populates="rubrics")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_configuration_id = Column(UUID(as_uuid=True), ForeignKey("avatar_configurations.id"), nullable=False)
    title = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=True)
    file_name = Column(String(255), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    file_type = Column(String(50), nullable=True)
    content_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    avatar_configuration = relationship("AvatarConfiguration", back_populates="knowledge_documents")


class ReferenceSolution(Base):
    __tablename__ = "reference_solutions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_configuration_id = Column(UUID(as_uuid=True), ForeignKey("avatar_configurations.id"), nullable=False)
    title = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=True)
    file_name = Column(String(255), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    file_type = Column(String(50), nullable=True)
    content_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    avatar_configuration = relationship("AvatarConfiguration", back_populates="reference_solutions")


class SlideChunk(Base):
    __tablename__ = "slide_chunks"
    __table_args__ = (
        Index(
            "ix_slide_chunks_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True)
    slide_number = Column(Integer, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index(
            "ix_knowledge_chunks_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=True, index=True)
    source = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session")
    course = relationship("Course")


# ═══════════════════════════════════════════════════════════════════
# Publisher Learning System
# Stores chat history, AI preference feedback, and per-publisher
# settings.  All tables are scoped to publisher_id; admins can read
# any row; publishers see only their own.
# ═══════════════════════════════════════════════════════════════════

from sqlalchemy import UniqueConstraint

class PublisherConversation(Base):
    __tablename__ = "publisher_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publisher_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=True)
    title = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    publisher = relationship("User", foreign_keys=[publisher_id])
    avatar = relationship("Avatar")
    messages = relationship(
        "PublisherMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="PublisherMessage.created_at",
    )


class PublisherMessage(Base):
    __tablename__ = "publisher_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(
        UUID(as_uuid=True), ForeignKey("publisher_conversations.id"), nullable=False, index=True
    )
    role = Column(String(20), nullable=False)   # "user" | "assistant" | "system"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("PublisherConversation", back_populates="messages")


class FeedbackPreference(Base):
    """
    Stores which AI response a publisher chose as better.
    rejected_responses holds the alternatives that were not chosen.
    This data can be used for future RLHF / DPO fine-tuning.
    """
    __tablename__ = "feedback_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publisher_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=True)
    prompt = Column(Text, nullable=False)
    selected_response = Column(Text, nullable=False)
    rejected_responses = Column(JSONB, nullable=False, default=list)
    feedback_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    publisher = relationship("User", foreign_keys=[publisher_id])
    avatar = relationship("Avatar")


class PublisherPreference(Base):
    """
    Key-value store for per-publisher settings.
    Examples: preferred_difficulty, feedback_style, question_style, grading_strictness.
    value is JSONB so it accepts strings, numbers, booleans, or dicts.
    """
    __tablename__ = "publisher_preferences"
    __table_args__ = (
        UniqueConstraint("publisher_id", "key", name="uq_publisher_preference"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publisher_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    key = Column(String(100), nullable=False)
    value = Column(JSONB, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)

    publisher = relationship("User", foreign_keys=[publisher_id])


# ═══════════════════════════════════════════════════════════════════
# Long-Term Memory System
# ═══════════════════════════════════════════════════════════════════

from sqlalchemy import Float

class UserMemory(Base):
    """
    Persistent per-user learning signals that survive across sessions.
    Generated by SummarizationService at session end and stored here.
    Retrieved by importance score and recency; injected into future session prompts.
    """
    __tablename__ = "user_memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="SET NULL"),
                       nullable=True, index=True)
    content = Column(Text, nullable=False)   # e.g. "Struggles with recursion"
    importance = Column(Float, nullable=False, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    # Legacy notes remain inspectable, but are never injected without evidence.
    kind = Column(String(30), nullable=False, default="note", server_default="note")
    topic = Column(String(200), nullable=True)
    evidence_quote = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="active", server_default="active")
    visibility = Column(JSONB, nullable=False, default=lambda: ["learner"], server_default='["learner"]')
    consent_basis = Column(String(40), nullable=True)
    source_run_id = Column(UUID(as_uuid=True), ForeignKey("session_runs.id", ondelete="SET NULL"), nullable=True)
    times_seen = Column(Integer, nullable=False, default=1, server_default="1")
    last_confirmed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    # Stable hash of kind + topic, used for merging and content-free suppression.
    memory_key = Column(String(64), nullable=True)
    edited_at = Column(DateTime, nullable=True)  # set when the user corrects it; seeding never overwrites

    user = relationship("User", foreign_keys=[user_id])
    avatar = relationship("Avatar", foreign_keys=[avatar_id])


class PublisherMessageFeedback(Base):
    """
    Per-message thumbs-up/down + optional comment from publishers.
    Linked to a specific PublisherMessage (AI response).
    Recent comments for a publisher+avatar are injected into future
    system prompts as "Publisher Preferences" context.
    """
    __tablename__ = "publisher_message_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True),
                        ForeignKey("publisher_messages.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    publisher_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True, index=True)
    rating = Column(String(20), nullable=True)   # "good" | "needs_improvement"
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    message = relationship("PublisherMessage")
    publisher = relationship("User", foreign_keys=[publisher_id])


class AvatarSubscription(Base):
    """
    Many-to-many join between subscribers and published avatars.

    A subscriber gains access to an avatar (and its sessions) by subscribing.
    Cascade: deleting an avatar or user removes all related subscriptions.
    """
    __tablename__ = "avatar_subscriptions"
    __table_args__ = (
        UniqueConstraint("subscriber_id", "avatar_id", name="uq_avatar_subscription"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscriber_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    avatar_id = Column(
        UUID(as_uuid=True),
        ForeignKey("avatars.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subscribed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    expires_at = Column(DateTime, nullable=True)

    subscriber = relationship("User", foreign_keys=[subscriber_id])
    avatar = relationship("Avatar", foreign_keys=[avatar_id])


class PublisherResponseEdit(Base):
    """
    Tracks publisher inline edits to AI-generated responses.
    Stores the original and edited text for future teaching-style analysis.
    Flagged as 'publisher_refinement' for downstream analysis pipelines.
    """
    __tablename__ = "publisher_response_edits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True),
                        ForeignKey("publisher_messages.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    publisher_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(String(100), nullable=True, index=True)
    original_content = Column(Text, nullable=False)
    edited_content = Column(Text, nullable=False)
    edit_type = Column(String(50), nullable=False, default="publisher_refinement")
    created_at = Column(DateTime, default=datetime.utcnow)

    message = relationship("PublisherMessage")
    publisher = relationship("User", foreign_keys=[publisher_id])
    avatar = relationship("Avatar", foreign_keys=[avatar_id])

class AuditEvent(Base):
    """
    Append-only record of a state change (ADR 0013).
    Application code only inserts rows; it never updates or deletes them.
    `data` must not contain secrets, passwords, tokens or raw file contents.
    """
    __tablename__ = "audit_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # NULL for system jobs; SET NULL keeps the event when a user is deleted.
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(100), nullable=False, index=True)        # dotted verb, e.g. "user.registered"
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(100), nullable=True)
    data = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
    )


class MemoryControl(Base):
    __tablename__ = "memory_controls"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TwinMemoryConsent(Base):
    __tablename__ = "twin_memory_consents"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    consented_at = Column(DateTime, nullable=True)
    education_shared = Column(Boolean, nullable=False, default=False, server_default="false")
    # Runs starting before this point cannot recreate erased/corrected memories.
    reset_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MemorySuppression(Base):
    __tablename__ = "memory_suppressions"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="CASCADE"), primary_key=True)
    memory_key = Column(String(64), primary_key=True)


class MemoryJob(Base):
    __tablename__ = "memory_jobs"

    run_id = Column(UUID(as_uuid=True), ForeignKey("session_runs.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    available_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ═══════════════════════════════════════════════════════════════════
# MYO'S Fertility — IVF Care program, one persistent consultation per
# user, fertility knowledge with retrieval metadata, instructional
# videos, patient context with provenance, simulated escalations.
# The knowledge / safety / patient-context layer is independent of the
# avatar renderer, so a clinic's own doctor twin can replace the demo
# persona without touching these tables.
# ═══════════════════════════════════════════════════════════════════


class CareProgram(Base):
    __tablename__ = "care_programs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_public = Column(Boolean, nullable=False, default=True, server_default="true")
    doctor_config = Column(JSONB, nullable=True)  # persona, avatar ids, voice
    clinic_id = Column(String(100), nullable=True)  # legacy free-text clinic key
    # ── Multi-program platform (care platform). A CareProgram is a clinic's
    # instance of a global ProgramTemplate. Legacy ivf-care keeps working.
    clinic_ref_id = Column(UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=True, index=True)
    template_id = Column(UUID(as_uuid=True), ForeignKey("program_templates.id", ondelete="SET NULL"), nullable=True)
    persona_id = Column(UUID(as_uuid=True), ForeignKey("doctor_personas.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False, default="published", server_default="published")  # draft|published|unpublished
    enrollment_policy = Column(String(20), nullable=False, default="staff", server_default="staff")  # open|staff
    branding = Column(JSONB, nullable=True)
    position = Column(Integer, nullable=False, default=0, server_default="0")
    is_demo = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class CareProgramMembership(Base):
    """A user's place in a care program. role: patient | partner."""

    __tablename__ = "care_program_memberships"
    __table_args__ = (UniqueConstraint("program_id", "user_id", name="uq_care_membership"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    program_id = Column(UUID(as_uuid=True), ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    care_role = Column(String(20), nullable=False, default="patient")
    treatment_stage = Column(String(50), nullable=True)
    # Partner access to a patient's records is opt-in by the patient and
    # scoped (e.g. ["appointments", "injection_reminders"]). Empty = none.
    linked_patient_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    authorized_scopes = Column(JSONB, nullable=False, default=list, server_default="[]")
    joined_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Consultation(Base):
    """The single, persistent consultation thread for a user in a program."""

    __tablename__ = "consultations"
    __table_args__ = (UniqueConstraint("program_id", "user_id", name="uq_consultation_user_program"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    program_id = Column(UUID(as_uuid=True), ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    care_role = Column(String(20), nullable=False, default="patient")
    status = Column(String(20), nullable=False, default="active")
    last_mode = Column(String(10), nullable=True)  # text | voice | avatar
    # Rolling AI-generated summary of older turns (never treated as verified).
    summary = Column(Text, nullable=True)
    summarized_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship(
        "ConsultationMessage",
        back_populates="consultation",
        cascade="all, delete-orphan",
        order_by="ConsultationMessage.created_at",
    )


class ConsultationMessage(Base):
    __tablename__ = "consultation_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consultation_id = Column(UUID(as_uuid=True), ForeignKey("consultations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    mode = Column(String(10), nullable=False, default="text")
    care_role = Column(String(20), nullable=True)
    # user messages: patient_reported; assistant: ai_generated
    provenance = Column(String(30), nullable=False, default="patient_reported")
    safety = Column(JSONB, nullable=True)
    sources = Column(JSONB, nullable=True)
    videos = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    consultation = relationship("Consultation", back_populates="messages")


class FertilityKnowledgeDocument(Base):
    __tablename__ = "fertility_knowledge_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_key = Column(String(120), nullable=False, unique=True)
    title = Column(String(255), nullable=False)
    # general_education | clinic_protocol | patient_order | product_label | synthetic_demo | video_transcript
    source_type = Column(String(40), nullable=False, default="general_education")
    approval_status = Column(String(30), nullable=False, default="demo_unreviewed")
    clinic_id = Column(String(100), nullable=True)
    jurisdiction = Column(String(50), nullable=True)
    clinician_approver = Column(String(255), nullable=True)
    version = Column(String(30), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    effective_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    original_reference = Column(String(500), nullable=True)
    content_sha256 = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class FertilityKnowledgeChunk(Base):
    __tablename__ = "fertility_knowledge_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("fertility_knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    video_id = Column(UUID(as_uuid=True), ForeignKey("instructional_videos.id", ondelete="CASCADE"), nullable=True, index=True)
    start_seconds = Column(Integer, nullable=True)
    end_seconds = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)
    meta = Column(JSONB, nullable=False, default=dict)  # section 11 schema
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class InstructionalVideo(Base):
    __tablename__ = "instructional_videos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    topic = Column(String(100), nullable=True)
    treatment_stage = Column(String(50), nullable=True)
    audience = Column(String(20), nullable=False, default="both")
    medication_name = Column(String(120), nullable=True)
    device_name = Column(String(120), nullable=True)
    language = Column(String(10), nullable=False, default="en")
    clinic_id = Column(String(100), nullable=True)
    approval_status = Column(String(30), nullable=False, default="demo_unreviewed")
    version = Column(String(30), nullable=True)
    storage_uri = Column(String(500), nullable=True)  # private://…
    external_url = Column(String(1000), nullable=True)
    content_type = Column(String(100), nullable=True)
    thumbnail_uri = Column(String(500), nullable=True)
    transcript = Column(Text, nullable=True)
    captions_vtt = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # care platform placement + publication workflow (draft|in_review|approved|retired)
    program_id = Column(UUID(as_uuid=True), ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=True, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("care_courses.id", ondelete="SET NULL"), nullable=True)
    lesson_id = Column(UUID(as_uuid=True), ForeignKey("care_lessons.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=True)
    position = Column(Integer, nullable=False, default=0, server_default="0")
    reviewer = Column(String(255), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PatientContextEntry(Base):
    """
    Patient context with explicit provenance. verified_clinical rows come
    from (or are confirmed by) the clinic; patient_reported rows are what a
    patient/partner typed; ai_generated rows are model summaries. Nothing
    is ever promoted between provenances automatically.
    """

    __tablename__ = "patient_context_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    program_id = Column(UUID(as_uuid=True), ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=True)
    # treatment_stage | treatment_plan | medication_schedule | confirmed_dose |
    # appointment | procedure | history | clinic_instruction | consultation_summary | note
    kind = Column(String(40), nullable=False)
    content = Column(Text, nullable=False)
    provenance = Column(String(30), nullable=False)  # verified_clinical | patient_reported | ai_generated
    is_synthetic = Column(Boolean, nullable=False, default=False, server_default="false")
    source = Column(String(255), nullable=True)
    verified_by = Column(String(255), nullable=True)
    effective_at = Column(DateTime, nullable=True)
    consent_scope = Column(String(50), nullable=False, default="patient_only")
    created_at = Column(DateTime, default=datetime.utcnow)


class ClinicProtocol(Base):
    """Versioned clinic-approved protocol (Phase 2). Indexed into fertility knowledge when approved."""

    __tablename__ = "clinic_protocols"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = Column(String(100), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    topic = Column(String(100), nullable=True)
    content = Column(Text, nullable=False)
    version = Column(String(30), nullable=False, default="1")
    approval_status = Column(String(30), nullable=False, default="draft")
    clinician_approver = Column(String(255), nullable=True)
    effective_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    knowledge_document_id = Column(UUID(as_uuid=True), ForeignKey("fertility_knowledge_documents.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SimulatedEscalation(Base):
    """Demo-only record of a handoff the patient asked for. Nothing is sent."""

    __tablename__ = "simulated_escalations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consultation_id = Column(UUID(as_uuid=True), ForeignKey("consultations.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(40), nullable=False)
    summary = Column(Text, nullable=False)
    simulated = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime, default=datetime.utcnow)



# ═══════════════════════════ Care platform (multi-program) ═══════════════════════════
# Platform → Clinic (publisher org) → Program (instance of a ProgramTemplate)
# → Course → Lesson. Personas (doctor twins) are reusable per clinic.
# Access is explicit CareEntitlement rows, separate from credits/billing.

class Clinic(Base):
    __tablename__ = "clinics"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    branding = Column(JSONB, nullable=True)  # {primary_color, logo_url, accent}
    contact_routes = Column(JSONB, nullable=False, default=list, server_default="[]")  # [{key,label,detail,hours}]
    response_expectation = Column(Text, nullable=True)  # e.g. "Messages are read on weekdays 9-17"
    status = Column(String(20), nullable=False, default="active", server_default="active")
    is_demo = Column(Boolean, nullable=False, default=False, server_default="false")
    is_pilot = Column(Boolean, nullable=False, default=False, server_default="false")
    languages = Column(JSONB, nullable=False, default=lambda: ["en"], server_default='["en"]')
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime, nullable=True)  # set when staff edit name/description; seeding keeps those


class ClinicStaff(Base):
    __tablename__ = "clinic_staff"
    __table_args__ = (UniqueConstraint("clinic_id", "user_id", name="uq_clinic_staff"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    can_manage = Column(Boolean, nullable=False, default=False, server_default="false")   # clinic settings, staff
    can_publish = Column(Boolean, nullable=False, default=False, server_default="false")  # programs, drafts, publish
    can_approve = Column(Boolean, nullable=False, default=False, server_default="false")  # clinical approval
    can_view_clinical = Column(Boolean, nullable=False, default=False, server_default="false")  # handoffs
    display_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProgramTemplate(Base):
    __tablename__ = "program_templates"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    care_area = Column(String(120), nullable=True)
    description = Column(Text, nullable=True)
    default_config = Column(JSONB, nullable=True)  # {suggested_courses:[...], icon, color}
    status = Column(String(20), nullable=False, default="active", server_default="active")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DoctorPersona(Base):
    __tablename__ = "doctor_personas"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    title = Column(String(255), nullable=True)
    specialty = Column(String(255), nullable=True)
    prompt = Column(Text, nullable=True)  # tone/style only; safety rules are platform-enforced
    avatar_id = Column(UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True)
    liveavatar_avatar_id = Column(String(100), nullable=True)
    variant = Column(String(100), nullable=True)
    voice_id = Column(String(100), nullable=True)
    gender = Column(String(10), nullable=True)
    is_demo = Column(Boolean, nullable=False, default=False, server_default="false")
    status = Column(String(20), nullable=False, default="active", server_default="active")
    slug = Column(String(100), nullable=True, unique=True, index=True)
    profile = Column(JSONB, nullable=False, default=dict, server_default="{}")  # photo, voices, reviewed_by, likeness, consent, modes, programs
    first_messages = Column(JSONB, nullable=False, default=dict, server_default="{}")  # {"en": "...", "ar": "..."}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class CareCourse(Base):
    __tablename__ = "care_courses"
    __table_args__ = (UniqueConstraint("program_id", "slug", name="uq_care_course_slug"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    program_id = Column(UUID(as_uuid=True), ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    slug = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    position = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(String(20), nullable=False, default="draft", server_default="draft")  # draft|published|unpublished
    requires_entitlement = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class CareLesson(Base):
    __tablename__ = "care_lessons"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("care_courses.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    position = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(String(20), nullable=False, default="draft", server_default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class CareEntitlement(Base):
    """Explicit access grant: a user in a clinic program (optionally one course)."""
    __tablename__ = "care_entitlements"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    program_id = Column(UUID(as_uuid=True), ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("care_courses.id", ondelete="CASCADE"), nullable=True)
    care_role = Column(String(20), nullable=False, default="patient", server_default="patient")
    source = Column(String(30), nullable=False)  # legacy_membership | open_enrollment | staff_grant
    granted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    terms_version = Column(String(30), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)


class CareContentItem(Base):
    """Versioned clinical content. Only status=approved, unexpired, latest in its
    lineage is retrievable. Patient-specific plans never live here."""
    __tablename__ = "care_content_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lineage_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    program_id = Column(UUID(as_uuid=True), ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("care_courses.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(30), nullable=False)  # protocol|patient_instruction|faq|document|deidentified_case
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    language = Column(String(10), nullable=False, default="en", server_default="en")
    audience = Column(String(20), nullable=False, default="patient", server_default="patient")  # patient|caregiver|both|staff
    applicability = Column(Text, nullable=True)
    source = Column(String(500), nullable=True)
    source_url = Column(String(500), nullable=True)
    source_type = Column(String(30), nullable=True)  # clinic_material | public_guidance
    seed_key = Column(String(150), nullable=True, index=True)
    edited_at = Column(DateTime, nullable=True)  # set on publisher edits; seeding never overwrites these
    status = Column(String(20), nullable=False, default="draft", server_default="draft")  # draft|in_review|approved|retired
    reviewer = Column(String(255), nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    is_demo = Column(Boolean, nullable=False, default=False, server_default="false")
    video_id = Column(UUID(as_uuid=True), ForeignKey("instructional_videos.id", ondelete="CASCADE"), nullable=True)
    # SHA-256 of the canonical content (see services/care/integrity.py); approved_sha256 is pinned at approval.
    content_sha256 = Column(String(64), nullable=True)
    approved_sha256 = Column(String(64), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class CareContentChunk(Base):
    __tablename__ = "care_content_chunks"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(UUID(as_uuid=True), ForeignKey("care_content_items.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=0)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    item_sha256 = Column(String(64), nullable=True)  # hash of the item text this chunk was cut from


class RedFlagRule(Base):
    """Clinic-configured warning sign. No thresholds are invented by the platform."""
    __tablename__ = "red_flag_rules"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    program_id = Column(UUID(as_uuid=True), ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("care_courses.id", ondelete="SET NULL"), nullable=True)
    symptom = Column(String(255), nullable=False)
    match_terms = Column(JSONB, nullable=False, default=list, server_default="[]")
    clinic_action = Column(Text, nullable=False)
    urgency = Column(String(20), nullable=False)  # emergency|urgent|same_day|routine
    contact_route = Column(String(100), nullable=True)  # key into clinic.contact_routes
    applicability = Column(Text, nullable=True)
    reviewer = Column(String(255), nullable=True)
    review_date = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="draft", server_default="draft")
    is_demo = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class CareHandoff(Base):
    """Request for human review. Simulated in demo clinics (nothing is sent)."""
    __tablename__ = "care_handoffs"
    __table_args__ = (Index("uq_care_handoffs_user_idem", "user_id", "idempotency_key", unique=True,
                            postgresql_where=text("idempotency_key IS NOT NULL")),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    program_id = Column(UUID(as_uuid=True), ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    consultation_id = Column(UUID(as_uuid=True), ForeignKey("consultations.id", ondelete="SET NULL"), nullable=True)
    reason = Column(String(40), nullable=False)  # red_flag|personal_judgment|patient_request
    summary = Column(Text, nullable=False)
    contact_route = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="open", server_default="open")
    simulated = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime, default=datetime.utcnow)
    # Review queue (phase 3). received_at = the platform stored it (receipt);
    # acknowledged_at = a human looked at it. They are never conflated.
    idempotency_key = Column(String(80), nullable=True)
    received_at = Column(DateTime, nullable=True)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)


class CareHandoffEvent(Base):
    """Audit trail of one review request: received|assigned|acknowledged|reply|closed."""
    __tablename__ = "care_handoff_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    handoff_id = Column(UUID(as_uuid=True), ForeignKey("care_handoffs.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(20), nullable=False)
    body = Column(Text, nullable=True)
    is_synthetic = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, default=datetime.utcnow)


class CareInvitation(Base):
    """Enrollment code (clinic -> patient) or supporter invitation (patient -> supporter).
    Only a SHA-256 of the code is stored."""
    __tablename__ = "care_invitations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind = Column(String(20), nullable=False)  # enrollment|support
    code_hash = Column(String(64), nullable=False, unique=True)  # verifier only, never the code
    hash_alg = Column(String(16), nullable=False, default="hmac-sha256", server_default="sha256")
    code_hint = Column(String(8), nullable=True)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    program_id = Column(UUID(as_uuid=True), ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    care_role = Column(String(20), nullable=False, default="patient")
    scopes = Column(JSONB, nullable=False, default=list, server_default="[]")
    label = Column(String(120), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    patient_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    max_uses = Column(Integer, nullable=False, default=1, server_default="1")
    use_count = Column(Integer, nullable=False, default=0, server_default="0")
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CareSupportGrant(Base):
    """A patient's scoped, revocable grant to a supporter's own account."""
    __tablename__ = "care_support_grants"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False)
    program_id = Column(UUID(as_uuid=True), ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    supporter_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    invitation_id = Column(UUID(as_uuid=True), ForeignKey("care_invitations.id", ondelete="SET NULL"), nullable=True)
    entitlement_id = Column(UUID(as_uuid=True), ForeignKey("care_entitlements.id", ondelete="SET NULL"), nullable=True)
    scopes = Column(JSONB, nullable=False, default=list, server_default="[]")
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CareDeviceAssignment(Base):
    """Verified medication/device: program-wide clinic configuration (user_id NULL)
    or a per-patient assignment. The assistant never guesses a device."""
    __tablename__ = "care_device_assignments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = Column(UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False)
    program_id = Column(UUID(as_uuid=True), ForeignKey("care_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    medication = Column(String(120), nullable=False)
    device = Column(String(120), nullable=True)
    guide_lineage_id = Column(UUID(as_uuid=True), nullable=True)
    video_id = Column(UUID(as_uuid=True), ForeignKey("instructional_videos.id", ondelete="SET NULL"), nullable=True)
    verified_by = Column(String(255), nullable=False)
    source = Column(String(20), nullable=False)  # clinic_config|assignment
    is_demo = Column(Boolean, nullable=False, default=False, server_default="false")
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
