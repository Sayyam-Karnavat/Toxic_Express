"""Application settings, loaded from environment variables / .env."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Toxic-Express"
    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # URLs
    frontend_url: str = "http://localhost:5173"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # Database
    database_url: str = "postgresql+asyncpg://toxic:toxic@localhost:5433/toxic_express"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    # Set when connecting through PgBouncer / Neon pooled endpoint (transaction pooling).
    db_use_pgbouncer: bool = False

    # Redis
    redis_url: str = "redis://localhost:6380/0"

    # Auth
    jwt_secret: SecretStr = SecretStr("dev-insecure-change-me-dev-insecure-change-me")
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    cookie_secure: bool = False
    cookie_domain: str | None = None
    email_verify_ttl_hours: int = 24
    password_reset_ttl_minutes: int = 60

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_redirect_uri: str = "http://localhost:5173/api/v1/auth/google/callback"

    # Object storage (Cloudflare R2 in production, any S3-compatible store locally)
    s3_endpoint_url: str = "http://localhost:8333"
    s3_access_key: str = "devaccesskey"
    s3_secret_key: SecretStr = SecretStr("devsecretkey123")
    s3_region: str = "auto"
    s3_bucket_raw: str = "te-uploads-raw"
    s3_bucket_public: str = "te-media-public"
    media_public_base_url: str = "http://localhost:8333/te-media-public"
    upload_url_ttl_seconds: int = 600

    # Media rules
    media_min_account_age_hours: int = 24
    media_require_verified_email: bool = True
    ffmpeg_path: str | None = None

    # Moderation
    openai_api_key: SecretStr = SecretStr("")
    moderation_timeout_seconds: float = 4.0
    moderation_blocklist_path: str = "moderation_blocklist.txt"

    # Email
    resend_api_key: SecretStr = SecretStr("")
    email_from: str = "Toxic-Express <no-reply@toxic-express.app>"

    # Background jobs. When true, jobs run inline instead of via the arq queue (tests only).
    tasks_eager: bool = False

    # Observability
    sentry_dsn: str = ""

    @model_validator(mode="after")
    def _check_production_secrets(self) -> "Settings":
        if self.env == "prod":
            secret = self.jwt_secret.get_secret_value()
            if len(secret) < 32 or "insecure" in secret:
                raise ValueError("JWT_SECRET must be a strong random value (>= 32 chars) in prod")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in prod")
            if not self.openai_api_key.get_secret_value():
                raise ValueError("OPENAI_API_KEY is required in prod (content moderation)")
            if self.tasks_eager:
                raise ValueError("TASKS_EAGER must be false in prod")
        return self

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
