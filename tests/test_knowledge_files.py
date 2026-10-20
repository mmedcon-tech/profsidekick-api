"""
Knowledge files and their embedded text: deletion removes both, and legacy
/uploads files move into private storage. Integration test: needs the test
database (see tests/conftest.py).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.database.models import (
    AuditEvent,
    Avatar,
    AvatarConfiguration,
    KnowledgeChunk,
    KnowledgeDocument,
    User,
)
from app.services import avatar_service as avatar_service_module
from app.services.avatar_service import AvatarService
from app.services.legacy_files import migrate_legacy_files
from app.services.personal_template import (
    PERSONAL_TEMPLATE_ID,
    ensure_personal_template,
)
from app.services.private_storage import LocalBackend, PrivateStorage


def _user(db, role):
    user = User(
        id=uuid.uuid4(),
        username=f"u_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed",
        first_name="T",
        last_name="U",
        role=role,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def avatar_with_config(db_session):
    ensure_personal_template(db_session, _user(db_session, "admin").id)
    owner = _user(db_session, "publisher")
    avatar = Avatar(
        id=uuid.uuid4(),
        template_id=PERSONAL_TEMPLATE_ID,
        publisher_id=owner.id,
        name="A",
    )
    db_session.add(avatar)
    db_session.flush()
    config = AvatarConfiguration(id=uuid.uuid4(), avatar_id=avatar.id)
    db_session.add(config)
    db_session.commit()
    return owner, avatar, config


@pytest.fixture
def storage(tmp_path, monkeypatch):
    store = PrivateStorage(LocalBackend(str(tmp_path / "private")))
    monkeypatch.setattr(avatar_service_module, "get_private_storage", lambda: store)
    return store


def test_deleting_a_document_removes_its_file_and_embedded_text(
    db_session, avatar_with_config, storage
):
    owner, avatar, config = avatar_with_config
    stored = storage.save(
        b"protocol", kind="knowledge", owner=str(avatar.id), filename="p.pdf"
    )
    doc = KnowledgeDocument(
        id=uuid.uuid4(),
        avatar_configuration_id=config.id,
        title="P",
        file_path=stored.uri,
    )
    db_session.add(doc)
    db_session.flush()
    source = f"avatar_knowledge:{config.id}:{doc.id}"
    other = KnowledgeChunk(
        id=uuid.uuid4(), source="avatar_knowledge:other:doc", content="keep"
    )
    db_session.add_all(
        [KnowledgeChunk(id=uuid.uuid4(), source=source, content="secret"), other]
    )
    db_session.commit()

    asyncio.run(
        AvatarService().delete_knowledge_document(
            db_session, avatar.id, doc.id, owner.id
        )
    )

    assert db_session.query(KnowledgeChunk).filter_by(source=source).count() == 0
    assert db_session.get(KnowledgeChunk, other.id) is not None
    with pytest.raises(FileNotFoundError):
        storage.read(stored.uri)


def test_legacy_upload_moves_to_private_storage(
    db_session, avatar_with_config, tmp_path
):
    _, avatar, config = avatar_with_config
    upload_dir = tmp_path / "uploads"
    legacy = upload_dir / f"avatar_{avatar.id}" / "1234_notes.pdf"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"old notes")
    doc = KnowledgeDocument(
        id=uuid.uuid4(),
        avatar_configuration_id=config.id,
        title="Notes",
        file_path=str(legacy),
        file_name="notes.pdf",
    )
    db_session.add(doc)
    db_session.commit()
    store = PrivateStorage(LocalBackend(str(tmp_path / "private")))

    dry = migrate_legacy_files(db_session, store, upload_dir=str(upload_dir))
    assert f"knowledge:{doc.id}" in dry.would_move
    assert db_session.get(KnowledgeDocument, doc.id).file_path == str(legacy)

    done = migrate_legacy_files(
        db_session, store, apply=True, delete_originals=True, upload_dir=str(upload_dir)
    )
    moved = db_session.get(KnowledgeDocument, doc.id)
    assert done.moved == [f"knowledge:{doc.id}"]
    assert moved.file_path.startswith(f"private://knowledge/{str(avatar.id).lower()}/")
    assert store.read(moved.file_path) == b"old notes"
    assert not legacy.exists()
    assert (
        db_session.query(AuditEvent)
        .filter_by(
            action="knowledge.file_moved_to_private_storage", entity_id=str(doc.id)
        )
        .count()
        == 1
    )


def test_paths_outside_uploads_are_never_read(db_session, avatar_with_config, tmp_path):
    _, _, config = avatar_with_config
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"x")
    doc = KnowledgeDocument(
        id=uuid.uuid4(),
        avatar_configuration_id=config.id,
        title="X",
        file_path=str(outside),
    )
    db_session.add(doc)
    db_session.commit()
    store = PrivateStorage(LocalBackend(str(tmp_path / "private")))

    report = migrate_legacy_files(
        db_session, store, apply=True, upload_dir=str(tmp_path / "uploads")
    )
    assert any(str(doc.id) in s for s in report.skipped)
    assert db_session.get(KnowledgeDocument, doc.id).file_path == str(outside)
