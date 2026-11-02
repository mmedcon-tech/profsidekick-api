"""Content integrity: immutable SHA-256 bindings for approved content.

* content_hash() is a SHA-256 over a canonical JSON of every field that can
  change what a patient reads (title, body, kind, language, audience,
  applicability, course, transcript-video link).
* Approval pins the hash (approved_sha256). Chunks carry the hash of the
  item text they were cut from. Retrieval only returns chunks whose hash
  equals the item's pinned hash AND whose item still re-hashes to that pin,
  so stale chunks, or a row edited behind the workflow's back, never reach
  the model.
* A before_flush guard refuses any in-place edit of an approved item's
  content fields: an edit must fork a new version (content.new_version).
"""
from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.database.models import CareContentItem

logger = logging.getLogger(__name__)

HASHED_FIELDS = ("title", "body", "kind", "language", "audience", "applicability", "course_id", "video_id")


class ImmutableContentError(RuntimeError):
    pass


def content_hash(item: CareContentItem) -> str:
    doc = {f: (str(getattr(item, f)) if getattr(item, f) is not None else None) for f in HASHED_FIELDS}
    raw = json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify(item: CareContentItem) -> bool:
    return bool(item.approved_sha256) and content_hash(item) == item.approved_sha256


@event.listens_for(Session, "before_flush")
def _guard_approved(session, flush_context, instances):  # noqa: ARG001
    for obj in session.dirty:
        if not isinstance(obj, CareContentItem):
            continue
        st = inspect(obj)
        status_hist = st.attrs.status.history
        was = status_hist.deleted[0] if status_hist.deleted else obj.status
        if was != "approved":
            continue
        changed = [f for f in HASHED_FIELDS if st.attrs[f].history.has_changes()]
        if changed:
            raise ImmutableContentError(
                f"Approved content v{obj.version} is immutable (tried to change {changed}); create a new version")
