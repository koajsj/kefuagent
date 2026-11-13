from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from support_agent.services.costs import ModelPrice


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: SecretStr
    deployment_environment: Literal["development", "production"] = "development"
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
    widget_instance_id: UUID | None = None
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
    document_storage_backend: Literal["local", "s3"] = "local"
    s3_endpoint: str | None = None
    s3_bucket: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    s3_region: str = Field(default="us-east-1", pattern=r"^[a-zA-Z0-9-]{1,64}$")
    s3_prefix: str = Field(default="kefu", pattern=r"^[a-zA-Z0-9_/-]{0,120}$")
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_session_token: SecretStr | None = None

    @field_validator("s3_access_key", "s3_secret_key", "s3_session_token")
    @classmethod
    def safe_storage_secret(cls, value):
        if value is not None and (
            not value.get_secret_value()
            or len(value.get_secret_value()) > 8192
            or any(ord(c) < 33 or ord(c) > 126 for c in value.get_secret_value())
        ):
            raise ValueError(
                "Storage credentials must be nonempty printable ASCII without whitespace"
            )
        return value

    @field_validator("s3_endpoint")
    @classmethod
    def safe_s3_endpoint(cls, value):
        if value is None:
            return value
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
            or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise ValueError(
                "Use an exact HTTPS object storage origin; HTTP is loopback development only"
            )
        return value.rstrip("/")

    @model_validator(mode="after")
    def storage_ready(self):
        if self.document_storage_backend == "s3" and not all(
            (self.s3_endpoint, self.s3_bucket, self.s3_access_key, self.s3_secret_key)
        ):
            raise ValueError("S3 requires endpoint, bucket and deployment-owned credentials")
        if (
            self.document_storage_backend == "s3"
            and self.deployment_environment == "production"
            and not self.s3_endpoint.startswith("https://")
        ):
            raise ValueError("Production object storage requires HTTPS")
        return self

    model_allowed_hosts: list[str] = Field(default_factory=list)
    # Deployment-owned opt-in subset. HTTPS/443 and certificate verification remain mandatory.
    model_private_hosts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def private_model_hosts_approved(self):
        if not set(self.model_private_hosts).issubset(self.model_allowed_hosts):
            raise ValueError(
                "Private model hosts must also be explicitly approved in model_allowed_hosts"
            )
        return self

    model_prices: list[ModelPrice] = Field(default_factory=list, max_length=100)

    @field_validator("model_prices")
    @classmethod
    def distinct_prices(cls, values):
        identities = {(p.provider, p.model, p.endpoint, p.effective_at) for p in values}
        if len(identities) != len(values):
            raise ValueError("Duplicate effective model prices")
        return values

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
