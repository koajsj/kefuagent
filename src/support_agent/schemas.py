from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

State = Literal["active", "inactive"]
Role = Literal["admin", "member"]
Name = Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]


class Input(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False, hide_input_in_errors=True
    )


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(Input):
    login: str = Field(min_length=3, max_length=160, pattern=r"^[a-z0-9][a-z0-9@._+-]*$")
    display_name: Name
    password: SecretStr = Field(min_length=12, max_length=128)


class UserOut(Output):
    id: UUID
    login: str
    display_name: str
    status: State
    is_platform_admin: bool
    created_at: datetime


class UserStatus(Input):
    status: State


class Login(Input):
    login: str = Field(min_length=1, max_length=160)
    password: SecretStr = Field(min_length=1, max_length=128)


class TokenOut(Output):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime


class TenantCreate(Input):
    name: str = Field(min_length=1, max_length=160, pattern=r"\S")
    slug: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    admin_user_id: UUID


class TenantPatch(Input):
    status: State


class TenantOut(Output):
    id: UUID
    name: str
    slug: str
    status: State
    created_at: datetime
    updated_at: datetime


class MembershipCreate(Input):
    user_id: UUID
    role: Role = "member"


class MembershipPatch(Input):
    role: Role | None = None
    status: State | None = None

    @field_validator("role", "status")
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged fields instead of sending null")
        return value


class MembershipOut(Output):
    id: UUID
    tenant_id: UUID
    user_id: UUID
    role: Role
    status: State
    created_at: datetime
    updated_at: datetime


class RuntimeConfig(Input):
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_output_tokens: int = Field(default=2048, ge=1, le=32768)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_input_tokens: int = Field(default=8192, ge=2048, le=32768)


class BehaviorConfig(Input):
    instructions: str = Field(default="", max_length=12000)
    language: str = Field(default="auto", min_length=2, max_length=32, pattern=r"^[a-zA-Z-]+$")


class AgentCreate(Input):
    name: Name
    enabled: bool = True
    provider: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    model: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    base_url: str | None = Field(default=None, max_length=500)
    credential_ref: str | None = Field(
        default=None, min_length=6, max_length=80, pattern=r"^cred_[a-z0-9][a-z0-9_-]*$"
    )


class AgentUpdate(AgentCreate):
    expected_version: int = Field(ge=1)


class AgentOut(AgentCreate, Output):
    id: UUID
    tenant_id: UUID
    created_by: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class ConversationCreate(Input):
    channel: str = Field(default="api", min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")


class ConversationPatch(Input):
    status: Literal["open", "closed"]


class ConversationOut(Output):
    id: UUID
    tenant_id: UUID
    created_by: UUID
    channel: str
    status: Literal["open", "closed"]
    created_at: datetime
    updated_at: datetime


class MessageCreate(Input):
    role: Literal["user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=32000)
    metadata: dict[str, str | int | bool | None] = Field(default_factory=dict, max_length=20)

    @field_validator("metadata")
    @classmethod
    def bounded_metadata(cls, value):
        if any(len(k) > 64 or (isinstance(v, str) and len(v) > 1000) for k, v in value.items()):
            raise ValueError("Metadata fields exceed limits")
        return value


class MessageOut(Output):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    created_by: UUID
    role: Literal["user", "assistant", "tool"]
    content: str
    metadata: dict = Field(validation_alias="message_metadata")
    source: Literal["manual", "rag", "agent"]
    model_call_id: UUID | None
    tool_call_id: str | None
    created_at: datetime


class AuditOut(Output):
    id: UUID
    tenant_id: UUID | None
    actor_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    request_id: UUID
    outcome: Literal["success", "failure", "rejected"]
    reason: str | None
    details: dict
    created_at: datetime


class ErrorDetail(Output):
    code: str
    message: str


class ErrorOut(Output):
    error: ErrorDetail
    request_id: UUID
