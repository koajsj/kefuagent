"""Durable per-call authorization, reservation and terminal accounting."""

import hashlib
import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from jsonschema import Draft202012Validator
from sqlalchemy import select

from support_agent.db import set_tenant
from support_agent.dependencies import resume_context
from support_agent.errors import AppError
from support_agent.models import (
    AgentConfig,
    AgentTool,
    Conversation,
    Message,
    ModelCall,
    ToolDefinition,
    ToolExecution,
)
from support_agent.services.audit import record
from support_agent.services.resources import get_owned
from support_agent.tool_runtime import ToolFailure


def bound_capability(tool, registry):
    capability = registry.get(tool.key, tool.version)
    if tool.execution_type == "write" or tool.risk_level != "low":
        return None, "approval_required"
    if not capability or tool.execution_type != "read_only":
        return None, "tool_not_bound"
    if not capability.read_only:
        return None, "approval_required"
    if tool.parameters != capability.parameters or tool.output_schema != capability.output_schema:
        return None, "tool_contract_mismatch"
    return capability, None


def authorized_tools(db, context, config_id, registry):
    tools = db.scalars(
        select(ToolDefinition)
        .join(
            AgentTool,
            (
                (AgentTool.tool_id == ToolDefinition.id)
                & (AgentTool.tenant_id == ToolDefinition.tenant_id)
            ),
        )
        .where(
            ToolDefinition.tenant_id == context.tenant_id,
            ToolDefinition.enabled.is_(True),
            AgentTool.agent_config_id == config_id,
            AgentTool.enabled.is_(True),
        )
        .order_by(ToolDefinition.key)
        .limit(33)
    ).all()
    if len(tools) > 32:
        raise AppError(409, "too_many_tools", "At most 32 tool grants can be advertised")
    return [
        tool
        for tool in tools
        if (context.role == "admin" or "tenant:admin" not in tool.permissions)
        and bound_capability(tool, registry)[1] is None
    ]


def live_call(db, context, call_id):
    call = get_owned(db, ModelCall, context, call_id, lock=True)
    if call.status != "running" or call.lease_expires_at <= datetime.now(UTC):
        raise AppError(409, "execution_interrupted", "Turn is no longer active")
    return call


def audit_execution(db, context, row, request, phase):
    outcome = (
        "rejected"
        if row.status == "denied"
        else "failure"
        if row.status in {"failed", "timed_out"}
        else "success"
        if row.status == "succeeded"
        else "rejected"
    )
    # Reservation explicitly is not execution success.
    record(
        db,
        request,
        "tool_execution." + phase,
        "tool_execution",
        row.id,
        tenant_id=context.tenant_id,
        outcome=outcome,
        reason=row.error_category,
        details={
            "agent_config_id": str(row.agent_config_id),
            "tool_name": row.tool_name,
            "tool_call_id": row.tool_call_id,
            "model_call_id": str(row.model_call_id),
            "status": row.status,
            "permission_check": "denied" if row.status == "denied" else "passed",
            "delivery_error": row.delivery_error,
            "arguments": row.argument_summary,
            "elapsed_ms": row.elapsed_ms,
        },
    )


def finish_execution(
    db, context, row, request, status, reason=None, result=None, elapsed=None, delivery_error=None
):
    row.status = status
    row.error_category = reason
    row.result = result if not delivery_error else None
    row.delivery_error = delivery_error
    row.finished_at = datetime.now(UTC)
    row.elapsed_ms = elapsed
    audit_execution(db, context, row, request, "finish")
    db.flush()


def reconcile_executions(db, context, request, *, call_id=None):
    query = select(ToolExecution).where(
        ToolExecution.tenant_id == context.tenant_id,
        ToolExecution.status == "running",
        ToolExecution.lease_expires_at <= datetime.now(UTC),
    )
    if call_id is not None:
        query = query.where(ToolExecution.model_call_id == call_id)
    for row in db.scalars(
        query.limit(100).with_for_update().execution_options(populate_existing=True)
    ):
        finish_execution(db, context, row, request, "failed", "interrupted_result_unknown")


def parse_arguments(raw):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError
            result[k] = v
        return result

    try:
        if not isinstance(raw, str) or len(raw.encode()) > 16384:
            return None
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        return value if isinstance(value, dict) else None
    except (ValueError, RecursionError):
        return None


def check_authorization(
    db, context, call, tool, arguments, registry, *, validate_arguments=True, lock=True
):
    conversation = get_owned(
        db, Conversation, context, call.conversation_id, lock=lock, refresh=True
    )
    config = get_owned(db, AgentConfig, context, call.agent_config_id, lock=lock, refresh=True)
    if conversation.status != "open" or not config.enabled or config.version != call.config_version:
        return None, "agent_configuration_changed"
    if tool is None:
        return None, "tool_unavailable"
    grant_query = (
        select(AgentTool)
        .where(
            AgentTool.tenant_id == context.tenant_id,
            AgentTool.agent_config_id == config.id,
            AgentTool.tool_id == tool.id,
        )
        .execution_options(populate_existing=True)
    )
    grant = db.scalar(grant_query.with_for_update() if lock else grant_query)
    if (
        not tool.enabled
        or not grant
        or not grant.enabled
        or ("tenant:admin" in tool.permissions and context.role != "admin")
    ):
        return None, "tool_not_authorized"
    capability, reason = bound_capability(tool, registry)
    if reason:
        return None, reason
    if validate_arguments and (
        arguments is None or not Draft202012Validator(capability.parameters).is_valid(arguments)
    ):
        return None, "tool_arguments_invalid"
    return capability, None


def ensure_delivery(db, context, call, rows, request):
    # Flattened server-owned provenance survives later turns that paraphrase earlier tool answers.
    dependencies = (call.result or {}).get("tool_dependencies", [])
    linked = (
        db.scalars(
            select(ToolExecution).where(
                ToolExecution.tenant_id == context.tenant_id,
                ToolExecution.id.in_(dependencies),
            )
        ).all()
        if dependencies
        else []
    )
    if len(linked) != len(set(dependencies)):
        raise AppError(
            409, "tool_dependency_unavailable", "Historical tool provenance is unavailable"
        )
    rows = list({row.id: row for row in [*rows, *linked]}.values())
    for row in rows:
        if row.status == "denied":
            continue
        if row.delivery_error:
            raise AppError(409, row.delivery_error, "Tool payload delivery is no longer authorized")
        tool = get_owned(db, ToolDefinition, context, row.tool_id, refresh=True)
        owner = (
            call
            if row.model_call_id == call.id
            else get_owned(db, ModelCall, context, row.model_call_id)
        )
        _, reason = check_authorization(
            db,
            context,
            owner,
            tool,
            None,
            request.app.state.tool_registry,
            validate_arguments=False,
            lock=False,
        )
        if reason:
            raise AppError(409, reason, "Tool payload delivery is no longer authorized")
    return rows


def invoke(db, context, call_id, model_tool_call, request, *, deadline=None):
    context = resume_context(db, context, request)
    # Consistent conversation -> call lock order across P2/P3 and direct execution.
    snapshot = get_owned(db, ModelCall, context, call_id)
    get_owned(db, Conversation, context, snapshot.conversation_id, lock=True)
    call = live_call(db, context, call_id)
    existing = db.scalar(
        select(ToolExecution).where(
            ToolExecution.tenant_id == context.tenant_id,
            ToolExecution.model_call_id == call_id,
            ToolExecution.tool_call_id == model_tool_call.id,
        )
    )
    raw = model_tool_call.arguments
    digest = hashlib.sha256((model_tool_call.name + "\n" + raw).encode()).hexdigest()
    if existing:
        if existing.argument_digest != digest:
            raise AppError(
                409, "tool_call_conflict", "Tool call identifier already has different input"
            )
        return existing
    arguments = parse_arguments(raw)
    get_owned(db, AgentConfig, context, call.agent_config_id, lock=True)
    tool = db.scalar(
        select(ToolDefinition)
        .where(
            ToolDefinition.tenant_id == context.tenant_id,
            ToolDefinition.key == model_tool_call.name,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    capability, reason = check_authorization(
        db, context, call, tool, arguments, request.app.state.tool_registry
    )
    # Only trusted schema field names and presence are retained; no raw values or model-supplied keys.
    summary = {
        "field_count": len(arguments) if arguments is not None else 0,
        "values": "[REDACTED]",
    }
    row = ToolExecution(
        tenant_id=context.tenant_id,
        model_call_id=call_id,
        agent_config_id=call.agent_config_id,
        conversation_id=call.conversation_id,
        tool_id=tool.id if tool else None,
        tool_name=model_tool_call.name,
        tool_version=tool.version if tool else None,
        tool_call_id=model_tool_call.id,
        created_by=context.user_id,
        request_id=context.request_id,
        argument_digest=digest,
        argument_summary=summary,
        status="running",
        lease_expires_at=datetime.now(UTC)
        + timedelta(seconds=(capability.timeout_seconds if capability else 0) + 10),
    )
    db.add(row)
    db.flush()
    if reason:
        finish_execution(db, context, row, request, "denied", reason, elapsed=0)
        db.commit()
        return row
    audit_execution(db, context, row, request, "start")
    execution_id = row.id
    tool_context = replace(
        context,
        conversation_id=call.conversation_id,
        agent_config_id=call.agent_config_id,
        model_call_id=call_id,
        tool_call_id=model_tool_call.id,
        execution_id=execution_id,
    )
    db.commit()
    started = time.monotonic()
    result = None
    error = None
    try:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ToolFailure("tool_timeout")
            capability = replace(
                capability, timeout_seconds=min(capability.timeout_seconds, remaining)
            )
        result = request.app.state.tool_runner.run(capability, arguments, tool_context)
        if (
            not isinstance(result, dict)
            or len(json.dumps(result, allow_nan=False).encode()) > 8192
            or not Draft202012Validator(capability.output_schema).is_valid(result)
        ):
            error = "tool_output_invalid"
    except ToolFailure as exc:
        error = exc.category
    except Exception:
        error = "tool_internal_error"
    elapsed = int((time.monotonic() - started) * 1000)
    status = "timed_out" if error == "tool_timeout" else "failed" if error else "succeeded"
    try:
        context = resume_context(db, context, request)
    except AppError:
        db.rollback()
        set_tenant(db, context.tenant_id)
        row = get_owned(db, ToolExecution, context, execution_id, lock=True)
        if row.status == "running":
            finish_execution(
                db,
                context,
                row,
                request,
                status,
                error,
                elapsed=elapsed,
                delivery_error="access_revoked",
            )
        db.commit()
        raise
    get_owned(db, Conversation, context, tool_context.conversation_id, lock=True)
    call = live_call(db, context, call_id)
    get_owned(db, AgentConfig, context, call.agent_config_id, lock=True)
    row = get_owned(db, ToolExecution, context, execution_id, lock=True)
    if row.status != "running":
        return row
    # Post-execution revocation suppresses the payload; no result is delivered to model/user.
    tool = get_owned(db, ToolDefinition, context, row.tool_id, lock=True)
    _, reason = check_authorization(
        db, context, call, tool, arguments, request.app.state.tool_registry
    )
    if reason:
        finish_execution(
            db, context, row, request, status, error, elapsed=elapsed, delivery_error=reason
        )
    else:
        finish_execution(
            db,
            context,
            row,
            request,
            status,
            error,
            result if status == "succeeded" else None,
            elapsed,
        )
    db.commit()
    return row


def tool_message(db, context, row):
    payload = {
        "execution_id": str(row.id),
        "status": row.status,
        "data": row.result,
        "error_category": row.error_category,
    }
    content = json.dumps(payload, ensure_ascii=False)
    db.add(
        Message(
            tenant_id=context.tenant_id,
            created_by=context.user_id,
            conversation_id=row.conversation_id,
            model_call_id=row.model_call_id,
            source="agent",
            role="tool",
            content=content,
            tool_call_id=row.tool_call_id,
            message_metadata={"execution_id": str(row.id)},
        )
    )
    return {"role": "tool", "tool_call_id": row.tool_call_id, "content": content}


def execution_view(db, context, row, request):
    from support_agent.tool_protocol import ExecutionOut

    view = ExecutionOut.model_validate(row)
    call = get_owned(db, ModelCall, context, row.model_call_id)
    try:
        ensure_delivery(db, context, call, [row], request)
    except AppError as exc:
        return view.model_copy(update={"data": None, "delivery_error": exc.code})
    return view
