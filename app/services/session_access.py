"""
Who may read a session's knowledge (slides, course materials and, later,
avatar knowledge) through POST /sessions/{id}/search.

Mirrors the run-start gates in app/api/sessions/api.py. Anonymous callers are
allowed only when guest links are enabled (GUEST_USER_UUID), because anyone
holding a shared session link can already start a guest run of it.
"""

from __future__ import annotations

from typing import Any, Optional


def can_search_session(
    *,
    user: Optional[Any],
    session_owner_id: Any,
    course_owner_id: Optional[Any],
    course_allows_subscribers: bool,
    is_enrolled: bool,
    guest_links_enabled: bool,
) -> bool:
    if user is None:
        return guest_links_enabled
    if user.role == "admin":
        return True
    user_id = str(user.id)
    if user_id == str(session_owner_id) or (
        course_owner_id is not None and user_id == str(course_owner_id)
    ):
        return True
    if not is_enrolled:
        return False
    if user.role == "subscriber":
        return course_allows_subscribers
    return True
