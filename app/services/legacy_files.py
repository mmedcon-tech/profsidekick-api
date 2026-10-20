"""
Move knowledge-document and reference-solution files saved before ADR 0010
from the public /uploads mount into private storage.

Dry run by default. With apply=True each file is copied into private storage
and its row updated (one commit per row, with an audit event). The original is
removed only with delete_originals=True, after its row is committed. Files on
S3 (http/https paths) are reported but not moved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import (
    AvatarConfiguration,
    KnowledgeDocument,
    ReferenceSolution,
)
from app.services.audit_service import record_audit_event
from app.services.private_storage import PrivateStorage, is_private_uri

logger = logging.getLogger(__name__)

_KINDS = ((KnowledgeDocument, "knowledge"), (ReferenceSolution, "reference"))


@dataclass
class MigrationReport:
    moved: List[str] = field(default_factory=list)
    would_move: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


def _local_path(file_path: str, upload_root: Path) -> Path | None:
    path = Path(file_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    return path if upload_root in path.parents else None


def migrate_legacy_files(
    db: Session,
    storage: PrivateStorage,
    *,
    apply: bool = False,
    delete_originals: bool = False,
    upload_dir: str | None = None,
) -> MigrationReport:
    report = MigrationReport()
    upload_root = Path(upload_dir or settings.upload_dir).resolve()

    for model, kind in _KINDS:
        rows = db.query(model).filter(model.file_path.isnot(None)).all()
        for row in rows:
            label = f"{kind}:{row.id}"
            if is_private_uri(row.file_path):
                continue
            if row.file_path.startswith(("http://", "https://")):
                report.skipped.append(f"{label} (S3/URL, move manually)")
                continue
            source = _local_path(row.file_path, upload_root)
            if source is None or not source.is_file():
                report.skipped.append(f"{label} (file missing or outside uploads)")
                continue
            if not apply:
                report.would_move.append(label)
                continue

            config = db.get(AvatarConfiguration, row.avatar_configuration_id)
            stored = storage.save(
                source.read_bytes(),
                kind=kind,
                owner=str(config.avatar_id),
                filename=row.file_name or source.name,
                content_type=row.file_type,
            )
            old_path = row.file_path
            row.file_path = stored.uri
            record_audit_event(
                db,
                action=f"{kind}.file_moved_to_private_storage",
                entity_type=model.__tablename__,
                entity_id=row.id,
                data={"checksum_sha256": stored.checksum_sha256},
            )
            try:
                db.commit()
            except Exception:
                db.rollback()
                storage.delete_quietly(stored.uri)
                raise
            if delete_originals:
                Path(source).unlink(missing_ok=True)
            report.moved.append(label)
            logger.info("moved %s from %s", label, old_path)
    return report
