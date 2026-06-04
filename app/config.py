import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    # OpenAI Configuration
    openai_api_key: str = Field("", env="OPENAI_API_KEY")
    
    # Database Configuration
    database_url: str = Field("sqlite:///./profsidekick.db", env="DATABASE_URL")
    
    # Redis Configuration
    redis_url: str = Field("redis://localhost:6379/0", env="REDIS_URL")
    
    # Application Configuration
    app_name: str = Field("ProfSidekick API", env="APP_NAME")
    app_version: str = Field("1.0.0", env="APP_VERSION")
    debug: bool = Field(False, env="DEBUG")
    secret_key: str = Field("dev-secret-key-change-in-production", env="SECRET_KEY")
    
    # File Upload Configuration
    upload_dir: str = Field("./uploads", env="UPLOAD_DIR")
    static_dir: str = Field("./static", env="STATIC_DIR")
    max_file_size: int = Field(52428800, env="MAX_FILE_SIZE")
    allowed_file_types: str = Field(".pptx,.ppt,.pdf,.docx", env="ALLOWED_FILE_TYPES")
    
    # Cloud Storage Configuration (AWS S3)
    use_cloud_storage: bool = Field(False, env="USE_CLOUD_STORAGE")
    aws_access_key_id: str = Field("", env="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field("", env="AWS_SECRET_ACCESS_KEY")
    aws_region: str = Field("us-east-1", env="AWS_REGION")
    s3_bucket_name: str = Field("", env="S3_BUCKET_NAME")
    s3_bucket_region: str = Field("", env="S3_BUCKET_REGION")
    cloudfront_domain: str = Field("", env="CLOUDFRONT_DOMAIN")  # Optional CDN domain
    
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