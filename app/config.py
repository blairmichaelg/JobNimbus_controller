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
    office_internal_token: str = Field(
        default="office-secret-token",
        description="Global access token for backend office endpoints.",
    )
    field_internal_token: str = Field(
        default="field-secret-token",
        description="Global access token for backend field endpoints.",
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

    # --- Application ---
    app_env: str = Field(
        default="development",
        description="Runtime environment: development, staging, production.",
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
    DB_PATH: str = Field(
        default="data/truck_server.db",
        description="Path to the local SQLite WAL database."
    )
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

from fastapi import Header, Cookie, HTTPException

async def verify_office_token(
    x_internal_token: str | None = Header(None, alias="x-internal-token"),
    office_auth: str | None = Cookie(None)
):
    """Dependency to verify corporate internal routes."""
    valid_token = get_settings().office_internal_token
    if x_internal_token == valid_token or office_auth == valid_token:
        return
    raise HTTPException(status_code=401, detail="Invalid internal token")

async def verify_field_token(x_internal_token: str = Header(...)):
    """Dependency to verify field internal routes."""
    if x_internal_token != get_settings().field_internal_token:
        raise HTTPException(status_code=401, detail="Invalid internal token")
