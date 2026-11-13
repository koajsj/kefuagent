"""Shared durable-worker identity and model admission; no permanent service-user bypass."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import null, select
from starlette.requests import Request

from support_agent.dependencies import locked_staff_context
from support_agent.models import AgentConfig, Membership, ModelCall
from support_agent.schemas import RuntimeConfig
from support_agent.services import knowledge_provenance, limits
from support_agent.services.audit import record
from support_agent.services.resources import get_owned
from support_agent.tool_protocol import ExecutionContext


def request_for(state, job):
    request = Request(
        {
            "type": "http",
            "method": "WORKER",
            "path": "/worker",
            "headers": [],
            "app": SimpleNamespace(state=state),
        }
    )
    request.state.request_id = uuid4()
    request.state.actor_id = job.requested_by
    request.state.session_id = job.auth_session_id
    return request


def identity(db, job, request, *, admin=False):
    membership = db.scalar(
        select(Membership).where(
            Membership.tenant_id == job.tenant_id, Membership.user_id == job.requested_by
        )
    )
    context = ExecutionContext(
        tenant_id=job.tenant_id,
        user_id=job.requested_by,
        membership_id=membership.id if membership else None,
        role=membership.role if membership else "",
        request_id=request.state.request_id,
    )
    return locked_staff_context(db, context, request, admin=admin)


def model_call(db, context, aid, request, *, kind, conversation_id=None):
    if conversation_id is not None:
        from support_agent.services.chat import expire_active_calls

        expire_active_calls(db, context, conversation_id, request)
    config = get_owned(db, AgentConfig, context, aid, lock=True)
    call = ModelCall(
        tenant_id=context.tenant_id,
        created_by=context.user_id,
        conversation_id=conversation_id,
        agent_config_id=config.id,
        config_version=config.version,
        model=config.model,
        kind=kind,
        status="running",
        attempts=null(),
        request_id=request.state.request_id,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=240),
        result={},
        steps=[],
    )
    db.add(call)
    knowledge_provenance.initialize(call)
    db.flush()
    limits.admit(
        db,
        context,
        call,
        request,
        RuntimeConfig.model_validate(config.runtime).model_dump(),
        offline=config.provider == "demo",
    )
    record(db, request, "model_call.start", "model_call", call.id, tenant_id=context.tenant_id)
    return call


def finish(db, context, call, request, *, error=None):
    call.status = "failed" if error else "answered"
    call.phase = "failed" if error else "complete"
    call.error_category = error
    limits.settle(call)

    record(
        db,
        request,
        "model_call.finish",
        "model_call",
        call.id,
        tenant_id=context.tenant_id,
        outcome="failure" if error else "success",
        reason=error,
    )
