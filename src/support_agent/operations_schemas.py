from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from support_agent.schemas import Input, Output


class OperationsPatch(Input):
    expected_version: int = Field(ge=1)
    assignee_id: UUID | None = None
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    tags: list[str] | None = Field(default=None, max_length=10)
    category: str | None = Field(default=None, max_length=80)

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, tags):
        if tags is not None and (
            len(set(tags)) != len(tags) or any(not t.strip() or len(t) > 40 for t in tags)
        ):
            raise ValueError("Use at most ten distinct nonempty tags of 40 characters")
        return tags


class NoteInput(Input):
    content: str = Field(min_length=1, max_length=4000, pattern=r"\S")


class CollaborationOut(Output):
    id: UUID
    kind: str
    actor_id: UUID
    content: str
    details: dict
    created_at: datetime


class SummaryOut(Output):
    id: UUID
    version: int
    content: str
    source_start_id: UUID
    source_end_id: UUID
    source_count: int
    created_at: datetime
    input_tokens: int | None
    output_tokens: int | None


class OperatorOut(Output):
    id: UUID
    display_name: str


class FeedbackInput(Input):
    rating: Literal["satisfied", "dissatisfied"]
    comment: str | None = Field(default="", max_length=1000)


class FeedbackOut(Output):
    rating: Literal["satisfied", "dissatisfied"]
    comment: str
    created_at: datetime


class ConversationMetrics(Output):
    total: int
    pending: int
    resolved: int
    avg_first_response_seconds: float | None
    avg_resolution_seconds: float | None
    handoff_rate: float | None
    overdue: int
    ai_resolved: int
    ai_to_human: int
    ai_unresolved: int


class AIMetrics(Output):
    retrieval_use_rate: float | None
    valid_citation_rate: float | None = Field(
        description="Source validation, never answer correctness"
    )
    tool_success_rate: float | None


class ModelMetrics(Output):
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    unknown_usage_calls: int


class UsageMetrics(Output):
    calls: int = Field(description="Logical durable turns; per-model counts are provider steps")
    failed: int
    input_tokens: int = Field(description="Known input tokens only")
    output_tokens: int = Field(description="Known output tokens only")
    unknown_usage_calls: int
    known_cost: None = Field(description="No verified prices configured; unknown, not zero")
    unknown_cost_calls: int
    models: list[ModelMetrics]


class TrendMetrics(Output):
    day: str
    conversations: int
    ai: int
    human: int
    calls: int
    input_tokens: int
    output_tokens: int
    unknown_usage_calls: int


class FeedbackMetrics(Output):
    satisfied: int
    dissatisfied: int
    unrated: int
    satisfaction_rate: float | None


class CategoryMetrics(Output):
    category: str
    count: int


class UnresolvedConversation(Output):
    id: UUID
    subject: str


class AnalyticsOut(Output):
    start: datetime
    end: datetime
    conversations: ConversationMetrics
    ai: AIMetrics
    usage: UsageMetrics
    trend: list[TrendMetrics]
    feedback: FeedbackMetrics
    categories: list[CategoryMetrics]
    unresolved: list[UnresolvedConversation]
