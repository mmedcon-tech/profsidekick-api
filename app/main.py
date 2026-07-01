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
    errors after new deployments add schema changes.
    """
    from app.config import settings
    db_url = settings.database_url
    # Redact password for safe logging
    try:
        parts = db_url.split("@")
        safe_url = parts[0].rsplit(":", 1)[0] + ":***@" + parts[1] if len(parts) > 1 else db_url
    except Exception:
        safe_url = "(could not parse URL)"
    print(f"[STARTUP] Connecting to database: {safe_url}")

    try:
        from alembic.config import Config
        from alembic import command

        # Locate alembic.ini relative to this file's package root
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        alembic_cfg = Config(os.path.join(base_dir, "alembic.ini"))
        alembic_cfg.set_main_option("script_location", os.path.join(base_dir, "alembic"))

        command.upgrade(alembic_cfg, "head")
        print("DB migrations applied successfully.")
    except Exception as exc:
        # Log but do not crash — a partially migrated DB is better than a dead server.
        print(f"Migration startup error (non-fatal): {exc}")
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
from app.api.assistant.api import router as assistant_router
from app.api.admin.models_api import router as admin_3d_models_router  # W2A
from app.api.avatars.variants import router as avatar_variants_router  # W2A
from app.api.programs.api import router as programs_router            # W2B
from app.api.avatars.courses import router as avatar_courses_router                          # W3
from app.api.avatar_access_codes.api import publisher_router as avatar_codes_publisher_router  # W3
from app.api.avatar_access_codes.api import subscriber_router as avatar_codes_subscriber_router  # W3
from app.api.subscriber.api import router as subscriber_router
from app.api.autograder.api import router as autograder_router
from app.api.autograder.events import router as autograder_events_router
from app.api.autograder.students import router as autograder_students_router
from app.api.sae.invite import router as sae_invite_router
from app.api.sae.publisher import router as sae_publisher_router
from app.api.sae.student import router as sae_student_router
from app.services.gemini_file_cache import load_autograder_cache
from app.api.webhooks.wix import router as wix_router
from app.api.analytics.api import router as analytics_router              # W6
from app.api.assistant.api import router as assistant_router              # W7
from app.api.brightspace.api import router as brightspace_router

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

    # Load autograder static files into memory — raises RuntimeError if any file is missing
    load_autograder_cache()

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
        "https://profsidekick-frontend-3il7.vercel.app",
        "https://profsidekick-autograder.vercel.app",
        "https://profsidekick-ai.vercel.app",
        "https://*.profsidekick-ai.vercel.app",
        "https://myos.sk",
        "https://www.myos.sk",
        "https://*.myos.sk",
        "https://autograder.myos.sk",
        "https://app.myos.sk",
        "https://*.app.myos.sk"
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
    import traceback
    print(f"[UNHANDLED EXCEPTION] {request.method} {request.url}\n{traceback.format_exc()}", flush=True)
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
async def health_check(request: Request):
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "app": settings.app_name,
        "instance": os.getenv("BACKEND_INSTANCE", "unknown"),
        "origin": request.headers.get("origin", "no-origin"),
        "host": request.headers.get("host", "no-host")
    }

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
app.include_router(assistant_router)
app.include_router(admin_3d_models_router)   # W2A: admin 3D model catalog
app.include_router(avatar_variants_router)   # W2A: publisher avatar variants
app.include_router(programs_router)          # W2B: programs system
app.include_router(avatar_courses_router)             # W3: publisher avatar-course links
app.include_router(avatar_codes_publisher_router)     # W3: publisher avatar access code CRUD
app.include_router(avatar_codes_subscriber_router)    # W3: subscriber avatar code redemption
app.include_router(subscriber_router)
app.include_router(autograder_router)
app.include_router(autograder_events_router)
app.include_router(autograder_students_router)
# Self Assessment Exam — isolated from the Math Placement autograder
app.include_router(sae_invite_router)
app.include_router(sae_publisher_router)
app.include_router(sae_student_router)
app.include_router(wix_router)
app.include_router(analytics_router)            # W6: subscriber, publisher, admin analytics
app.include_router(assistant_router)            # W7: multi-role AI navigation assistant
app.include_router(brightspace_router)          # Brightspace LMS integration

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