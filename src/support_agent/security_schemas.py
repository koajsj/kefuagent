"""Administrative security contracts; never expose stored ciphertext or bearer material."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from support_agent.schemas import Input, Output
from support_agent.tool_protocol import ToolCall


class ErasureInput(Input):
    subject_type: Literal["user", "customer", "conversation"]
    subject_id: UUID


class ErasureOut(Output):
    id: UUID
    subject_type: str
    subject_id: UUID
    status: str
    attempts: int
    assessment: dict
    created_at: datetime
    updated_at: datetime


class ApprovalInput(ToolCall):
    tool_id: UUID
    conversation_id: UUID
    agent_config_id: UUID
    idempotency_key: UUID
    expires_in_minutes: int = Field(default=30, ge=1, le=60)


class ApprovalDecision(Input):
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["APPROVED", "REJECTED", "REVOKED"]
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class ApprovalOut(Output):
    id: UUID
    requested_by: UUID
    decided_by: UUID | None
    conversation_id: UUID
    agent_config_id: UUID
    tool_id: UUID
    status: str
    payload_digest: str
    binding: dict
    reason: str | None
    expires_at: datetime
    decided_at: datetime | None
    execution_id: UUID | None
    created_at: datetime


class BudgetInput(Input):
    expected_version: int = Field(ge=0)
    enabled: bool
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    run_limit: Decimal = Field(ge=0, max_digits=24, decimal_places=12)
    daily_limit: Decimal = Field(ge=0, max_digits=24, decimal_places=12)
    monthly_limit: Decimal = Field(ge=0, max_digits=24, decimal_places=12)
    total_limit: Decimal = Field(ge=0, max_digits=24, decimal_places=12)
    agent_limits: dict[UUID, Decimal] = Field(default_factory=dict, max_length=100)

    @field_validator("agent_limits")
    @classmethod
    def valid_limits(cls, value):
        if any(
            not v.is_finite()
            or v < 0
            or v >= Decimal("1000000000000")
            or v.as_tuple().exponent < -12
            for v in value.values()
        ):
            raise ValueError(
                "Agent totals require nonnegative finite amounts with at most 12 decimals"
            )
        return value


class BudgetOut(Output):
    enabled: bool
    version: int
    currency: str
    run_limit: Decimal
    daily_limit: Decimal
    monthly_limit: Decimal
    total_limit: Decimal
    agent_limits: dict[str, str]
    price_catalog_digest: str


class CostOut(Output):
    id: UUID
    model_call_id: UUID
    agent_config_id: UUID
    step_index: int
    currency: str
    reserved: Decimal
    charged: Decimal
    status: str
    pricing: dict
    created_at: datetime
    settled_at: datetime | None


class SiteInput(Input):
    publication_id: UUID
    origin: str = Field(max_length=300)

    @field_validator("origin")
    @classmethod
    def exact_origin(cls, value):
        from support_agent.services.widget_identity import normalize_origin

        return normalize_origin(value)


class SitePatch(Input):
    expected_version: int = Field(ge=1)
    enabled: bool


class SiteVerify(Input):
    challenge: str = Field(min_length=40, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class SiteOut(Output):
    id: UUID
    publication_id: UUID
    origin: str
    enabled: bool
    version: int
    verified_at: datetime | None
    verification_expires_at: datetime | None
    challenge_expires_at: datetime


class SiteCreated(Output):
    site: SiteOut
    challenge: str
    server_secret: str
    verification_url: str


class BootstrapInput(Input):
    site_id: UUID
    nonce: UUID
    expires_at: int = Field(ge=1)
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


class BootstrapOut(Output):
    origin: str
    token: str
    expires_at: datetime


class VisitorStart(Input):
    bootstrap_token: str = Field(min_length=40, max_length=256)


class ApprovalDetail(Output):
    approval: ApprovalOut
    arguments: dict


class BudgetOverview(Output):
    policy: BudgetOut | None
    usage: dict[str, Decimal]
    remaining: dict[str, Decimal] | None
    admission_state: str
    price_catalog_digest: str
    prices: list[dict]
    basis: Literal["internal_deployment_price_not_supplier_invoice"]
    timezone: Literal["UTC"]
    unknown_carry_forward: Literal[True]


class SiteIntegration(Output):
    instance_id: UUID
    aud: str
    publication_id: UUID
    publication_version: int
    site_id: UUID
    site_version: int
    origin: str
    algorithm: Literal["HMAC-SHA256"]
    max_assertion_seconds: Literal[60]
    signing_secret_exposed: Literal[False]
