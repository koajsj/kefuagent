"""Internal human review, distinct from visitor satisfaction and semantic proof."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from support_agent.schemas import Input, Output

FeedbackCategory = Literal[
    "helpful", "not_helpful", "citation_inaccurate", "incomplete", "knowledge_missing", "other"
]
FeedbackStatus = Literal["open", "processing", "reviewed", "resolved"]


class AnswerFeedbackCreate(Input):
    call_id: UUID
    category: FeedbackCategory
    comment: str = Field(default="", max_length=1000)


class AnswerFeedbackPatch(Input):
    expected_revision: int = Field(ge=0)
    expected_status: FeedbackStatus
    status: FeedbackStatus
    resolution_category: (
        Literal[
            "correct",
            "answer_issue",
            "knowledge_issue",
            "retrieval_issue",
            "citation_issue",
            "other",
        ]
        | None
    ) = None
    resolution_note: str = Field(default="", max_length=1000)
    related_chunk_ids: list[UUID] = Field(default_factory=list, max_length=100)


class FeedbackSource(Output):
    chunk_id: UUID
    document_id: UUID
    knowledge_base_id: UUID


class AnswerFeedbackOut(Output):
    id: UUID
    actor_id: UUID
    message_id: UUID
    call_id: UUID
    question_message_id: UUID | None = None
    revision: int = 0
    category: FeedbackCategory
    status: FeedbackStatus
    comment: str
    citation_chunk_ids: list[UUID]
    resolution_category: (
        Literal[
            "correct",
            "answer_issue",
            "knowledge_issue",
            "retrieval_issue",
            "citation_issue",
            "other",
        ]
        | None
    ) = None
    resolution_note: str = ""
    related_chunk_ids: list[UUID] = Field(default_factory=list)
    related_sources: list[FeedbackSource] = Field(default_factory=list)
    created_at: datetime
