"""
Shared pytest fixtures for backend tests.

Requires a real PostgreSQL + pgvector database.  Set DATABASE_URL before running:

  Local development (docker-compose.test.yml):
    export DATABASE_URL=postgresql://postgres:postgres@localhost:5433/profsidekick_test
    docker compose -f docker-compose.test.yml up -d
    pytest tests/ -v

  CI: DATABASE_URL is injected by the GitHub Actions workflow which spins up
      a pgvector/pgvector:pg16 service container.
"""

import os
import uuid

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

_DATABASE_URL = os.getenv("DATABASE_URL", "")

if not _DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set.\n"
        "Start the test database with:\n"
        "  docker compose -f docker-compose.test.yml up -d\n"
        "Then export:\n"
        "  export DATABASE_URL=postgresql://postgres:postgres@localhost:5433/profsidekick_test"
    )

# Normalise legacy postgres:// scheme used by some hosting providers.
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(_DATABASE_URL)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Enable pgvector, create all tables once per session, drop on teardown."""
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(create_tables):
    """Yield a transactional session that rolls back after each test."""
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
