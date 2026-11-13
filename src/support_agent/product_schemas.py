"""Contracts for private knowledge indexing, customer portability and staff drafts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from support_agent.rag_schemas import Citation, SearchHit, SearchInput
from support_agent.schemas import Input, Output


class IndexConfig(Input):
    expected_version: int = Field(ge=0)
    agent_config_id: UUID
    model: str = Field(min_length=1, max_length=120)
    enabled: bool
    rerank: bool = False


class IndexRequest(Input):
    expected_version: int = Field(ge=1)
    rebuild: bool = False


class IndexOut(Output):
    id: UUID
    knowledge_base_id: UUID
    agent_config_id: UUID
    model: str
    version: int
    enabled: bool
    rerank: bool
    state: str
    error_category: str | None
    lease_until: datetime | None
    updated_at: datetime


class IndexStatus(Output):
    configuration: IndexOut | None
    dimensions: int
    eligible_chunks: int
    indexed_chunks: int
    missing_chunks: int
    physical_erasure: Literal["BLOCKED"]


class ExportPreview(Output):
    scope: dict
    scope_digest: str
    policy: Literal["customer_portability_v1"]
    excluded: list[str]
    requires_review: str
    identity_assurance: str
    artifact_expiry_hours: int
    physical_cleanup: str


class RetrievalInput(SearchInput):
    agent_config_id: UUID
    document_ids: list[UUID] = Field(default_factory=list, max_length=50)
    section: str | None = Field(default=None, max_length=200)
    rerank: bool = False


class RetrievalOut(Output):
    call_id: UUID
    keyword: list[SearchHit]
    vector: list[SearchHit]
    fused: list[SearchHit]
    reranked: list[SearchHit]
    final: list[SearchHit]
    stages: dict
    elapsed_ms: int
    index_states: list[dict]


class ExportRequest(Input):
    request_key: UUID
    scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy: Literal["customer_portability_v1"]
    reviewed_subject_content: Literal[True]


class ExportOut(Output):
    id: UUID
    customer_id: UUID
    requested_by: UUID
    status: str
    scope_digest: str
    manifest: dict
    error_category: str | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class DraftCreate(Input):
    agent_config_id: UUID
    request_key: UUID


class DraftAction(Input):
    expected_version: int = Field(ge=1)
    action: Literal["generate", "edit", "reject", "accept_send", "feedback"]
    content: str | None = Field(default=None, min_length=1, max_length=16000)
    feedback: str | None = Field(default=None, min_length=1, max_length=1000)
    confirmed_human_send: bool = False


class DraftOut(Output):
    id: UUID
    conversation_id: UUID
    agent_config_id: UUID
    requested_by: UUID
    status: str
    version: int
    model_call_id: UUID | None
    content: str
    citations: list[Citation]
    warnings: list[str]
    feedback: str | None
    sent_message_id: UUID | None
    error_category: str | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
