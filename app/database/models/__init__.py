"""
models package — re-exports every ORM class and Base so that any existing
import of the form `from app.database.models import X` continues to work
unchanged after the monolithic models.py was replaced by this package.

Import order matters: tables with FK targets must be imported before tables
that reference them so SQLAlchemy's mapper registry sees the target first.
"""

from app.database.connection import Base  # noqa: F401

# Enums (no FK dependencies)
from app.database.models.enums import (  # noqa: F401
    MaterialType,
    ProcessingStatus,
    SessionRunStatus,
)

# Core entities
from app.database.models.users import User, UserAgreement  # noqa: F401
from app.database.models.courses import (  # noqa: F401
    Course,
    CourseMaterial,
    CourseStudent,
    CourseAccessCode,
)

# Templates — must come before Avatar (Avatar.template_id → avatar_templates)
from app.database.models.templates import (  # noqa: F401
    AvatarTemplate,
    AvatarTemplateVersion,
    AvatarTemplateRole,
)

# Avatars — must come before Sessions (Session.avatar_id → avatars)
from app.database.models.avatars import (  # noqa: F401
    Avatar,
    PublisherAvatarProfile,
    AvatarConfiguration,
)

# W2A: 3-D models and avatar variants
# Avatar3DModel must come before AvatarVariant (FK: AvatarVariant.model_3d_id → avatar_3d_models)
# Both must come after Avatar (FK: AvatarVariant.avatar_id → avatars)
from app.database.models.variants import (  # noqa: F401
    Avatar3DModel,
    AvatarVariant,
)

# W3: Avatar–Course join + access codes
# Both depend on Avatar and Course (already imported above)
from app.database.models.avatar_courses import AvatarCourse  # noqa: F401
from app.database.models.avatar_access_codes import (  # noqa: F401
    AvatarAccessCode,
    AvatarAccessCodeRedemption,
)

# Sessions — depend on User, Course, Avatar, AvatarTemplateRole, AvatarVariant
from app.database.models.sessions import (  # noqa: F401
    Session,
    SessionRun,
    SessionMaterial,
)

# W2B: Programs system
# Program must come before ProgramMembership/ProgramAvatar/ProgramCourse
# All must come after User, Avatar, Course
from app.database.models.programs import (  # noqa: F401
    Program,
    ProgramMembership,
    ProgramAvatar,
    ProgramCourse,
)

# Billing
from app.database.models.billing import (  # noqa: F401
    CreditBalance,
    AccessCode,
    AccessCodeRedemption,
    UsageRecord,
    PricingConfig,
    ProcessedWixOrder,
    AutoTopUpSettings,
)

# RAG / knowledge
from app.database.models.rag import (  # noqa: F401
    SlideChunk,
    KnowledgeChunk,
    KnowledgeDocument,
    Rubric,
    ReferenceSolution,
    SavedPrompt,
    UserMemory,
)

# Publisher learning / assistant (W7: models renamed to Assistant*)
from app.database.models.assistant import (  # noqa: F401
    AssistantConversation,
    AssistantMessage,
    # backward-compatible aliases — same objects, old names preserved
    PublisherConversation,
    PublisherMessage,
    FeedbackPreference,
    PublisherPreference,
    AvatarSubscription,
    PublisherMessageFeedback,
    PublisherResponseEdit,
)

# Session feedback (W1B stubs)
from app.database.models.feedback import (  # noqa: F401
    SessionFeedback,
    TranscriptFeedback,
    SessionPersonaSwitch,
)

# W6: Progress tracking and assessment results
# Must come after SessionRun (FK: session_run_id → session_runs) and Course, User
from app.database.models.progress import (  # noqa: F401
    SubscriberCourseProgress,
    AssessmentResult,
)

# Third-party integration tokens — depends on User only
from app.database.models.integrations import BrightspaceToken  # noqa: F401

# Dormant v1 stubs — keep last; no other models depend on them
from app.database.models.legacy import ProfessorPersona  # noqa: F401

# Autograder
from app.database.models.autograder import (  # noqa: F401
    Student,
    AutograderSubmission,
)

# SAE
from app.database.models.sae import (  # noqa: F401
    SAEStudent,
    SAEInvitationToken,
    SAESubmission,
)

__all__ = [
    "Base",
    # enums
    "MaterialType",
    "ProcessingStatus",
    "SessionRunStatus",
    # users
    "User",
    "UserAgreement",
    # courses
    "Course",
    "CourseMaterial",
    "CourseStudent",
    "CourseAccessCode",
    # templates
    "AvatarTemplate",
    "AvatarTemplateVersion",
    "AvatarTemplateRole",
    # avatars
    "Avatar",
    "PublisherAvatarProfile",
    "AvatarConfiguration",
    # variants (W2A)
    "Avatar3DModel",
    "AvatarVariant",
    # avatar–course join + access codes (W3)
    "AvatarCourse",
    "AvatarAccessCode",
    "AvatarAccessCodeRedemption",
    # sessions
    "Session",
    "SessionRun",
    "SessionMaterial",
    # programs (W2B)
    "Program",
    "ProgramMembership",
    "ProgramAvatar",
    "ProgramCourse",
    # billing
    "CreditBalance",
    "AccessCode",
    "AccessCodeRedemption",
    "UsageRecord",
    "PricingConfig",
    "ProcessedWixOrder",
    "AutoTopUpSettings",
    # rag
    "SlideChunk",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "Rubric",
    "ReferenceSolution",
    "SavedPrompt",
    "UserMemory",
    # assistant (W7 renamed; old names kept as aliases)
    "AssistantConversation",
    "AssistantMessage",
    "PublisherConversation",
    "PublisherMessage",
    "FeedbackPreference",
    "PublisherPreference",
    "AvatarSubscription",
    "PublisherMessageFeedback",
    "PublisherResponseEdit",
    # feedback
    "SessionFeedback",
    "TranscriptFeedback",
    "SessionPersonaSwitch",
    # progress + assessment (W6)
    "SubscriberCourseProgress",
    "AssessmentResult",
    # integrations
    "BrightspaceToken",
    # legacy
    "ProfessorPersona",
    # autograder
    "Student",
    "AutograderSubmission",
    # sae
    "SAEStudent",
    "SAEInvitationToken",
    "SAESubmission",
]
