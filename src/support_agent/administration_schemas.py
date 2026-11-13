from pydantic import Field

from support_agent.schemas import Input, Output


class RetentionPreview(Input):
    conversations_days: int | None = Field(default=None, ge=2, le=36500)
    visitors_days: int | None = Field(default=None, ge=2, le=36500)
    calls_days: int | None = Field(default=None, ge=2, le=36500)
    audit_days: int | None = Field(default=None, ge=30, le=36500)
    documents: bool = False
    batch_size: int = Field(default=20, ge=1, le=100)


class CapabilityState(Output):
    name: str
    state: str
    detail: str


class AdministrationOut(Output):
    deployment_mode: str
    required_revision: str
    storage_backend: str
    external_models_enabled: bool
    automatic_migrations: bool
    backup_last_verified_at: None
    backup_mode: str
    worker: str
    capabilities: list[CapabilityState]
    retention: dict[str, int | None]
