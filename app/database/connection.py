import logging
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import redis.asyncio as aioredis
from app.config import settings

# setting up the logger for diagnostic warning
logger = logging.getLogger(__name__)

# PostgreSQL Database Setup
# Fix postgres:// to postgresql:// for SQLAlchemy 2.0+
database_url = settings.database_url
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    echo=False,  # Set to True only for debugging SQL queries
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Redis Setup
redis_client = None


async def get_redis():
    global redis_client
    if redis_client is None:
        redis_client = aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
        try:
            await redis_client.ping()
        except Exception as e:
            logger.warning(
                f"Redis connection health check failed on initialization at {settings.redis_url}. "
                f"Application performance may degrade. Error: {e}"
            )
    return redis_client


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None


# Database Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Create all tables
def create_tables():
    from app.database.models import (  # noqa: F401 — imports register models with Base
        User,
        Course,
        CourseStudent,
        CourseMaterial,
        Session,
        SessionRun,
        SessionMaterial,
        SavedPrompt,
        SlideChunk,
        KnowledgeChunk,
    )

    # Enable pgvector extension before creating tables that use Vector columns
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
