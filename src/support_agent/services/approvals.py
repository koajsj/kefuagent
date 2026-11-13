"""One-shot approval for fixed transactional service commands only."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator
from sqlalchemy import select, text

from support_agent.autonomy import POLICY_VERSION, decide
from support_agent.credentials import Keyring
from support_agent.dependencies import locked_staff_context
from support_agent.errors import AppError, forbidden
from support_agent.maintenance import confirmation
from support_agent.models import (
    AgentConfig,
    AgentTool,
    Conversation,
    Ticket,
    ToolApproval,
    ToolDefinition,
)
from support_agent.security_schemas import ApprovalInput
from support_agent.services import desk_tools, operations
from support_agent.services.audit import record
from support_agent.services.resources import get_owned
from support_agent.tool_protocol import ToolCall


def binding(db, context, tool, config, conversation, arguments, registry):
    operations.controlled(db, context, conversation)
    capability = registry.get(tool.key, tool.version)
    if (
        not capability
        or capability.key not in desk_tools.COMMAND_KEYS
        or capability.read_only
        or tool.execution_type != "write"
        or capability.parameters != tool.parameters
        or capability.output_schema != tool.output_schema
    ):
        raise AppError(
            409,
            "approval_tool_unsupported",
            "Only fixed transactional service commands support approval",
        )
    decision = decide(tool, capability, ceiling=2)
    grant = db.scalar(
        select(AgentTool)
        .where(
            AgentTool.tenant_id == context.tenant_id,
            AgentTool.agent_config_id == config.id,
            AgentTool.tool_id == tool.id,
        )
        .with_for_update()
    )
    if (
        not tool.enabled
        or not grant
        or not grant.enabled
        or not config.enabled
        or config.behavior.get("autonomy_max_risk", 1) < 2
        or decision.risk != 3
        or conversation.status != "open"
        or ("tenant:admin" in tool.permissions and context.role != "admin")
    ):
        raise AppError(
            409,
            "approval_policy_denied",
            "Current permissions and policy do not authorize this proposal",
        )
    if not Draft202012Validator(capability.parameters).is_valid(arguments):
        raise AppError(422, "tool_arguments_invalid", "Arguments do not match the fixed contract")
    resources = {"conversation_version": conversation.version}
    if tool.key in {"ticket_update", "notification"}:
        try:
            ticket = get_owned(db, Ticket, context, UUID(arguments["ticket_id"]), lock=True)
        except ValueError:
            raise AppError(422, "tool_arguments_invalid", "Invalid ticket identifier") from None
        if ticket.conversation_id != conversation.id:
            raise forbidden()
        if tool.key == "ticket_update" and ticket.version != arguments["expected_version"]:
            raise AppError(
                409, "approval_resource_changed", "Ticket changed; request a new approval"
            )
        resources["ticket_version"] = ticket.version
    return {
        "policy_version": POLICY_VERSION,
        "risk": 3,
        "tool_key": tool.key,
        "tool_version": tool.version,
        "tool_contract": confirmation(
            {
                "parameters": tool.parameters,
                "output_schema": tool.output_schema,
                "permissions": tool.permissions,
                "risk": tool.risk_level,
            }
        ),
        "config_version": config.version,
        "grant_stamp": grant.updated_at.isoformat(),
        "resources": resources,
    }


def _inputs(db, context, data):
    conversation = get_owned(db, Conversation, context, data.conversation_id, lock=True)
    config = get_owned(db, AgentConfig, context, data.agent_config_id, lock=True)
    tool = get_owned(db, ToolDefinition, context, data.tool_id, lock=True)
    return tool, config, conversation


def create(db, context, data, request, *, already_locked=False):
    if not already_locked:
        context = locked_staff_context(db, context, request)
    from support_agent.services.model_configs import credential_lock

    credential_lock(db, context.tenant_id)
    tool, config, conversation = _inputs(db, context, data)
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"approval-request:{context.tenant_id}:{context.user_id}:{data.idempotency_key}"},
    )
    bound = binding(
        db, context, tool, config, conversation, data.arguments, request.app.state.tool_registry
    )
    payload_digest = confirmation(
        {
            "tenant": str(context.tenant_id),
            "requester": str(context.user_id),
            "conversation": str(conversation.id),
            "agent": str(config.id),
            "tool": str(tool.id),
            "arguments": data.arguments,
            "binding": bound,
        }
    )
    previous = db.scalar(
        select(ToolApproval)
        .where(
            ToolApproval.tenant_id == context.tenant_id,
            ToolApproval.requested_by == context.user_id,
            ToolApproval.idempotency_key == data.idempotency_key,
        )
        .with_for_update()
    )
    if previous:
        if previous.payload_digest != payload_digest:
            raise AppError(
                409,
                "approval_request_conflict",
                "Request key is already bound to another operation or version",
            )
        return previous
    row = ToolApproval(
        id=uuid4(),
        tenant_id=context.tenant_id,
        requested_by=context.user_id,
        conversation_id=conversation.id,
        agent_config_id=config.id,
        tool_id=tool.id,
        idempotency_key=data.idempotency_key,
        payload_digest=payload_digest,
        binding=bound,
        expires_at=datetime.now(UTC) + timedelta(minutes=data.expires_in_minutes),
    )
    row.encrypted_arguments = Keyring(request.app.state.settings).seal(
        context.tenant_id,
        "approval:" + str(row.id),
        json.dumps(data.arguments, sort_keys=True, allow_nan=False),
    )
    db.add(row)
    db.flush()
    record(
        db,
        request,
        "approval.requested",
        "tool_approval",
        row.id,
        tenant_id=context.tenant_id,
        details={"payload_digest": payload_digest, "tool_id": str(tool.id), "risk": 3},
    )
    return row


def expire(db, row, request):
    if row.status in {"PENDING_APPROVAL", "APPROVED"} and row.expires_at <= datetime.now(UTC):
        row.status = "EXPIRED"
        record(
            db,
            request,
            "approval.expired",
            "tool_approval",
            row.id,
            tenant_id=row.tenant_id,
            outcome="rejected",
            reason="approval_expired",
        )


def arguments(row, request):
    return json.loads(
        Keyring(request.app.state.settings).open(
            row.tenant_id, "approval:" + str(row.id), row.encrypted_arguments
        )
    )


def decide_request(db, context, aid, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    # Same resource -> approval order as the executor. Read identity before locks.
    snapshot = get_owned(db, ToolApproval, context, aid)
    _inputs(db, context, snapshot)
    row = get_owned(db, ToolApproval, context, aid, lock=True)
    expire(db, row, request)
    if row.requested_by == context.user_id:
        raise AppError(
            403,
            "approval_self_review_denied",
            "A different administrator must review this operation",
        )
    if row.payload_digest != data.expected_digest:
        raise AppError(409, "approval_digest_conflict", "Refresh and review the exact operation")
    if data.decision == "REVOKED":
        valid = row.status in {"PENDING_APPROVAL", "APPROVED"}
    else:
        valid = row.status == "PENDING_APPROVAL"
    if not valid:
        raise AppError(
            409, "approval_not_pending", "Approval is no longer eligible for this decision"
        )
    row.status, row.decided_by, row.reason, row.decided_at = (
        data.decision,
        context.user_id,
        data.reason,
        datetime.now(UTC),
    )
    record(
        db,
        request,
        "approval." + data.decision.lower(),
        "tool_approval",
        row.id,
        tenant_id=context.tenant_id,
        details={"payload_digest": row.payload_digest, "decision": row.status},
    )
    db.flush()
    return row


def check_execution(db, context, aid, call, tool, supplied, request, *, gated_approver_id):
    row = get_owned(db, ToolApproval, context, aid, lock=True)
    expire(db, row, request)
    if row.decided_by != gated_approver_id:
        raise AppError(
            409,
            "approval_reviewer_changed",
            "Approval reviewer changed; refresh the decision before executing",
        )
    if (
        row.status != "APPROVED"
        or row.requested_by != context.user_id
        or row.decided_by is None
        or row.decided_by == context.user_id
        or row.execution_id is not None
    ):
        raise AppError(
            409, "approval_not_executable", "A current unused independent approval is required"
        )
    # Check the approver's account/member role again; revocation must invalidate authority.
    operations.operator(db, context, row.decided_by)
    from support_agent.models import Membership, User

    if not db.scalar(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.tenant_id == context.tenant_id,
            Membership.user_id == row.decided_by,
            Membership.role == "admin",
            Membership.status == "active",
            User.status == "active",
        )
    ):
        raise forbidden()
    if (
        row.conversation_id != call.conversation_id
        or row.agent_config_id != call.agent_config_id
        or row.tool_id != tool.id
        or supplied != arguments(row, request)
    ):
        raise AppError(409, "approval_payload_changed", "Approval is bound to another operation")
    config = get_owned(db, AgentConfig, context, call.agent_config_id, lock=True)
    conversation = get_owned(db, Conversation, context, call.conversation_id, lock=True)
    bound = binding(
        db, context, tool, config, conversation, supplied, request.app.state.tool_registry
    )
    digest = confirmation(
        {
            "tenant": str(context.tenant_id),
            "requester": str(context.user_id),
            "conversation": str(conversation.id),
            "agent": str(config.id),
            "tool": str(tool.id),
            "arguments": supplied,
            "binding": bound,
        }
    )
    if bound != row.binding or digest != row.payload_digest:
        row.status = "REVOKED"
        record(
            db,
            request,
            "approval.invalidated",
            "tool_approval",
            row.id,
            tenant_id=context.tenant_id,
            outcome="rejected",
            reason="approval_resource_changed",
        )
        db.commit()
        raise AppError(
            409,
            "approval_resource_changed",
            "Permissions, policy or resources changed; request a new approval",
        )
    return row


def execute(db, context, aid, request):
    row = get_owned(db, ToolApproval, context, aid, refresh=True)
    if row.requested_by != context.user_id:
        raise forbidden()
    expire(db, row, request)
    if row.status not in {"APPROVED", "EXECUTED"}:
        db.commit()
        raise AppError(409, "approval_not_executable", "Approval is not executable")
    data = ToolCall(
        arguments=arguments(row, request),
        conversation_id=row.conversation_id,
        agent_config_id=row.agent_config_id,
        idempotency_key=row.id,
        tool_call_id="approval_" + row.id.hex,
        approval_id=row.id,
    )
    from support_agent.services.agent_turns import execute_direct

    return execute_direct(db, context, row.tool_id, data, request)


def propose_execution(db, context, call, tool, supplied, execution, request):
    return create(
        db,
        context,
        ApprovalInput(
            tool_id=tool.id,
            agent_config_id=call.agent_config_id,
            conversation_id=call.conversation_id,
            idempotency_key=execution.id,
            arguments=supplied,
        ),
        request,
        already_locked=True,
    )


def execution_context(db, context, aid, request):
    from support_agent.db import authorization_gate
    from support_agent.dependencies import resume_context

    if context.public_session_id is not None:
        raise forbidden()
    row = get_owned(db, ToolApproval, context, aid, refresh=True)
    reviewer = row.decided_by
    for uid in sorted({context.user_id, reviewer} - {None}, key=str):
        authorization_gate(db, user_id=uid)
    authorization_gate(db, tenant_id=context.tenant_id)
    return resume_context(db, context, request), reviewer


def preflight(db, context, tool_id, data, request):
    """Reject before reserving an immutable execution key; repeat after commit at dispatch."""
    context, reviewer = execution_context(db, context, data.approval_id, request)
    row = get_owned(db, ToolApproval, context, data.approval_id, refresh=True)
    if (
        row.requested_by != context.user_id
        or row.tool_id != tool_id
        or row.conversation_id != data.conversation_id
        or row.agent_config_id != data.agent_config_id
        or data.idempotency_key != row.id
        or data.tool_call_id != "approval_" + row.id.hex
        or data.arguments != arguments(row, request)
    ):
        raise AppError(
            409, "approval_payload_changed", "Execute the exact immutable approval operation"
        )
    if row.status == "EXECUTED":
        return context  # Existing receipt only; reserve returns the original run and never invokes again.
    tool, _, _ = _inputs(db, context, row)
    check_execution(
        db, context, row.id, data, tool, data.arguments, request, gated_approver_id=reviewer
    )
    return context
