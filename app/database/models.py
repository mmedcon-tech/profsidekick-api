import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Enum as SQLEnum, Boolean, BigInteger, Numeric, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.database.connection import Base
import uuid
from datetime import datetime

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
    
    # Professor approval fields
    is_approved = Column(Boolean, nullable=True, default=False)
    approval_token = Column(String(255), nullable=True)
    approval_request_sent_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(255), nullable=True)  # Email of approver
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    avatar = relationship("Avatar", back_populates="configuration")
    rubrics = relationship("Rubric", back_populates="avatar_configuration", cascade="all, delete-orphan")
    knowledge_documents = relationship("KnowledgeDocument", back_populates="avatar_configuration", cascade="all, delete-orphan")
    reference_solutions = relationship("ReferenceSolution", back_populates="avatar_configuration", cascade="all, delete-orphan")


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

# ═══════════════════════════════════════════════════════════════════
# Self Assessment Exam (SAE) System
# Completely isolated from the Math Placement Exam autograder.
# Three tables: sae_students → sae_invitation_tokens → sae_submissions
# ═══════════════════════════════════════════════════════════════════

class SAEStudent(Base):
    """
    A pre-created student slot managed by a publisher before the exam.
    user_id is NULL until the student activates their account via the
    one-time invitation link.
    """
    __tablename__ = "sae_students"
    __table_args__ = (
        UniqueConstraint("publisher_id", "student_number",
                         name="uq_sae_student_publisher_number"),
    )

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_number = Column(Integer, nullable=False)
    student_code   = Column(String(20), unique=True, nullable=False, index=True)
    display_name   = Column(String(100), nullable=False)
    publisher_id   = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
                            nullable=False, index=True)
    user_id        = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
                            nullable=True, index=True)
    is_activated   = Column(Boolean, nullable=False, default=False)
    activated_at   = Column(DateTime, nullable=True)
    has_submitted  = Column(Boolean, nullable=False, default=False)
    submitted_at   = Column(DateTime, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)

    publisher   = relationship("User", foreign_keys=[publisher_id])
    user        = relationship("User", foreign_keys=[user_id])
    invitation  = relationship("SAEInvitationToken", back_populates="student",
                               uselist=False, cascade="all, delete-orphan")
    submission  = relationship("SAESubmission", back_populates="student",
                               uselist=False, cascade="all, delete-orphan")


class SAEInvitationToken(Base):
    """
    One-time setup link for an SAE student.
    token is a secrets.token_urlsafe(32) value (43 chars, 256-bit entropy).
    is_used is flipped to True atomically with User creation inside a transaction.
    No email is ever sent — the publisher copies the URL and distributes it offline.
    """
    __tablename__ = "sae_invitation_tokens"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True),
                        ForeignKey("sae_students.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    token      = Column(String(64), unique=True, nullable=False, index=True)
    is_used    = Column(Boolean, nullable=False, default=False)
    used_at    = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("SAEStudent", back_populates="invitation")


class SAESubmission(Base):
    """
    A single exam submission for an SAE student.
    UNIQUE(student_id) at the DB level enforces the one-submission rule.
    submitted_by_publisher=True means the publisher uploaded on behalf of the student.
    """
    __tablename__ = "sae_submissions"

    id                     = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id             = Column(UUID(as_uuid=True), ForeignKey("sae_students.id",
                                    ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    submitted_by_publisher = Column(Boolean, nullable=False, default=False)
    publisher_user_id      = Column(UUID(as_uuid=True),
                                    ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    handwritten_filename   = Column(String(255), nullable=True)
    handwritten_file_path  = Column(String(500), nullable=True)
    webassign_filename     = Column(String(255), nullable=True)
    webassign_file_path    = Column(String(500), nullable=True)
    score                  = Column(Integer, nullable=True)
    overall_confidence     = Column(String(50), nullable=True)
    review_required        = Column(Boolean, nullable=False, default=False)
    result_json            = Column(JSONB, nullable=True)
    # Instructor-edited copy; NULL until the first publisher edit.
    # result_json holds the original LLM output and is never overwritten.
    edited_result_json     = Column(JSONB, nullable=True)
    last_edited_at         = Column(DateTime, nullable=True)
    last_edited_by         = Column(UUID(as_uuid=True),
                                    ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at             = Column(DateTime, default=datetime.utcnow)
    updated_at             = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student        = relationship("SAEStudent", back_populates="submission")
    publisher_user = relationship("User", foreign_keys=[publisher_user_id])
    last_editor    = relationship("User", foreign_keys=[last_edited_by])


class Student(Base):
    __tablename__ = "students"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_code = Column(String(20), unique=True, nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    created_by   = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User", foreign_keys=[created_by])
    submissions = relationship(
        "AutograderSubmission",
        back_populates="student",
        foreign_keys="[AutograderSubmission.student_id]",
        order_by="AutograderSubmission.version_number",
    )


class AutograderSubmission(Base):
    __tablename__ = "autograder_submissions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ── New columns (Phase 3) ────────────────────────────────────────────────
    student_id    = Column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="RESTRICT"), nullable=True)
    version_number = Column(Integer, nullable=True)
    submitted_by  = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)

    handwritten_filename  = Column(String(255), nullable=True)
    handwritten_file_path = Column(String(500), nullable=True)
    webassign_filename    = Column(String(255), nullable=True)
    webassign_file_path   = Column(String(500), nullable=True)

    # ── Legacy columns (kept until Phase 5) ─────────────────────────────────
    # Link to logged-in account when available
    student_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Human-facing placement test identity
    student_net_id = Column(String(100), nullable=False)
    student_name = Column(String(255), nullable=False)

    # Uploaded submission file, nullable for now
    filename = Column(String(255), nullable=True)
    file_path = Column(String(500), nullable=True)

    # Summary fields for professor table
    score = Column(Integer, nullable=True)
    overall_confidence = Column(String(50), nullable=True)
    review_required = Column(Boolean, default=False)

    # Full AI grading result
    result_json = Column(JSONB, nullable=False)

    # Only the newest submission per student is active; older ones are False
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")

    created_at = Column(DateTime, default=datetime.utcnow)

    # ── Relationships ────────────────────────────────────────────────────────
    student      = relationship("Student", foreign_keys=[student_id], back_populates="submissions")
    student_user = relationship("User", foreign_keys=[student_user_id])
    operator     = relationship("User", foreign_keys=[submitted_by])