"""Bounded, content-free observations assembled from existing durable records."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select

from support_agent.errors import AppError, forbidden, missing
from support_agent.models import AuditEvent, Conversation, ModelCall, ToolExecution
from support_agent.services import costs
from support_agent.services.resources import get_owned
from support_agent.trace_schemas import TraceCost, TraceEvent, TraceOut

MAX_EVENTS = 100
STATUS = {
    "success": "SUCCEEDED",
    "succeeded": "SUCCEEDED",
    "completed": "SUCCEEDED",
    "failure": "FAILED",
    "failed": "FAILED",
    "denied": "FAILED",
    "rejected": "FAILED",
    "running": "RUNNING",
    "pending": "NOT_STARTED",
    "timed_out": "TIMED_OUT",
    "interrupted": "INTERRUPTED",
}


def status(value, error=None):
    if error in {"timeout", "tool_timeout", "turn_timeout"}:
        return "TIMED_OUT"
    if error in {"execution_interrupted", "interrupted_result_unknown", "tool_process_interrupted"}:
        return "INTERRUPTED"
    return STATUS.get(value, "UNKNOWN")


AUDIT_ACTIONS = {
    "agent.plan",
    "agent.policy",
    "model_call.start",
    "model_call.finish",
    "model_call.reconcile",
    "model_call.phase",
    "agent_turn.reserve",
    "agent_turn.finish",
    "tool_execution.start",
    "tool_execution.finish",
    "tool_execution.reconcile",
}


def get_trace(db, context, conversation_id, call_id, request):
    if context.public_session_id is not None or context.user_id is None:
        raise forbidden()
    get_owned(db, Conversation, context, conversation_id)
    call = get_owned(db, ModelCall, context, call_id)
    if call.conversation_id != conversation_id:
        raise missing()
    if context.role != "admin" and call.created_by != context.user_id:
        raise forbidden()
    now = datetime.now(UTC)
    lease_expired = call.status == "running" and call.lease_expires_at <= now
    rows = list(
        db.scalars(
            select(ToolExecution)
            .where(
                ToolExecution.tenant_id == context.tenant_id,
                ToolExecution.model_call_id == call.id,
                ToolExecution.conversation_id == conversation_id,
            )
            .order_by(ToolExecution.created_at, ToolExecution.id)
            .limit(MAX_EVENTS + 1)
        )
    )
    # Never authorize only a prefix of the provenance.
    if len(rows) > MAX_EVENTS or len(call.steps) > MAX_EVENTS:
        raise AppError(409, "trace_too_large", "Trace exceeds the observation limit")
    # Metadata diagnostics must remain visible after a credential/source/tool has
    # been revoked. This separate owner/admin view never serializes any payload,
    # memory identity, citation, parameter, credential or arbitrary audit details.
    audits = list(
        db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == context.tenant_id,
                AuditEvent.action.in_(AUDIT_ACTIONS),
                or_(
                    and_(
                        AuditEvent.resource_type == "model_call", AuditEvent.resource_id == call.id
                    ),
                    and_(
                        AuditEvent.resource_type == "tool_execution",
                        AuditEvent.resource_id.in_([r.id for r in rows]),
                    ),
                ),
            )
            .order_by(AuditEvent.created_at, AuditEvent.id)
            .limit(MAX_EVENTS + 1)
        )
    )
    events = [
        TraceEvent(
            kind="model",
            label="模型请求",
            status=(
                "NOT_STARTED"
                if s.get("status") == "denied" and s.get("attempts") == 0
                else status(s.get("status"), s.get("error_category"))
            ),
            started_at=s.get("started_at"),
            finished_at=s.get("finished_at"),
            elapsed_ms=s.get("elapsed_ms"),
            model=s.get("model"),
            purpose=s.get("purpose"),
            provider=s.get("provider"),
            task=s.get("task"),
            prompt_id=s.get("prompt_id"),
            prompt_version=s.get("prompt_version"),
            prompt_hash=s.get("prompt_hash"),
            input_tokens=s.get("input_tokens") if s.get("usage_complete") else None,
            output_tokens=s.get("output_tokens") if s.get("usage_complete") else None,
            error_category=s.get("error_category"),
        )
        for s in call.steps
    ]
    events.extend(
        TraceEvent(
            kind="tool",
            label="工具执行",
            status=status(r.status, r.error_category),
            started_at=r.started_at,
            finished_at=r.finished_at,
            elapsed_ms=r.elapsed_ms,
            execution_id=r.id,
            tool_id=r.tool_id,
            error_category=r.delivery_error or r.error_category,
        )
        for r in rows
    )
    labels = {"context": "近期上下文", "retrieval": "知识检索", "memory": "授权记忆筛选"}
    for audit in audits[:MAX_EVENTS]:
        phase = audit.details.get("phase") if audit.action == "model_call.phase" else None
        tool_id = None
        if audit.action == "agent.policy":
            try:
                tool_id = UUID(audit.details.get("tool_id", ""))
            except (ValueError, TypeError, AttributeError):
                pass
        events.append(
            TraceEvent(
                kind=phase if phase in labels else "audit",
                label=labels.get(phase, audit.action),
                status=(
                    "NOT_STARTED"
                    if audit.action == "agent_turn.reserve" and audit.reason == "execution_pending"
                    else audit.details.get("phase_status")
                    if audit.details.get("phase_status")
                    in {"SUCCEEDED", "FAILED", "TIMED_OUT", "INTERRUPTED"}
                    else status(audit.outcome, audit.reason)
                ),
                started_at=audit.details.get("started_at", audit.created_at)
                if phase in labels
                else audit.created_at,
                elapsed_ms=audit.details.get("elapsed_ms") if phase in labels else None,
                finished_at=audit.details.get("finished_at") if phase in labels else None,
                error_category=audit.reason,
                tool_id=tool_id,
                risk=audit.details.get("risk")
                if audit.action == "agent.policy"
                and type(audit.details.get("risk")) is int
                and 0 <= audit.details["risk"] <= 4
                else None,
                decision=audit.details.get("decision")
                if audit.action == "agent.policy"
                and audit.details.get("decision") in {"allowed", "denied"}
                else None,
                policy_version="private-autonomy-v1"
                if audit.action in {"agent.policy", "agent.plan"}
                and audit.details.get("policy_version") == "private-autonomy-v1"
                else None,
            )
        )
    # Start/reservation proves server acceptance only; finish does not prove
    # that a client received a response. No delivery event is currently stored.
    starts = [a for a in audits if a.action in {"model_call.start", "agent_turn.reserve"}]
    if starts:
        events.append(
            TraceEvent(
                kind="request",
                label="服务端请求受理",
                status="SUCCEEDED",
                started_at=starts[0].created_at,
            )
        )
    else:
        events.append(TraceEvent(kind="request", label="服务端请求受理", status="UNKNOWN"))
    finishes = [a for a in audits if a.action in {"model_call.finish", "agent_turn.finish"}]
    if finishes:
        finish = finishes[-1]
        events.append(
            TraceEvent(
                kind="result",
                label="服务端处理结束",
                status=status(finish.outcome, finish.reason),
                started_at=finish.created_at,
            )
        )
    else:
        events.append(TraceEvent(kind="result", label="服务端处理结束", status="UNKNOWN"))
    events.append(TraceEvent(kind="delivery", label="客户端收到结果", status="UNKNOWN"))
    expired_executions = {row.id for row in rows if row.lease_expires_at <= now}
    for event in events:
        if event.status == "RUNNING" and (
            lease_expired or call.status != "running" or event.execution_id in expired_executions
        ):
            event.status = "UNKNOWN"
    observed = {event.kind for event in events}
    for kind, label in (("model", "模型请求"), ("tool", "工具执行")):
        if kind not in observed:
            events.append(TraceEvent(kind=kind, label=label, status="UNKNOWN"))
    for phase, label in labels.items():
        if phase not in observed:
            events.append(TraceEvent(kind=phase, label=label, status="UNKNOWN"))
    # Unknown timestamps remain unknown, rather than inventing a phase span.
    events.sort(key=lambda e: (e.started_at is None, e.started_at or call.created_at))
    return TraceOut(
        call_id=call.id,
        conversation_id=conversation_id,
        request_id=call.request_id,
        status=call.status,
        execution_state="UNKNOWN"
        if lease_expired
        else (
            "SUCCEEDED"
            if call.status in {"answered", "unresolved", "connected"}
            else status(call.status, call.error_category)
        ),
        lease_expired=lease_expired,
        phase=call.phase,
        agent_config_id=call.agent_config_id,
        config_version=call.config_version,
        error_category=call.error_category,
        input_tokens=call.input_tokens if call.usage_complete else None,
        output_tokens=call.output_tokens if call.usage_complete else None,
        usage_complete=call.usage_complete,
        started_at=call.created_at,
        elapsed_ms=call.elapsed_ms,
        cost=TraceCost(**costs.estimate(call.steps)),
        events=events[:MAX_EVENTS],
        truncated=len(events) > MAX_EVENTS or len(audits) > MAX_EVENTS,
    )
