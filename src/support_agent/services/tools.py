from dataclasses import replace

from jsonschema import Draft202012Validator
from sqlalchemy import select

from support_agent.errors import AppError, forbidden
from support_agent.models import AgentConfig, AgentTool, Conversation, ToolDefinition
from support_agent.services.audit import record
from support_agent.services.resources import get_owned
from support_agent.tool_protocol import ToolResult


def register(db, context, data, request):
    tool = ToolDefinition(
        **data.model_dump(), tenant_id=context.tenant_id, created_by=context.user_id
    )
    db.add(tool)
    db.flush()
    record(db, request, "tool.register", "tool", tool.id, tenant_id=context.tenant_id)
    return tool


def set_enabled(db, context, tool_id, data, request):
    tool = get_owned(db, ToolDefinition, context, tool_id, lock=True)
    tool.enabled = data.enabled
    db.flush()
    record(db, request, "tool.update", "tool", tool.id, tenant_id=context.tenant_id)
    return tool


def validate_call(db, context, tool_id, data):
    tool = get_owned(db, ToolDefinition, context, tool_id)
    if not tool.enabled:
        raise AppError(409, "tool_disabled", "Tool definition is disabled")
    if "tenant:admin" in tool.permissions and context.role != "admin":
        raise forbidden()
    if data.conversation_id:
        get_owned(db, Conversation, context, data.conversation_id)
    if not Draft202012Validator(tool.parameters).is_valid(data.arguments):
        # Validator error messages often embed argument values. Never return them.
        raise AppError(
            422, "tool_arguments_invalid", "Arguments do not match the registered schema"
        )
    return replace(context, conversation_id=data.conversation_id)


def validate(db, context, tool_id, data, request):
    checked = validate_call(db, context, tool_id, data)
    record(db, request, "tool.validate", "tool", tool_id, tenant_id=context.tenant_id)
    return ToolResult(
        status="validated",
        data={"valid": True},
        request_id=checked.request_id,
        tool_id=tool_id,
        conversation_id=checked.conversation_id,
    )


def execute(db, context, tool_id, data, request):
    if data.agent_config_id is not None:
        from support_agent.services.agent_turns import execute_direct

        if not data.conversation_id or not data.idempotency_key or not data.tool_call_id:
            raise AppError(
                422,
                "execution_context_required",
                "Agent, conversation and idempotency identifiers are required",
            )
        return execute_direct(db, context, tool_id, data, request)
    checked = validate_call(db, context, tool_id, data)
    record(
        db,
        request,
        "tool.execute",
        "tool",
        tool_id,
        tenant_id=context.tenant_id,
        outcome="rejected",
        reason="execution_not_enabled",
    )
    return ToolResult(
        status="rejected",
        error_category="execution_not_enabled",
        request_id=checked.request_id,
        tool_id=tool_id,
        conversation_id=checked.conversation_id,
    )


def grant(db, context, config_id, tool_id, data, request):
    get_owned(db, AgentConfig, context, config_id, lock=True)
    get_owned(db, ToolDefinition, context, tool_id)
    row = db.scalar(
        select(AgentTool)
        .where(
            AgentTool.tenant_id == context.tenant_id,
            AgentTool.agent_config_id == config_id,
            AgentTool.tool_id == tool_id,
        )
        .with_for_update()
    )
    if row is None:
        row = AgentTool(
            tenant_id=context.tenant_id,
            agent_config_id=config_id,
            tool_id=tool_id,
            created_by=context.user_id,
        )
        db.add(row)
    row.enabled = data.enabled
    db.flush()
    record(
        db,
        request,
        "agent_tool.grant",
        "agent_tool",
        row.id,
        tenant_id=context.tenant_id,
        details={
            "agent_config_id": str(config_id),
            "tool_id": str(tool_id),
            "enabled": data.enabled,
        },
    )
    return row
