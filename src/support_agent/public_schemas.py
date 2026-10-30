from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from support_agent.rag_schemas import Citation
from support_agent.schemas import Input, Name, Output


class PublicationCreate(Input):
    agent_config_id: UUID
    name: Name
    public_tool_ids: list[UUID] = Field(default_factory=list, max_length=32)

    @field_validator("public_tool_ids")
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Duplicate tools")
        return value


class PublicationPatch(Input):
    expected_version: int = Field(ge=1)
    enabled: bool


class PublicationOut(Output):
    id: UUID
    agent_config_id: UUID
    name: str
    enabled: bool
    version: int
    agent_version: int
    public_tool_ids: list[UUID]
    available: bool
    requires_republish: bool
    revoked_at: datetime | None
    created_at: datetime


class PublicInfo(Output):
    id: UUID
    name: str
    mode: Literal["demo", "model"]
    version: int


class VisitorOut(Output):
    id: UUID
    token: str
    expires_at: datetime


class VisitorTurn(Input):
    content: str = Field(min_length=1, max_length=2000)
    idempotency_key: UUID


class PublicToolResult(Output):
    name: str
    status: str
    data: dict | None
    error_category: str | None


class PublicMessage(Output):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    citations: list[Citation] = Field(default_factory=list)
    tool_results: list[PublicToolResult] = Field(default_factory=list)


class PublicRun(Output):
    id: UUID
    status: str
    phase: str
    error_category: str | None
