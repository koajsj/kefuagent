"""Explicit staff-only service desk contracts; visitor identity is never inferred."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from support_agent.schemas import Input, Name, Output

TicketStatus = Literal["open", "in_progress", "resolved", "closed"]
Priority = Literal["low", "normal", "high", "urgent"]


class CustomerFields(Input):
    name: Name
    external_ref: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=2000)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values):
        if any(not v.strip() or len(v) > 40 for v in values):
            raise ValueError("Tags must contain 1..40 characters")
        return list(dict.fromkeys(v.strip() for v in values))


class CustomerCreate(CustomerFields):
    idempotency_key: UUID


class CustomerPatch(Input):
    expected_version: int = Field(ge=1)
    name: Name | None = None
    external_ref: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    tags: list[str] | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)
    status: Literal["active", "archived"] | None = None

    @field_validator("name", "tags", "notes", "status")
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged fields instead of null")
        return value

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values):
        return CustomerCreate.clean_tags(values)


class CustomerOut(CustomerFields, Output):
    id: UUID
    tenant_id: UUID
    status: str
    memory_enabled: bool
    version: int
    created_at: datetime
    updated_at: datetime


class CustomerLink(Input):
    customer_id: UUID
    expected_version: int = Field(ge=1, description="Current conversation version")


class TicketCreate(Input):
    idempotency_key: UUID
    title: str = Field(min_length=1, max_length=160, pattern=r"\S")
    description: str = Field(default="", max_length=4000)
    conversation_id: UUID | None = None
    customer_id: UUID | None = None
    assignee_id: UUID | None = None
    priority: Priority = "normal"
    due_at: datetime | None = None

    @field_validator("due_at")
    @classmethod
    def aware_due(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("An explicit timezone is required")
        return value


class TicketPatch(Input):
    expected_version: int = Field(ge=1)
    status: TicketStatus | None = None
    priority: Priority | None = None
    assignee_id: UUID | None = None
    due_at: datetime | None = None
    note: str = Field(default="", max_length=1000)

    _aware_due = field_validator("due_at")(TicketCreate.aware_due.__func__)

    @field_validator("status", "priority")
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged status/priority instead of null")
        return value


class TicketOut(Output):
    id: UUID
    tenant_id: UUID
    title: str
    description: str
    status: TicketStatus
    priority: Priority
    customer_id: UUID | None
    conversation_id: UUID | None
    assignee_id: UUID | None
    due_at: datetime | None
    resolved_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class TicketEventOut(Output):
    id: UUID
    actor_id: UUID | None
    action: str
    details: dict
    created_at: datetime


class NotificationOut(Output):
    id: UUID
    ticket_id: UUID
    ticket_version: int
    kind: str
    read_at: datetime | None
    created_at: datetime


class CustomerMemoryConsent(Input):
    expected_version: int = Field(ge=1)
    enabled: bool


class CustomerMemoryCreate(Input):
    expected_customer_version: int = Field(ge=1)
    source_message_id: UUID
    content: str = Field(min_length=1, max_length=500)
    lifetime_days: int = Field(ge=1, le=365)


class CustomerMemoryForget(Input):
    expected_version: int = Field(ge=1)


class CustomerMemoryOut(Output):
    source_conversation_id: UUID
    id: UUID
    customer_id: UUID
    source_message_id: UUID
    confirmed_by: UUID
    content: str | None
    expires_at: datetime
    deleted_at: datetime | None
    version: int
    created_at: datetime
