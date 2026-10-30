from datetime import datetime
from uuid import UUID

from pydantic import Field

from support_agent.schemas import Output


class BrowserSessionOut(Output):
    expires_at: datetime


class WorkspaceOut(Output):
    tenant_id: UUID
    user_id: UUID
    role: str
    external_models_enabled: bool


class KnowledgeBindingsOut(Output):
    knowledge_base_ids: list[UUID]
    config_version: int


class ReadinessOut(Output):
    external_models_enabled: bool
    credential_encryption_ready: bool
    public_rate_key_ready: bool
    model_allowed_hosts: list[str]
    enabled_credentials: int
    enabled_agents: int
    demo_agents: int
    web_origin: str
    real_model_verified: bool = Field(
        description="Offline verification cannot establish real model quality"
    )


class StatisticsOut(Output):
    agents: int
    conversations: int
    documents: int
    tool_executions: int
    model_calls: int
    known_input_tokens: int
    known_output_tokens: int
    calls_with_unknown_usage: int
    failed_calls: int
    cost: None = None
