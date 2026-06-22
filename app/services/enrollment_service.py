"""W3: Post-subscription enrollment helper (R51, R18, R57).

Called whenever an avatar subscription is created — either via direct
subscription or via avatar access code redemption — to auto-enroll the
subscriber in all courses and programs linked to the avatar.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.database.models import CourseStudent, ProgramMembership

logger = logging.getLogger(__name__)


def enroll_from_avatar(subscriber_id: UUID, avatar_id: UUID, db: Session) -> Dict[str, Any]:
    """
    Enroll a subscriber in all courses and programs linked to an avatar.

    Idempotent — skips items where enrollment already exists.
    Uses db.flush() so the caller controls the commit boundary.

    Returns a summary of what was added:
        {"courses_enrolled": [UUID, ...], "programs_enrolled": [UUID, ...]}
    """
    from app.database.models.avatar_courses import AvatarCourse
    from app.database.models import ProgramAvatar

    avatar_course_links: List[AvatarCourse] = (
        db.query(AvatarCourse).filter(AvatarCourse.avatar_id == avatar_id).all()
    )

    courses_enrolled: List[UUID] = []
    for ac in avatar_course_links:
        already_enrolled = (
            db.query(CourseStudent)
            .filter(
                CourseStudent.user_id == subscriber_id,
                CourseStudent.course_id == ac.course_id,
            )
            .first()
        )
        if not already_enrolled:
            db.add(
                CourseStudent(
                    user_id=subscriber_id,
                    course_id=ac.course_id,
                    enrollment_date=datetime.utcnow(),
                )
            )
            courses_enrolled.append(ac.course_id)

    program_avatar_links: List[Any] = (
        db.query(ProgramAvatar).filter(ProgramAvatar.avatar_id == avatar_id).all()
    )

    programs_enrolled: List[UUID] = []
    for pa in program_avatar_links:
        already_member = (
            db.query(ProgramMembership)
            .filter(
                ProgramMembership.program_id == pa.program_id,
                ProgramMembership.user_id == subscriber_id,
            )
            .first()
        )
        if not already_member:
            db.add(
                ProgramMembership(
                    program_id=pa.program_id,
                    user_id=subscriber_id,
                    role="member",
                    joined_at=datetime.utcnow(),
                )
            )
            programs_enrolled.append(pa.program_id)

    if courses_enrolled or programs_enrolled:
        db.flush()

    logger.info(
        "Enrolled subscriber %s via avatar %s: %d course(s), %d program(s)",
        subscriber_id,
        avatar_id,
        len(courses_enrolled),
        len(programs_enrolled),
    )
    return {
        "courses_enrolled": courses_enrolled,
        "programs_enrolled": programs_enrolled,
    }
