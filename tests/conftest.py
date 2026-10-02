"""
Shared pytest fixtures for backend tests.

Integration tests require a real PostgreSQL + pgvector *test* database.
Unit tests in tests/unit do not. Set DATABASE_URL before integration tests:

  Local development (docker-compose.test.yml):
    export DATABASE_URL=postgresql://postgres:postgres@localhost:5433/profsidekick_test
    docker compose -f docker-compose.test.yml up -d
    pytest tests/ -v

  CI: DATABASE_URL is injected by the GitHub Actions workflow which spins up
      a pgvector/pgvector:pg16 service container.
"""

import os
import uuid
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database.connection import Base, get_db
from app.database.models import Course, Session as SessionModel, User
from app.dependencies.auth import get_current_user
from app.main import app


# ---------------------------------------------------------------------------
# Database engine
# ---------------------------------------------------------------------------
# Integration fixtures talk to Postgres. They run only when DATABASE_URL names
# a test database (the name must contain "test"). Unit tests under tests/unit
# do not use these fixtures and do not need a database.
# The guard also refuses the dev database so a local pytest run cannot
# drop tables in profsidekick.

_DATABASE_URL = os.getenv("DATABASE_URL", "")

if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

def _database_name(url: str) -> str:
    return urlparse(url).path.lstrip("/").split("?")[0]


def _missing_test_database_message() -> str:
    return (
        "Integration tests need a Postgres URL whose database name contains 'test'.\n"
        "Start the test database with:\n"
        "  docker compose -f docker-compose.test.yml up -d\n"
        "Then export:\n"
        "  export DATABASE_URL=postgresql://postgres:postgres@localhost:5433/profsidekick_test\n"
        "Unit tests do not need this:\n"
        "  pytest tests/unit -q"
    )


engine = None
TestSessionLocal = None
if _DATABASE_URL and "test" in _database_name(_DATABASE_URL).lower():
    engine = create_engine(_DATABASE_URL)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Enable pgvector, create all tables once per session, drop on teardown."""
    if engine is None:
        yield
        return
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(create_tables):
    """Yield a transactional session that rolls back after each test."""
    if TestSessionLocal is None:
        pytest.fail(_missing_test_database_message())
    session = TestSessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def test_user(db_session):
    """A pre-committed User row for use in tests."""
    user = User(
        id=uuid.uuid4(),
        username=f"testuser_{uuid.uuid4().hex[:8]}",
        email=f"test_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed",
        first_name="Test",
        last_name="User",
        role="teacher",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_session(db_session, test_user):
    """A minimal Course + Session row required by the sessions FK chain."""
    course = Course(
        id=uuid.uuid4(),
        course_id=f"course_{uuid.uuid4().hex[:8]}",
        user_id=test_user.id,
        name="Test Course",
    )
    db_session.add(course)
    db_session.flush()

    session = SessionModel(
        id=uuid.uuid4(),
        session_id=f"session_{uuid.uuid4().hex[:8]}",
        user_id=test_user.id,
        course_id=course.id,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


@pytest.fixture
def client(db_session, test_user):
    """FastAPI TestClient with DB and auth overrides applied."""

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
