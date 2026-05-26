import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Enum as SQLEnum, Boolean, BigInteger, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
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
    credit_balance = relationship("CreditBalance", back_populates="user", uselist=False, cascade="all, delete-orphan")
    access_code_redemptions = relationship("AccessCodeRedemption", back_populates="user", cascade="all, delete-orphan")
    usage_records = relationship("UsageRecord", back_populates="user", cascade="all, delete-orphan")

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="courses_created")
    sessions = relationship("Session", back_populates="course", cascade="all, delete-orphan")
    students = relationship("User", secondary="course_students", back_populates="courses_enrolled")
    course_materials = relationship("CourseMaterial", back_populates="course", cascade="all, delete-orphan")

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
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    session_runs = relationship("SessionRun", back_populates="session", cascade="all, delete-orphan")
    user = relationship("User", back_populates="sessions")
    course = relationship("Course", back_populates="sessions")
    session_materials = relationship("SessionMaterial", back_populates="session", cascade="all, delete-orphan")
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    session = relationship("Session", back_populates="session_runs")
    user = relationship("User", back_populates="session_runs")
    usage_records = relationship("UsageRecord", back_populates="session_run")

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


# ─── Billing Models ────────────────────────────────────────────────────────────

class CreditBalance(Base):
    __tablename__ = "credit_balances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    balance_credits = Column(Numeric(precision=12, scale=6), nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="credit_balance")


class AccessCode(Base):
    __tablename__ = "access_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, nullable=False, index=True)
    total_credits = Column(Numeric(precision=12, scale=6), nullable=False)
    remaining_credits = Column(Numeric(precision=12, scale=6), nullable=False)
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
    # Credits remaining on the code at the moment of redemption
    credits_at_redemption = Column(Numeric(precision=12, scale=6), nullable=False)

    user = relationship("User", back_populates="access_code_redemptions")
    access_code = relationship("AccessCode", back_populates="redemptions")


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_run_id = Column(UUID(as_uuid=True), ForeignKey("session_runs.id"), nullable=True)
    operation_type = Column(String(50), nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    raw_cost_usd = Column(Numeric(precision=12, scale=6), nullable=False)
    platform_fee_usd = Column(Numeric(precision=12, scale=6), nullable=False)
    total_cost_usd = Column(Numeric(precision=12, scale=6), nullable=False)
    credits_charged = Column(Numeric(precision=12, scale=6), nullable=False)
    # "purchased" or "access_code"
    funded_by = Column(String(20), nullable=False)
    access_code_id = Column(UUID(as_uuid=True), ForeignKey("access_codes.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="usage_records")
    session_run = relationship("SessionRun", back_populates="usage_records")
    access_code = relationship("AccessCode", back_populates="usage_records")


class PricingConfig(Base):
    __tablename__ = "pricing_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_type = Column(String(50), unique=True, nullable=False, index=True)
    cost_per_1k_input_tokens = Column(Numeric(precision=12, scale=6), nullable=False, default=0)
    cost_per_1k_output_tokens = Column(Numeric(precision=12, scale=6), nullable=False, default=0)
    # Must be >= 1.0; enforced at service layer
    platform_fee_multiplier = Column(Numeric(precision=5, scale=4), nullable=False, default=1)
    minimum_charge_credits = Column(Numeric(precision=12, scale=6), nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ProcessedWixOrder(Base):
    """Idempotency guard — one row per Wix order ID that has been credited."""
    __tablename__ = "processed_wix_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wix_order_id = Column(String(255), unique=True, nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    credits_added = Column(Numeric(precision=12, scale=6), nullable=False)
    processed_at = Column(DateTime, default=datetime.utcnow)