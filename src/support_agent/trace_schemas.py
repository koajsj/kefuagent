from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class TraceEvent(BaseModel):
    kind: Literal[
        "model", "tool", "audit", "context", "retrieval", "memory", "request", "result", "delivery"
    ]
    label: str
    status: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    execution_id: UUID | None = None
    tool_id: UUID | None = None
    model: str | None = None
    purpose: str | None = None
    provider: str | None = None
    task: str | None = None
    prompt_id: str | None = None
    prompt_version: int | None = None
    prompt_hash: str | None = None
    error_category: str | None = None
    risk: int | None = None
    decision: Literal["allowed", "denied"] | None = None
    policy_version: str | None = None


class TraceCost(BaseModel):
    basis: str
    complete: bool
    unknown_steps: int
    known_subtotals: dict[str, str]
    total: str | None
    currency: str | None


class TraceOut(BaseModel):
    call_id: UUID
    conversation_id: UUID
    request_id: UUID
    status: str
    execution_state: Literal[
        "NOT_STARTED", "RUNNING", "SUCCEEDED", "FAILED", "TIMED_OUT", "INTERRUPTED", "UNKNOWN"
    ]
    lease_expired: bool
    phase: str
    agent_config_id: UUID
    config_version: int
    error_category: str | None
    input_tokens: int | None
    output_tokens: int | None
    usage_complete: bool
    started_at: datetime
    elapsed_ms: int | None
    cost: TraceCost
    events: list[TraceEvent]
    truncated: bool
