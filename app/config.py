import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    # OpenAI Configuration
    openai_api_key: str = Field("", env="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4.1", env="OPENAI_MODEL")

    # Gemini Configuration (used by the Math Autograder — direct Google API)
    # Each tier has its own API key so each can upload static PDFs under its own
    # Google project and reference them via Files API URIs without cross-project 403s.
    gemini_pro_api_key: str = Field("", env="GEMINI_PRO_API_KEY")
    gemini_flash_api_key: str = Field("", env="GEMINI_FLASH_API_KEY")
    gemini_free_api_key: str = Field("", env="GEMINI_FREE_API_KEY")
    # Legacy key kept for deployments that have not yet renamed their env var.
    gemini_api_key: str = Field("", env="GEMINI_API_KEY")
    gemini_model: str = Field("gemini-2.5-pro", env="GEMINI_MODEL")
    gemini_flash_model: str = Field("gemini-2.5-flash", env="GEMINI_FLASH_MODEL")
    # LLM provider routing. "default" = full chain. "openai_only" = OpenAI only (debug).
    llm_provider_mode: str = Field("default", env="LLM_PROVIDER_MODE")

    # Vertex AI Configuration — uses Application Default Credentials (no API key).
    # Local dev: run `gcloud auth application-default login` once.
    # CI/prod: set GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON path,
    #          or use Workload Identity (GKE / Cloud Run).
    google_cloud_project: str = Field("", env="GOOGLE_CLOUD_PROJECT")
    vertex_ai_location: str = Field("us-central1", env="VERTEX_AI_LOCATION")
    vertex_ai_model: str = Field("gemini-2.5-pro", env="VERTEX_AI_MODEL")
    # Optional GCS bucket for caching static PDFs in Vertex AI requests.
    # If set: static PDFs are uploaded once to gs://<bucket>/autograder/ and
    # referenced via Part.from_uri() — cheaper than inline base64 on large PDFs.
    # If unset or upload fails: falls back to inline base64 (always works).
    gcs_static_bucket: str = Field("", env="GCS_STATIC_BUCKET")

    # Database Configuration
    database_url: str = Field("sqlite:///./profsidekick.db", env="DATABASE_URL")
    
    # Redis Configuration
    redis_url: str = Field("redis://localhost:6379/0", env="REDIS_URL")
    
    # Application Configuration
    app_name: str = Field("ProfSidekick API", env="APP_NAME")
    app_version: str = Field("1.0.0", env="APP_VERSION")
    debug: bool = Field(False, env="DEBUG")
    secret_key: str = Field("dev-secret-key-change-in-production", env="SECRET_KEY")

    # Temporary demo layer (see app/services/demo_service.py) — OFF by default.
    # When on, the chat + realtime memory-fetch call sites skip the UserMemory
    # DB query entirely and use demo_service.get_demo_memories() (a hardcoded
    # list) instead, so Teaching Mode appears to "remember" a scripted mistake
    # deterministically — no DB writes, no DB timing/ranking dependency.
    # Safe to delete entirely once real mistake-detection/memory ships.
    demo_mode: bool = Field(False, env="DEMO_MODE")
    
    # File Upload Configuration
    upload_dir: str = Field("./uploads", env="UPLOAD_DIR")
    static_dir: str = Field("./static", env="STATIC_DIR")
    max_file_size: int = Field(31457280, env="MAX_FILE_SIZE")  # 30 MB
    allowed_file_types: str = Field(".pptx,.ppt,.pdf,.docx", env="ALLOWED_FILE_TYPES")
    
    # Cloud Storage Configuration (AWS S3)
    use_cloud_storage: bool = Field(False, env="USE_CLOUD_STORAGE")
    aws_access_key_id: str = Field("", env="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field("", env="AWS_SECRET_ACCESS_KEY")
    aws_region: str = Field("us-east-1", env="AWS_REGION")
    s3_bucket_name: str = Field("", env="S3_BUCKET_NAME")
    s3_bucket_region: str = Field("", env="S3_BUCKET_REGION")
    cloudfront_domain: str = Field("", env="CLOUDFRONT_DOMAIN")  # Optional CDN domain

    # Cloudflare R2 Storage (SAE submission PDFs)
    r2_account_id: str = Field("", env="R2_ACCOUNT_ID")
    r2_access_key_id: str = Field("", env="R2_ACCESS_KEY_ID")
    r2_secret_access_key: str = Field("", env="R2_SECRET_ACCESS_KEY")
    r2_bucket_name: str = Field("", env="R2_BUCKET_NAME")
    r2_public_url: str = Field("", env="R2_PUBLIC_URL")
    r2_api_token: str = Field("", env="R2_API_TOKEN")

    # ElevenLabs Configuration — server-side voice catalog lookups / reachability
    # checks for the dual voice pipeline (see voice_catalog_service.py). The
    # frontend BFF has its own ELEVENLABS_API_KEY for actual synthesis calls;
    # this is a separate, backend-side use of the same provider account.
    elevenlabs_api_key: str = Field("", env="ELEVENLABS_API_KEY")

    # Poppler path (required on Windows for pdf2image; leave empty on Linux/Docker where poppler-utils is in PATH)
    poppler_path: Optional[str] = Field(None, env="POPPLER_PATH")

    # Guest session user — UUID of the users row that owns unauthenticated (shared-link) session runs.
    # The row must exist in the database before shared-link sessions can be used.
    # If unset or the row is missing, /run/start/guest and /run/stop/guest return HTTP 503.
    guest_user_uuid: Optional[str] = Field(None, env="GUEST_USER_UUID")

    # Server Configuration
    host: str = Field("0.0.0.0", env="HOST")
    port: int = Field(8000, env="PORT")
    
    # Security
    cors_origins: str = Field("http://localhost:3000,https://profsidekick.vercel.app,https://profsidekick-frontend-3il7.vercel.app", env="CORS_ORIGINS")
    admin_secret: str = Field("", env="ADMIN_SECRET")
    credits_per_usd: int = Field(100, env="CREDITS_PER_USD")

    # Brightspace (D2L Valence) OAuth integration
    brightspace_client_id: str = Field("", env="BRIGHTSPACE_CLIENT_ID")
    brightspace_client_secret: str = Field("", env="BRIGHTSPACE_CLIENT_SECRET")
    brightspace_redirect_uri: str = Field("", env="BRIGHTSPACE_REDIRECT_URI")

    # Wix payment webhook
    # WIX_WEBHOOK_SECRET: shared secret set in your Wix Automation action header.
    # Leave empty in dev to skip secret verification (logs a warning).
    wix_webhook_secret: str = Field("", env="WIX_WEBHOOK_SECRET")
    # WIX_PRODUCT_CREDIT_MAP: JSON mapping Wix product IDs → credit amounts.
    # Example: {"prod_abc123": 500, "prod_def456": 1000}
    wix_product_credit_map: str = Field("{}", env="WIX_PRODUCT_CREDIT_MAP")
    
    # Email Configuration
    # For production, use EMAIL_SERVICE=sendgrid or resend (API-based, no SMTP ports)
    # For development, use EMAIL_SERVICE=smtp
    email_service: str = Field("smtp", env="EMAIL_SERVICE")  # smtp, sendgrid, resend
    
    # SMTP Configuration (for local development)
    smtp_host: str = Field("smtp.gmail.com", env="SMTP_HOST")
    smtp_port: int = Field(587, env="SMTP_PORT")
    smtp_username: str = Field("", env="SMTP_USERNAME")
    smtp_password: str = Field("", env="SMTP_PASSWORD")
    smtp_from_email: str = Field("", env="SMTP_FROM_EMAIL")
    smtp_from_name: str = Field("ProfSidekick", env="SMTP_FROM_NAME")
    
    # SendGrid Configuration (recommended for production)
    sendgrid_api_key: str = Field("", env="SENDGRID_API_KEY")
    
    # Resend Configuration (alternative for production)
    resend_api_key: str = Field("", env="RESEND_API_KEY")
    
    # Email Verification & Approval
    professor_approval_emails: str = Field("", env="PROFESSOR_APPROVAL_EMAILS")
    frontend_url: str = Field("http://localhost:3000", env="FRONTEND_URL")
    autograder_frontend_url: str = Field("http://localhost:3000", env="AUTOGRADER_FRONTEND_URL")
    # DEV ONLY — set BYPASS_EMAIL_VERIFICATION=false in production
    bypass_email_verification: bool = Field(True, env="BYPASS_EMAIL_VERIFICATION")
    
    @field_validator('allowed_file_types')
    @classmethod
    def parse_allowed_file_types(cls, v) -> List[str]:
        if isinstance(v, str):
            return [ext.strip() for ext in v.split(',') if ext.strip()]
        return v if isinstance(v, list) else [v]
    
    @field_validator('cors_origins')
    @classmethod
    def parse_cors_origins(cls, v) -> List[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(',') if origin.strip()]
        return v if isinstance(v, list) else [v]
    
    @field_validator('professor_approval_emails')
    @classmethod
    def parse_professor_emails(cls, v) -> List[str]:
        if isinstance(v, str):
            return [email.strip() for email in v.split(',') if email.strip()]
        return v if isinstance(v, list) else [v]
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        env_file_encoding = 'utf-8'
        
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure upload and static directories exist
        os.makedirs(self.upload_dir, exist_ok=True)
        os.makedirs(self.static_dir, exist_ok=True)
        os.makedirs(f"{self.static_dir}/slides", exist_ok=True)


# Global settings instance
settings = Settings() 