"""
Retrieval covers everything indexed for a session's twin (slides, course
materials, the avatar's uploaded knowledge) and never returns hidden solution
slides. Integration test: needs the test database; OpenAI is never called.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.sessions import api as sessions_api
from app.database.connection import get_db
from app.database.models import (
    Avatar,
    AvatarConfiguration,
    Course,
    KnowledgeChunk,
    KnowledgeDocument,
    SlideChunk,
    User,
)
from app.dependencies.auth import get_optional_user
from app.main import app
from app.services.personal_template import (
    PERSONAL_TEMPLATE_ID,
    ensure_personal_template,
)
from app.services.rag_service import ingest_session_document, retrieve_context

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


def _avatar_config(db, owner):
    ensure_personal_template(db, _user(db, "admin").id)
    avatar = Avatar(
        id=uuid.uuid4(),
        template_id=PERSONAL_TEMPLATE_ID,
        publisher_id=owner.id,
        name="A",
    )
    db.add(avatar)
    db.flush()
    cfg = AvatarConfiguration(id=uuid.uuid4(), avatar_id=avatar.id)
    db.add(cfg)
    db.commit()
    return avatar, cfg


def _doc_chunk(db, cfg, title, content, embedding=None):
    doc = KnowledgeDocument(
        id=uuid.uuid4(), avatar_configuration_id=cfg.id, title=title
    )
    db.add(doc)
    db.flush()
    db.add(
        KnowledgeChunk(
            id=uuid.uuid4(),
            source=f"avatar_knowledge:{cfg.id}:{doc.id}",
            content=content,
            embedding=embedding,
        )
    )
    db.commit()
    return doc


def test_solution_slides_are_not_indexed(db_session, test_session):
    slides = [
        {
            "slideNumber": 1,
            "content": "Question: integrate x squared",
            "source": "student",
        },
        {
            "slideNumber": 1,
            "content": "Answer: x cubed over three",
            "source": "solution",
        },
    ]
    with patch(
        "app.services.rag_service._embed", side_effect=lambda t: [_vec(0)] * len(t)
    ):
        ingest_session_document(test_session.id, slides, db_session)
    db_session.commit()
    stored = [
        c.content
        for c in db_session.query(SlideChunk).filter_by(session_id=test_session.id)
    ]
    assert stored == ["Question: integrate x squared"]


def test_vector_search_includes_this_twins_knowledge_only(
    db_session, test_session, test_user
):
    _, cfg = _avatar_config(db_session, test_user)
    _, other_cfg = _avatar_config(db_session, test_user)
    _doc_chunk(
        db_session, cfg, "ACL recovery protocol", "Ice the knee for 20 minutes", _vec(5)
    )
    _doc_chunk(db_session, other_cfg, "Other twin", "Other twin secret", _vec(5))
    db_session.add(
        SlideChunk(
            id=uuid.uuid4(),
            session_id=test_session.id,
            slide_number=1,
            chunk_index=0,
            content="Slide about anatomy",
            embedding=_vec(9),
        )
    )
    db_session.commit()

    with patch("app.services.rag_service._embed", return_value=[_vec(5)]):
        results = retrieve_context(
            test_session.id,
            "how long to ice",
            top_k=5,
            db=db_session,
            avatar_configuration_id=cfg.id,
        )

    contents = [r["content"] for r in results]
    assert "Ice the knee for 20 minutes" in contents
    assert "Other twin secret" not in contents
    top = results[0]
    assert top["source"] == "avatar_knowledge"
    assert top["document_title"] == "ACL recovery protocol"
    assert "_tag" not in top


def test_without_an_avatar_nothing_from_avatar_knowledge(
    db_session, test_session, test_user
):
    _, cfg = _avatar_config(db_session, test_user)
    _doc_chunk(db_session, cfg, "Doc", "Ice the knee", _vec(5))
    with patch("app.services.rag_service._embed", return_value=[_vec(5)]):
        results = retrieve_context(test_session.id, "ice", top_k=5, db=db_session)
    assert all(r["source"] != "avatar_knowledge" for r in results)


def test_keyword_fallback_finds_avatar_knowledge(db_session, test_session, test_user):
    _, cfg = _avatar_config(db_session, test_user)
    _doc_chunk(db_session, cfg, "FAQ", "Physio starts in week two", None)
    results = retrieve_context(
        test_session.id,
        "physio",
        top_k=5,
        db=db_session,
        avatar_configuration_id=cfg.id,
    )
    assert [(r["source"], r["document_title"]) for r in results] == [
        ("avatar_knowledge", "FAQ")
    ]


def test_legacy_solution_chunks_are_dropped(db_session, test_session):
    for i, text in enumerate(["Question two: derive f", "Answer two: f prime is 2x"]):
        db_session.add(
            SlideChunk(
                id=uuid.uuid4(),
                session_id=test_session.id,
                slide_number=2,
                chunk_index=i,
                content=text,
                embedding=None,
            )
        )
    db_session.commit()
    results = retrieve_context(
        test_session.id,
        "two",
        top_k=5,
        db=db_session,
        solution_texts=["Answer two: f prime is 2x"],
        student_texts=["Question two: derive f"],
    )
    assert [r["content"] for r in results] == ["Question two: derive f"]


def test_search_endpoint_returns_avatar_knowledge_but_never_solutions(
    db_session, test_session, test_user
):
    avatar, cfg = _avatar_config(db_session, test_user)
    _doc_chunk(
        db_session, cfg, "Clinic FAQ", "Call the clinic if bleeding is heavy", None
    )
    test_session.avatar_id = avatar.id
    test_session.slides_details = [
        {"slideNumber": 1, "content": "Bleeding question", "source": "student"},
        {"slideNumber": 1, "content": "Bleeding answer key", "source": "solution"},
    ]
    db_session.add(
        SlideChunk(
            id=uuid.uuid4(),
            session_id=test_session.id,
            slide_number=1,
            chunk_index=0,
            content="Bleeding answer key",
            embedding=None,
        )
    )
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: (yield db_session)
    app.dependency_overrides[get_optional_user] = lambda: test_user
    try:
        with TestClient(app) as c:
            res = c.post(
                f"/api/sessions/{test_session.session_id}/search",
                json={"query": "bleeding"},
            )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    contents = [r["content"] for r in res.json()["results"]]
    assert "Call the clinic if bleeding is heavy" in contents
    assert "Bleeding answer key" not in contents
