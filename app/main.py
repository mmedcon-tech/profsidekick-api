import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import uvicorn

from app.config import settings
from app.database.connection import close_redis


def _run_migrations() -> None:
    """Apply any pending Alembic migrations at startup.

    Running migrations on startup guarantees the deployed database is always in sync
    with the ORM models, eliminating 'column does not exist' or 'table does not exist'
    errors after new deployments add schema changes. An empty database is created
    from the models and stamped (see app/database/migrate.py). Tests switch this off
    with RUN_MIGRATIONS_ON_STARTUP=false.
    """
    if not settings.run_migrations_on_startup:
        print("Startup migrations disabled (RUN_MIGRATIONS_ON_STARTUP=false).")
        return
    try:
        from app.database.migrate import migrate

        print(f"DB migrations applied successfully ({migrate()}).")
        _ensure_fertility_kb()
    except Exception as exc:
        # Log but do not crash — a partially migrated DB is better than a dead server.
        print(f"Migration startup error (non-fatal): {exc}")


def _ensure_fertility_kb() -> None:
    """Index the IVF Doctor Twin knowledge base if it is missing or out of date."""
    from app.database.connection import SessionLocal
    from app.database.models import FertilityKnowledgeDocument
    from app.services.fertility.knowledge import KB_DOCUMENT_KEY, KB_PATH, ingest_kb, kb_digest

    db = SessionLocal()
    try:
        doc = db.query(FertilityKnowledgeDocument).filter_by(document_key=KB_DOCUMENT_KEY).first()
        current = kb_digest(KB_PATH.read_text(encoding="utf-8"))
        if doc is None or doc.content_sha256 != current:
            print(f"Fertility knowledge base indexed: {ingest_kb(db)}")
    except Exception as exc:  # noqa: BLE001
        print(f"Fertility KB indexing skipped: {exc}")
    finally:
        db.close()


from app.api.sessions.api import router as sessions_router
from app.api.auth.api import router as auth_router
from app.api.users.api import router as users_router
from app.api.prompts.api import router as prompts_router
from app.api.courses.api import router as courses_router
from app.api.course_materials.api import router as course_materials_router
from app.api.avatar_templates.api import router as avatar_templates_router
from app.api.avatars.api import router as avatars_router
from app.api.publisher.api import router as publisher_router
from app.api.subscriptions.api import router as subscriptions_router
from app.api.billing.api import router as billing_router
from app.api.admin.billing_api import router as admin_billing_router
from app.api.admin.analytics_api import router as admin_analytics_router
from app.api.admin.models_api import (
    admin_router as admin_models_router,
    publisher_router as publisher_models_router,
)
from app.api.subscriber.api import router as subscriber_router
from app.api.renderer.api import router as renderer_router
from app.api.voices.api import router as voices_router
from app.api.voices.authorize import router as voice_authorize_router
from app.api.fertility.api import router as fertility_router
from app.api.care.api import router as care_router
from app.api.care.phase3 import router as care_phase3_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    print("Starting ProfSidekick API...")

    # Apply pending DB migrations before accepting traffic
    _run_migrations()

    # Ensure upload/static directories exist
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.static_dir, exist_ok=True)
    os.makedirs(f"{settings.static_dir}/slides", exist_ok=True)
    print("Upload and static directories created/verified")

    yield

    # Shutdown
    print("Shutting down ProfSidekick API...")
    await close_redis()
    print("Redis connection closed")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="""
    ProfSidekick API - AI-powered teaching assistant backend
    
    ## Features
    
    * **Presentation Processing**: Upload and process PowerPoint/PDF presentations
    * **AI Integration**: OpenAI Chat Completions for content analysis and Realtime API tokens
    * **Session Management**: Create and manage teaching sessions with Redis caching
    * **Enhanced AI Capabilities**: Concept explanations and question answering
    * **File Management**: Secure file upload and static file serving
    
    ## Authentication
    
    Currently, this API does not require authentication. In production, implement proper authentication and authorization.
    
    ## Rate Limiting
    
    API calls to OpenAI services are subject to rate limiting. The backend handles retries and errors gracefully.
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

_RID = __import__("re").compile(r"^[A-Za-z0-9-]{8,64}$")


@app.middleware("http")
async def request_id_middleware(request, call_next):
    """Correlation id for support: echoed as X-Request-ID, never contains user data."""
    import uuid as _uuid

    rid = request.headers.get("x-request-id", "")
    rid = rid if _RID.match(rid) else _uuid.uuid4().hex[:16]
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


# CORS middleware - Must be added before other middleware and mounts
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins + [
        "http://localhost:3001", 
        "http://127.0.0.1:3000", 
        "http://192.168.10.174:3001",
        "https://*.up.railway.app",
        "https://*.railway.app",
        "https://profsidekick.vercel.app",
        "https://*.vercel.app",
        "https://profsidekick-frontend-3il7.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Mount static files
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

# Global exception handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with consistent error response format"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "HTTPException",
            "message": exc.detail,
            "status_code": exc.status_code,
            "path": str(request.url)
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions"""
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred" if not settings.debug else str(exc),
            "status_code": 500,
            "path": str(request.url)
        }
    )

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "app": settings.app_name
    }

@app.get("/api/health")
async def api_health():
    """Liveness plus the model provider's configuration state (no live call, no secrets)."""
    from app.services.care import health as care_health

    llm = await care_health.check_llm(live=False)
    return {"status": "healthy", "model_provider": {"ok": llm.get("ok"), "error_kind": llm.get("error_kind")}}

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Welcome to ProfSidekick API",
        "version": settings.app_version,
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health"
    }

# Include API routers
app.include_router(sessions_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(prompts_router)
app.include_router(courses_router)
app.include_router(course_materials_router)
app.include_router(avatar_templates_router)
app.include_router(avatars_router)
app.include_router(publisher_router)
app.include_router(subscriptions_router)
app.include_router(billing_router)
app.include_router(admin_billing_router)
app.include_router(admin_analytics_router)
app.include_router(admin_models_router)
app.include_router(publisher_models_router)
app.include_router(subscriber_router)
from app.api.memory.api import router as memory_router
app.include_router(memory_router)
app.include_router(renderer_router)
app.include_router(voices_router)
app.include_router(voice_authorize_router)
app.include_router(fertility_router)
app.include_router(care_router)
app.include_router(care_phase3_router)

# Add middleware for request logging (optional)
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log requests for debugging (optional)"""
    if settings.debug:
        print(f"Request: {request.method} {request.url}")
    
    response = await call_next(request)
    
    if settings.debug:
        print(f"Response: {response.status_code}")
    
    return response

# Run the application
if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", settings.port))
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=port,
        reload=settings.debug,
        log_level="info" if not settings.debug else "debug"
    ) 