"""
Indexed content is actually retrievable on every path: typed-in knowledge is
indexed, word-based keyword search works, partly embedded documents stay
visible, both chats get passages for the current message, and never-indexed
documents can be found and indexed. Integration test: needs the test database;
OpenAI is never called.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.avatars import api as avatars_api
from app.database.connection import get_db
from app.database.models import (
    Avatar,
    AvatarConfiguration,
    KnowledgeChunk,
    KnowledgeDocument,
    SessionRun,
    SlideChunk,
    User,
)
from app.dependencies.auth import get_current_user
from app.main import app
from app.services import subscriber_chat_service
from app.services.knowledge_indexing import find_unindexed, index_unindexed
from app.services.personal_template import (
    PERSONAL_TEMPLATE_ID,
    ensure_personal_template,
)
from app.services.rag_service import (
    ingest_avatar_knowledge_text,
    knowledge_for_chat,
    retrieve_context,
)

DIM = 1536


def _vec(i: int) -> list:
    v = [0.0] * DIM
    v[i] = 1.0
    return v


def _user(db, role="publisher"):
    u = User(
        id=uuid.uuid4(),
        username=f"u_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        first_name="T",
        last_name="U",
        role=role,
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def twin(db_session, test_user):
    ensure_personal_template(db_session, _user(db_session, "admin").id)
    avatar = Avatar(
        id=uuid.uuid4(),
        template_id=PERSONAL_TEMPLATE_ID,
        publisher_id=test_user.id,
        name="Dr T",
    )
    db_session.add(avatar)
    db_session.flush()
    cfg = AvatarConfiguration(id=uuid.uuid4(), avatar_id=avatar.id)
    db_session.add(cfg)
    db_session.commit()
    db_session.refresh(avatar)
    return avatar, cfg


def _doc(db, cfg, title, text=None):
    doc = KnowledgeDocument(
        id=uuid.uuid4(), avatar_configuration_id=cfg.id, title=title, content_text=text
    )
    db.add(doc)
    db.commit()
    return doc


def test_typed_in_knowledge_is_indexed_and_retrievable(db_session, test_session, twin):
    _, cfg = twin
    doc = _doc(
        db_session,
        cfg,
        "Recovery FAQ",
        "Physiotherapy starts in week two after surgery.",
    )
    with patch(
        "app.services.rag_service._embed", side_effect=lambda t: [_vec(3)] * len(t)
    ):
        assert (
            ingest_avatar_knowledge_text(doc.id, cfg.id, doc.content_text, db_session)
            == 1
        )
        results = retrieve_context(
            test_session.id,
            "physio",
            top_k=3,
            db=db_session,
            avatar_configuration_id=cfg.id,
        )
    with patch("app.services.rag_service._embed", return_value=[_vec(3)]):
        results = retrieve_context(
            test_session.id,
            "when does physio start",
            top_k=3,
            db=db_session,
            avatar_configuration_id=cfg.id,
        )
    assert results[0]["document_title"] == "Recovery FAQ"


def test_upload_endpoint_schedules_indexing_for_typed_text(db_session, test_user, twin):
    avatar, _ = twin
    test_user.role = (
        "publisher"  # the conftest user is a "teacher"; uploads need a publisher
    )
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    app.dependency_overrides[get_current_user] = lambda: test_user
    try:
        with patch.object(avatars_api, "ingest_avatar_knowledge_text_background") as bg:
            with TestClient(app) as c:
                res = c.post(
                    f"/api/publisher/avatars/{avatar.id}"
                    "/configuration/knowledge-documents",
                    data={
                        "title": "Notes",
                        "content_text": "Ice the knee for 20 minutes.",
                    },
                )
        assert res.status_code == 201
        bg.assert_called_once()
        assert bg.call_args.args[2] == "Ice the knee for 20 minutes."
    finally:
        app.dependency_overrides.clear()


def test_keyword_search_matches_words_not_the_whole_question(
    db_session, test_session, twin
):
    _, cfg = twin
    _doc(db_session, cfg, "Protocol")
    db_session.add(
        KnowledgeChunk(
            id=uuid.uuid4(),
            source=f"avatar_knowledge:{cfg.id}:{uuid.uuid4()}",
            content="Ice the knee for 20 minutes, three times a day.",
        )
    )
    db_session.commit()
    results = retrieve_context(
        test_session.id,
        "How long should I ice my knee?",
        top_k=3,
        db=db_session,
        avatar_configuration_id=cfg.id,
    )
    assert [r["content"] for r in results] == [
        "Ice the knee for 20 minutes, three times a day."
    ]


def test_unembedded_chunks_stay_visible_next_to_vector_results(
    db_session, test_session, twin
):
    _, cfg = twin
    embedded_doc = _doc(db_session, cfg, "Embedded")
    failed_doc = _doc(db_session, cfg, "Embedding failed")
    db_session.add_all(
        [
            KnowledgeChunk(
                id=uuid.uuid4(),
                source=f"avatar_knowledge:{cfg.id}:{embedded_doc.id}",
                content="Anatomy of the knee joint",
                embedding=_vec(1),
            ),
            KnowledgeChunk(
                id=uuid.uuid4(),
                source=f"avatar_knowledge:{cfg.id}:{failed_doc.id}",
                content="Swelling usually settles within two weeks",
                embedding=None,
            ),
            SlideChunk(
                id=uuid.uuid4(),
                session_id=test_session.id,
                slide_number=1,
                chunk_index=0,
                content="Slide without an embedding",
                embedding=None,
            ),
        ]
    )
    db_session.commit()
    with patch("app.services.rag_service._embed", return_value=[_vec(1)]):
        results = retrieve_context(
            test_session.id,
            "swelling",
            top_k=5,
            db=db_session,
            avatar_configuration_id=cfg.id,
        )
    titles = {r.get("document_title") for r in results}
    assert "Embedding failed" in titles  # found by keyword despite no embedding
    assert (
        results[0]["content"] == "Anatomy of the knee joint"
    )  # vector match still first


def test_chat_gets_relevant_passages_and_unindexed_docs(db_session, test_session, twin):
    avatar, cfg = twin
    indexed = _doc(
        db_session, cfg, "Indexed", "full text that must not be pasted again"
    )
    _doc(db_session, cfg, "Old upload", "x" * 9000)
    db_session.add(
        KnowledgeChunk(
            id=uuid.uuid4(),
            source=f"avatar_knowledge:{cfg.id}:{indexed.id}",
            content="Bleeding that soaks a pad within an hour needs a call",
            embedding=None,
        )
    )
    db_session.commit()
    db_session.refresh(avatar)

    passages = knowledge_for_chat(
        db_session, "heavy bleeding", session=test_session, avatar=avatar
    )

    assert passages[0].startswith("(from document: Indexed)")
    assert "soaks a pad" in passages[0]
    assert not any("must not be pasted again" in p for p in passages)
    old = [p for p in passages if p.startswith("(from document: Old upload)")]
    assert len(old) == 1 and len(old[0]) < 4100  # capped fallback


def test_member_chat_prompt_uses_passages_for_this_message(
    db_session, test_session, test_user, twin, monkeypatch
):
    avatar, _ = twin
    test_session.avatar_id = avatar.id
    run = SessionRun(
        id=uuid.uuid4(),
        session_run_id=f"r_{uuid.uuid4().hex[:8]}",
        user_id=test_user.id,
        session_id=test_session.id,
        runtime_mode_used="chat",
    )
    db_session.add(run)
    db_session.commit()
    seen = {}

    def fake_knowledge(db, query, *, session=None, avatar=None, **kw):
        seen["query"] = query
        return ["(from document: X)\nretrieved passage"]

    async def fake_create(**kwargs):
        seen["system"] = kwargs["messages"][0]["content"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    monkeypatch.setattr(subscriber_chat_service, "knowledge_for_chat", fake_knowledge)
    monkeypatch.setattr(
        subscriber_chat_service._openai.chat.completions, "create", fake_create
    )

    reply = asyncio.run(
        subscriber_chat_service.send_message(
            db_session, run.session_run_id, test_user.id, "is bleeding normal?"
        )
    )
    assert reply == "ok"
    assert seen["query"] == "is bleeding normal?"
    assert "retrieved passage" in seen["system"]


def test_unindexed_documents_are_found_and_indexed(db_session, twin):
    _, cfg = twin
    doc = _doc(db_session, cfg, "Typed earlier", "Rest the leg on a pillow.")
    _doc(db_session, cfg, "Empty")
    assert doc.id in {d.id for d in find_unindexed(db_session)}

    dry = index_unindexed(db_session)
    assert any("Typed earlier" in line for line in dry.would_index)
    assert any("Empty" in line for line in dry.skipped)

    with patch(
        "app.services.rag_service._embed", side_effect=lambda t: [_vec(2)] * len(t)
    ):
        done = index_unindexed(db_session, apply=True)
    assert any("Typed earlier" in line for line in done.indexed)
    assert doc.id not in {d.id for d in find_unindexed(db_session)}


def test_chunks_without_embeddings_can_be_embedded_later(
    db_session, test_session, twin
):
    from app.services.knowledge_indexing import embed_missing

    _, cfg = twin
    db_session.add(
        KnowledgeChunk(
            id=uuid.uuid4(),
            source=f"avatar_knowledge:{cfg.id}:{uuid.uuid4()}",
            content="Stored while the key was missing",
            embedding=None,
        )
    )
    db_session.commit()
    assert embed_missing(db_session) >= 1  # dry run counts them
    with patch(
        "app.services.rag_service._embed", side_effect=lambda t: [_vec(4)] * len(t)
    ):
        embed_missing(db_session, apply=True)
    assert (
        db_session.query(KnowledgeChunk)
        .filter(KnowledgeChunk.embedding.is_(None))
        .count()
        == 0
    )
