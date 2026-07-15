"""
Application configuration via Pydantic Settings.

Loads and validates all environment variables at startup.
Fails fast with clear errors if required variables are missing.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # --- Webhook Security ---
    webhook_secret: str = Field(
        ...,
        description="Shared secret for x-api-key header validation on inbound webhooks.",
    )
    jwt_secret: str = Field(
        default="super-secret-jwt-key-for-local-dev-only",
        description="Secret key for signing JWTs.",
    )
    admin_pin: str = Field(
        default="9999",
        description="Access PIN for the Admin persona.",
    )
    INTERNAL_API_TOKEN: str = Field(
        default="office-secret-token",
        description="Internal token for system-to-system operations.",
    )
    accounting_pin: str = Field(
        default="1111",
        description="Access PIN for the Accounting persona.",
    )
    operations_pin: str = Field(
        default="2222",
        description="Access PIN for the Operations persona.",
    )
    field_pin: str = Field(
        default="3333",
        description="Access PIN for Field Salesmen.",
    )

    # --- Redis ---
    redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL (Render internal KV store).",
    )

    # --- Google Gemini AI ---
    gemini_api_key: str = Field(
        ..., description="API key for the Google Gemini generative AI service."
    )
    
    # --- Image Processing Constraints ---
    ai_image_max_width: int = Field(
        default=1600,
        description="Maximum pixel width for AI photo uploads.",
    )
    pdf_image_max_width: int = Field(
        default=800,
        description="Maximum pixel width for embedded PDF photos.",
    )

    # --- Application ---
    app_env: str = Field(
        default="dev",
        description="Runtime environment: dev or prod.",
    )
    log_level: str = Field(
        default="DEBUG",
        description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
    )
    quarantine_status: str = Field(
        default="API TEST LAB",
        description="CRM status name used to filter test jobs. Only webhooks with this status are processed.",
    )
    dry_run: bool = Field(
        default=True,
        description="When true, outbound CRM mutations are logged but NOT executed.",
    )
    
    @property
    def get_db_path(self) -> str:
        if self.app_env.lower() == "prod":
            return "data/jobnimbus.db"
        return "data/jobnimbus_dev.db"

    BACKUP_RETENTION_LIMIT: int = Field(
        default=10,
        description="Number of hot SQLite WAL backups to retain before pruning."
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            msg = f"Invalid log_level '{v}'. Must be one of: {allowed}"
            raise ValueError(msg)
        return upper


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached Settings instance.

    Raises pydantic's ValidationError at startup if required
    environment variables are missing or malformed.
    """
    return Settings() # type: ignore


