from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_serializer, field_validator

from support_agent.schemas import Input, Name, Output


class KnowledgeCreate(Input):
    name: Name
    description: str = Field(default="", max_length=2000)


class KnowledgeOut(KnowledgeCreate, Output):
    id: UUID
    tenant_id: UUID
    status: Literal["active", "deleting"]
    created_at: datetime
    updated_at: datetime


class DocumentOut(Output):
    id: UUID
    knowledge_base_id: UUID
    tenant_id: UUID
    filename: str
    size_bytes: int
    media_type: str
    sha256: str
    status: Literal["pending", "processing", "ready", "failed", "deleting"]
    error_category: str | None
    chunk_count: int
    generation: int
    created_at: datetime
    updated_at: datetime


class CredentialCreate(Input):
    ref: str = Field(min_length=6, max_length=80, pattern=r"^cred_[a-z0-9][a-z0-9_-]*$")
    api_key: SecretStr = Field(min_length=1, max_length=4096)
    enabled: bool = True

    @field_validator("api_key")
    @classmethod
    def safe_header(cls, value):
        raw = value.get_secret_value()
        if not raw.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in raw):
            raise ValueError("Credential must contain printable non-space ASCII characters")
        return value


class CredentialOut(Output):
    id: UUID
    ref: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class SearchInput(Input):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=6, ge=1, le=10)


class SearchHit(Output):
    document_id: UUID
    document_name: str
    chunk_id: UUID
    content: str
    score: float
    page: int | None
    section: str | None
    generation: int
    strategy: Literal["postgres_fts", "postgres_fts_cjk"] = "postgres_fts"


class KnowledgeBindings(Input):
    expected_version: int | None = Field(default=None, ge=1)
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=10)

    @field_validator("knowledge_base_ids")
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Duplicate knowledge bases")
        return value


class ChatInput(Input):
    agent_config_id: UUID
    knowledge_base_ids: list[UUID] = Field(min_length=1, max_length=10)
    content: str = Field(min_length=1, max_length=4000)
    idempotency_key: UUID
    task: Literal["auto", "qa", "extraction", "reasoning"] = "auto"

    @field_validator("knowledge_base_ids")
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Duplicate knowledge bases")
        return value


class Citation(Output):
    document_id: UUID
    document_name: str
    chunk_id: UUID
    quote: str
    page: int | None
    section: str | None


class ChatOut(Output):
    answer: str
    citations: list[Citation]
    grounded: bool = Field(
        description="Only current source membership and verbatim extracts are verified; source truth and semantic sufficiency are not proven"
    )
    grounding_mode: Literal["verified_extracts"] = "verified_extracts"
    status: Literal["answered", "unresolved", "failed", "running"]
    conversation_id: UUID
    call_id: UUID
    request_id: UUID
    error_category: str | None = None


class CallOut(Output):
    id: UUID
    conversation_id: UUID | None
    agent_config_id: UUID
    config_version: int
    model: str
    kind: str
    request_id: UUID
    status: str
    error_category: str | None
    input_tokens: int | None
    output_tokens: int | None
    elapsed_ms: int | None
    attempts: int | None
    steps: list[dict]
    phase: str
    reserved_tokens: int
    usage_complete: bool
    cost: None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("steps")
    def public_steps(self, steps):
        return [
            {
                key: value
                for key, value in step.items()
                if key not in {"credential_id", "credential_stamp"}
            }
            for step in steps
        ]


class ScopeLimits(Output):
    requests_per_minute: int
    concurrent_calls: int
    daily_token_budget: int


class ScopeUsage(Output):
    requests_last_minute: int
    active_calls: int
    tokens_reserved_today: int


class UsageLimitsOut(Output):
    day_timezone: Literal["UTC"]
    limits: dict[Literal["tenant", "user", "agent"], ScopeLimits]
    tenant_usage: ScopeUsage
    current_user_usage: ScopeUsage


class SelectedQuote(Input):
    chunk_id: UUID
    quote: str = Field(min_length=8, max_length=600)


class EvidenceSelection(Input):
    answerable: bool
    citations: list[SelectedQuote] = Field(default_factory=list, max_length=3)
    conflict: bool = False


class ChunkOut(Output):
    id: UUID
    document_id: UUID
    position: int
    generation: int
    content: str
    page: int | None
    section: str | None
