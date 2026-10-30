"""Provider-neutral, data-only tool contracts. No handler, imports, network or DB access."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, SchemaError
from pydantic import Field, field_validator

from support_agent.schemas import Input, Output

# A deliberately bounded subset: no refs, regex, combinators or executable extensions.
_SCHEMA_KEYS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "description",
    "title",
}


def check_schema(schema: dict) -> dict:
    if len(json.dumps(schema, allow_nan=False).encode()) > 16384:
        raise ValueError("Schema exceeds 16 KiB")

    def visit(node, depth=0):
        if not isinstance(node, dict) or depth > 8 or set(node) - _SCHEMA_KEYS:
            raise ValueError("Unsupported or excessively nested schema")
        if not isinstance(node.get("type"), str) or node["type"] not in {
            "object",
            "array",
            "string",
            "integer",
            "number",
            "boolean",
            "null",
        }:
            raise ValueError("Every schema node requires one explicit type")
        if node["type"] != "object" and set(node) & {
            "properties",
            "required",
            "additionalProperties",
        }:
            raise ValueError("Object keywords require object type")
        if node["type"] != "array" and "items" in node:
            raise ValueError("Array keywords require array type")
        if node["type"] == "object":
            if node.get("additionalProperties") is not False:
                raise ValueError("Objects must reject unknown properties")
            for child in node.get("properties", {}).values():
                visit(child, depth + 1)
        if node["type"] == "array":
            if not isinstance(node.get("maxItems"), int) or not 0 <= node["maxItems"] <= 100:
                raise ValueError("Arrays require maxItems <= 100")
            visit(node.get("items"), depth + 1)

    try:
        Draft202012Validator.check_schema(schema)
        visit(schema)
    except SchemaError as exc:
        raise ValueError("Invalid JSON Schema") from exc
    if schema.get("type") != "object":
        raise ValueError("Root parameters must be an object")
    return schema


class ToolSpec(Input):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    description: str = Field(min_length=1, max_length=2000)
    parameters: dict
    risk_level: Literal["low", "medium", "high"] = "low"
    permissions: list[Literal["tools:invoke", "tenant:admin"]] = Field(
        default_factory=lambda: ["tools:invoke"], max_length=2
    )
    enabled: bool = True
    version: int = Field(default=1, ge=1)
    execution_type: Literal["unbound", "read_only", "write"] = "unbound"
    output_schema: dict | None = None

    @field_validator("parameters")
    @classmethod
    def valid_schema(cls, value):
        return check_schema(value)

    @field_validator("output_schema")
    @classmethod
    def valid_output(cls, value):
        return check_schema(value) if value is not None else None

    @field_validator("permissions")
    @classmethod
    def explicit_permission(cls, value):
        if "tools:invoke" not in value or len(set(value)) != len(value):
            raise ValueError("tools:invoke is mandatory and permissions must be unique")
        return value


class ToolOut(ToolSpec, Output):
    id: UUID
    tenant_id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class ToolPatch(Input):
    enabled: bool


class ToolCall(Input):
    arguments: dict
    conversation_id: UUID | None = None
    agent_config_id: UUID | None = None
    idempotency_key: UUID | None = None
    tool_call_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,128}$")

    @field_validator("arguments")
    @classmethod
    def bounded(cls, value):
        if len(json.dumps(value, allow_nan=False).encode()) > 16384:
            raise ValueError("Tool arguments exceed 16 KiB")
        return value


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    tenant_id: UUID
    user_id: UUID
    membership_id: UUID
    role: str
    request_id: UUID
    conversation_id: UUID | None = None
    agent_config_id: UUID | None = None
    model_call_id: UUID | None = None
    tool_call_id: str | None = None
    execution_id: UUID | None = None


class ToolResult(Output):
    status: Literal[
        "validated", "rejected", "running", "succeeded", "failed", "timed_out", "denied"
    ]
    data: dict | None = None
    error_category: str | None = None
    invocation_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    tool_id: UUID
    conversation_id: UUID | None = None
    execution_id: UUID | None = None
    tool_call_id: str | None = None


class AgentToolGrant(Input):
    enabled: bool


class AgentToolOut(Output):
    id: UUID
    agent_config_id: UUID
    tool_id: UUID
    enabled: bool


class CapabilityOut(Output):
    key: str
    version: int
    parameters: dict
    output_schema: dict
    execution_type: Literal["read_only", "write"]


class ExecutionOut(Output):
    id: UUID
    model_call_id: UUID
    agent_config_id: UUID
    conversation_id: UUID
    tool_id: UUID | None
    tool_call_id: str
    tool_name: str
    tool_version: int | None
    status: str
    error_category: str | None
    delivery_error: str | None
    request_id: UUID
    started_at: datetime
    finished_at: datetime | None
    elapsed_ms: int | None
    data: dict | None = Field(validation_alias="result", default=None)


class AgentTurnInput(Input):
    agent_config_id: UUID
    content: str = Field(min_length=1, max_length=4000)
    idempotency_key: UUID


class AgentTurnOut(Output):
    conversation_id: UUID
    call_id: UUID
    request_id: UUID
    status: Literal["running", "answered", "failed", "unresolved"]
    answer: str = ""
    error_category: str | None = None
    executions: list[ExecutionOut] = Field(default_factory=list)
    grounded: Literal[False] = False
