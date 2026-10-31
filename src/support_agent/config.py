from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: SecretStr
    migration_database_url: SecretStr | None = None
    http_limits_enabled: bool = False
    http_rate_key: SecretStr | None = Field(default=None, min_length=32, max_length=256)
    http_requests_per_minute: int = Field(default=1200, ge=1)
    http_login_per_minute: int = Field(default=30, ge=1)
    http_upload_per_minute: int = Field(default=20, ge=1)
    http_public_per_minute: int = Field(default=120, ge=1)
    http_sse_per_minute: int = Field(default=20, ge=1)
    http_sse_ip_connections: int = Field(default=4, ge=1, le=32)
    http_sse_global_connections: int = Field(default=32, ge=1, le=128)
    session_hours: int = Field(default=12, ge=1, le=168)
    web_origin: str = "http://127.0.0.1:8000"
    allow_external_models: bool = False
    public_rate_key: SecretStr | None = Field(default=None, min_length=32, max_length=256)

    @field_validator("web_origin")
    @classmethod
    def safe_web_origin(cls, value):
        from urllib.parse import urlsplit

        url = urlsplit(value)
        if (
            url.scheme not in {"https", "http"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
            or (url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"})
        ):
            raise ValueError("Use an exact HTTPS Web origin; HTTP is local development only")
        return value.rstrip("/")

    credential_master_key: SecretStr | None = None
    credential_keyring: SecretStr | None = None
    credential_active_key: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    retention_conversations_days: int | None = Field(default=None, ge=2, le=36500)
    retention_visitors_days: int | None = Field(default=None, ge=2, le=36500)
    retention_calls_days: int | None = Field(default=None, ge=2, le=36500)
    retention_audit_days: int | None = Field(default=None, ge=30, le=36500)
    document_storage_root: Path = Path(".local/documents")
    model_allowed_hosts: list[str] = Field(default_factory=list)
    tenant_requests_per_minute: int = Field(default=120, ge=1, le=10000)
    user_requests_per_minute: int = Field(default=60, ge=1, le=10000)
    agent_requests_per_minute: int = Field(default=90, ge=1, le=10000)
    tenant_concurrent_calls: int = Field(default=8, ge=1, le=100)
    user_concurrent_calls: int = Field(default=2, ge=1, le=100)
    agent_concurrent_calls: int = Field(default=4, ge=1, le=100)
    tenant_daily_token_budget: int = Field(default=5000000, ge=1)
    user_daily_token_budget: int = Field(default=3000000, ge=1)
    agent_daily_token_budget: int = Field(default=4000000, ge=1)

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            try:
                url = make_url(value.get_secret_value())
            except ArgumentError:
                raise ValueError("Use a dedicated postgresql+psycopg database") from None
            if url.drivername != "postgresql+psycopg" or not url.database:
                raise ValueError("Use a dedicated postgresql+psycopg database")
        return value
