from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: SecretStr
    migration_database_url: SecretStr | None = None
    session_hours: int = Field(default=12, ge=1, le=168)

    credential_master_key: SecretStr | None = None
    document_storage_root: Path = Path(".local/documents")
    model_allowed_hosts: list[str] = Field(default_factory=list)

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
