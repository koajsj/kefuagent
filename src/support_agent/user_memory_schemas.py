from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from support_agent.schemas import Input, Output


class ConsentInput(Input):
    enabled: bool


class ConsentOut(BaseModel):
    enabled: bool
    version: int


class MemoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    source_message_id: UUID
    quote: str = Field(min_length=1, max_length=300)
    expected_version: int | None = Field(default=None, ge=1)
    retention_days: int = Field(default=30, ge=1, le=365)


class MemoryOut(Output):
    id: UUID
    memory_key: str
    quote: str
    source_conversation_id: UUID
    source_message_id: UUID
    version: int
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
