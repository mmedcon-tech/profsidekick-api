import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import uvicorn

from app.config import settings
from app.database.connection import close_redis, create_tables
from app.api.sessions.api import router as sessions_router
from app.api.auth.api import router as auth_router
from app.api.users.api import router as users_router
from app.api.prompts.api import router as prompts_router
from app.api.courses.api import router as courses_router
from app.api.course_materials.api import router as course_materials_router
from app.api.billing.api import router as billing_router
from app.api.admin.billing_api import router as admin_billing_router
from app.api.webhooks.wix import router as wix_webhook_router
from app.api.professor.api import router as professor_router
from app.api.assistant.api import router as assistant_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    print("Starting ProfSidekick API...")

    # Create database tables
    create_tables()
    print("Database tables created/verified")

    # Ensure directories exist
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
    lifespan=lifespan,
)

# CORS middleware - Must be added before other middleware and mounts
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins
    + [
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://192.168.10.174:3001",
        "https://*.up.railway.app",
        "https://*.railway.app",
        "https://profsidekick.vercel.app",
        "https://*.vercel.app",
        "https://profsidekick-frontend-3il7.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
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
            "path": str(request.url),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions"""
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": (
                "An unexpected error occurred" if not settings.debug else str(exc)
            ),
            "status_code": 500,
            "path": str(request.url),
        },
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "app": settings.app_name,
    }


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Welcome to ProfSidekick API",
        "version": settings.app_version,
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }


# Include API routers
app.include_router(sessions_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(prompts_router)
app.include_router(courses_router)
app.include_router(course_materials_router)
app.include_router(billing_router)
app.include_router(admin_billing_router)
app.include_router(wix_webhook_router)
app.include_router(professor_router)
app.include_router(assistant_router)


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
        log_level="info" if not settings.debug else "debug",
    )
