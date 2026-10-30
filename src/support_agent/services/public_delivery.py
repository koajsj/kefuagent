"""Narrow anonymous delivery capabilities; never a management identity."""

import hashlib
import hmac
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from support_agent.db import set_tenant
from support_agent.errors import AppError, missing
from support_agent.models import (
    AgentConfig,
    Conversation,
    Membership,
    ModelCall,
    Publication,
    PublicRoute,
    Tenant,
    User,
    VisitorSession,
)
from support_agent.security import token_digest
from support_agent.services import agent_turns, conversations, tool_execution
from support_agent.services.audit import record
from support_agent.services.resources import get_owned
from support_agent.tool_protocol import AgentTurnInput, ExecutionContext


def create(db, context, data, request):
    config = get_owned(db, AgentConfig, context, data.agent_config_id, lock=True)
    tools = tool_execution.authorized_tools(
        db, replace(context, role="visitor"), config.id, request.app.state.tool_registry
    )
    if not set(data.public_tool_ids).issubset({t.id for t in tools}):
        raise AppError(
            422, "public_tool_denied", "Public tools require active low-risk read-only Agent grants"
        )
    route = PublicRoute(tenant_id=context.tenant_id)
    db.add(route)
    db.flush()
    row = Publication(
        id=route.id,
        tenant_id=context.tenant_id,
        agent_config_id=config.id,
        created_by=context.user_id,
        name=data.name,
        agent_version=config.version,
        public_tool_ids=[str(t) for t in data.public_tool_ids],
    )
    db.add(row)
    db.flush()
    record(db, request, "publication.create", "publication", row.id, tenant_id=context.tenant_id)
    return row


def change(db, context, pid, data, request):
    row = get_owned(db, Publication, context, pid, lock=True)
    config = get_owned(db, AgentConfig, context, row.agent_config_id, lock=True)
    if row.revoked_at:
        raise AppError(409, "publication_revoked", "Create a new public entry")
    if row.version != data.expected_version:
        raise AppError(409, "version_conflict", "Reload publication before changing it")
    if data.enabled and not config.enabled:
        raise AppError(409, "agent_disabled", "Enable the Agent first")
    row.enabled = data.enabled
    if data.enabled:
        row.created_by = context.user_id
    row.agent_version = config.version
    row.version += 1
    record(
        db,
        request,
        "publication.publish" if row.enabled else "publication.offline",
        "publication",
        row.id,
        tenant_id=context.tenant_id,
    )
    db.flush()
    return row


def revoke(db, context, pid, request):
    row = get_owned(db, Publication, context, pid, lock=True)
    row.enabled = False
    row.revoked_at = datetime.now(UTC)
    row.version += 1
    record(db, request, "publication.revoke", "publication", pid, tenant_id=context.tenant_id)


def locate(db, pid, request):
    route = db.get(PublicRoute, pid)
    if route is None:
        raise missing()
    set_tenant(db, route.tenant_id)
    request.state.tenant_id = route.tenant_id
    row = db.scalar(
        select(Publication)
        .where(Publication.id == pid, Publication.tenant_id == route.tenant_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if not row or not row.enabled or row.revoked_at:
        raise missing()
    config = db.get(AgentConfig, row.agent_config_id, populate_existing=True)
    owner = db.scalar(
        select(User)
        .where(User.id == row.created_by)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    tenant = db.scalar(
        select(Tenant)
        .where(Tenant.id == row.tenant_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    link = db.scalar(
        select(Membership)
        .where(
            Membership.tenant_id == row.tenant_id,
            Membership.user_id == row.created_by,
            Membership.status == "active",
            Membership.role == "admin",
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        not config
        or not config.enabled
        or config.version != row.agent_version
        or not owner
        or owner.status != "active"
        or not tenant
        or tenant.status != "active"
        or not link
    ):
        raise missing()
    return row, config, link


def start(db, pid, request):
    row, config, link = locate(db, pid, request)
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "visitor-start:" + str(row.tenant_id)},
    )
    # Recheck after waiting for another process; no raw IP or forwarded headers retained.
    row, config, link = locate(db, pid, request)
    now = datetime.now(UTC)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ip = request.client.host if request.client else "unknown"
    rate_key = request.app.state.settings.public_rate_key
    if rate_key is None:
        raise AppError(
            503,
            "public_rate_key_unavailable",
            "Configure a private PUBLIC_RATE_KEY before accepting anonymous sessions",
        )
    iphash = hmac.new(
        rate_key.get_secret_value().encode(), (str(pid) + ":" + ip).encode(), hashlib.sha256
    ).hexdigest()
    total = db.scalar(
        select(func.count())
        .select_from(VisitorSession)
        .where(VisitorSession.tenant_id == row.tenant_id, VisitorSession.created_at >= day)
    )
    recent, daily = db.execute(
        select(
            func.count().filter(VisitorSession.created_at >= now - timedelta(minutes=1)),
            func.count().filter(VisitorSession.created_at >= day),
        ).where(
            VisitorSession.tenant_id == row.tenant_id,
            VisitorSession.publication_id == pid,
            VisitorSession.ip_hash == iphash,
            VisitorSession.created_at >= min(day, now - timedelta(minutes=1)),
        )
    ).one()
    if total >= 1000 or recent >= 3 or daily >= 20:
        raise AppError(
            429, "visitor_limit_exceeded", "Public session creation limit reached; retry later"
        )
    conv = Conversation(
        tenant_id=row.tenant_id,
        created_by=row.created_by,
        subject=row.name + " · 访客",
        channel="public",
    )
    db.add(conv)
    db.flush()
    token = secrets.token_urlsafe(32)
    visitor = VisitorSession(
        tenant_id=row.tenant_id,
        publication_id=pid,
        publication_version=row.version,
        conversation_id=conv.id,
        token_hash=token_digest(token),
        ip_hash=iphash,
        expires_at=now + timedelta(hours=12),
    )
    db.add(visitor)
    db.flush()
    request.state.visitor_session_id = visitor.id
    record(db, request, "visitor.start", "visitor_session", visitor.id, tenant_id=row.tenant_id)
    return {"id": visitor.id, "token": token, "expires_at": visitor.expires_at}


def authenticate(db, pid, sid, request):
    row, config, link = locate(db, pid, request)
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Visitor ") or not 20 <= len(authorization[8:]) <= 256:
        raise AppError(
            401, "visitor_authentication_required", "A valid visitor session is required"
        )
    digest = token_digest(authorization[8:])
    visitor = db.scalar(
        select(VisitorSession)
        .where(
            VisitorSession.tenant_id == row.tenant_id,
            VisitorSession.id == sid,
            VisitorSession.publication_id == pid,
            VisitorSession.token_hash == digest,
        )
        .execution_options(populate_existing=True)
    )
    if (
        not visitor
        or visitor.ended_at is not None
        or visitor.expires_at <= datetime.now(UTC)
        or visitor.publication_version != row.version
    ):
        raise AppError(401, "visitor_authentication_required", "Visitor session expired or invalid")
    request.state.visitor_session_id = visitor.id
    request.state.visitor_digest = digest
    request.state.publication_id = pid
    # A delegated owner is retained for existing foreign keys, while audit actor remains anonymous.
    return ExecutionContext(
        tenant_id=row.tenant_id,
        user_id=row.created_by,
        membership_id=link.id,
        role="visitor",
        request_id=request.state.request_id,
        public_session_id=visitor.id,
        conversation_id=visitor.conversation_id,
        agent_config_id=row.agent_config_id,
    )


def resume_visitor(db, context, request):
    current = authenticate(db, request.state.publication_id, context.public_session_id, request)
    if (
        current.tenant_id != context.tenant_id
        or current.conversation_id != context.conversation_id
        or current.agent_config_id != context.agent_config_id
    ):
        raise AppError(403, "visitor_access_revoked", "Public delivery is no longer authorized")
    return current


def public_tool_allowed(db, context, tool_id):
    visitor = db.get(VisitorSession, context.public_session_id, populate_existing=True)
    publication = (
        db.get(Publication, visitor.publication_id, populate_existing=True) if visitor else None
    )
    return bool(
        publication
        and publication.enabled
        and not publication.revoked_at
        and publication.version == visitor.publication_version
        and str(tool_id) in publication.public_tool_ids
    )


def turn(db, context, data, request):
    get_owned(db, Conversation, context, context.conversation_id, lock=True)
    context = resume_visitor(db, context, request)
    visitor = get_owned(db, VisitorSession, context, context.public_session_id, refresh=True)
    if visitor.ended_at:
        raise AppError(409, "conversation_closed", "Start a new visitor session")
    return agent_turns.turn(
        db,
        context,
        visitor.conversation_id,
        AgentTurnInput(
            agent_config_id=context.agent_config_id,
            content=data.content,
            idempotency_key=data.idempotency_key,
        ),
        request,
    )


def delivery_guard(db, context, request):
    # Owner/tenant/member locks are acquired by authenticate before conversation/config.
    # Never carry these locks across provider/tool I/O: all callers commit before transport.
    get_owned(db, Conversation, context, context.conversation_id, lock=True)
    db.scalar(
        select(VisitorSession)
        .where(
            VisitorSession.id == context.public_session_id,
            VisitorSession.tenant_id == context.tenant_id,
        )
        .with_for_update(read=True)
    )
    db.scalar(
        select(AgentConfig)
        .where(
            AgentConfig.id == context.agent_config_id, AgentConfig.tenant_id == context.tenant_id
        )
        .with_for_update(read=True)
    )
    return resume_visitor(db, context, request)


def history(db, context, request, limit, offset):
    context = delivery_guard(db, context, request)
    rows = conversations.history(db, context, context.conversation_id, limit, offset, request, True)
    result = []
    for row in rows:
        metadata = row.message_metadata if hasattr(row, "message_metadata") else row.metadata
        if row.role not in {"user", "assistant"} or (
            row.role == "assistant"
            and row.source != "manual"
            and not metadata.get("final")
            and not metadata.get("redacted")
        ):
            continue
        tools = []
        if row.role == "assistant" and row.model_call_id and not metadata.get("redacted"):
            call = get_owned(db, ModelCall, context, row.model_call_id)
            executions = agent_turns.executions(db, context, call.id)
            tool_execution.ensure_delivery(db, context, call, executions, request)
            tools = [
                {
                    "name": e.tool_name,
                    "status": e.status,
                    "data": e.result,
                    "error_category": e.error_category,
                }
                for e in executions
            ]
        result.append(
            {
                "role": row.role,
                "content": row.content,
                "created_at": row.created_at,
                "citations": metadata.get("citations", []),
                "tool_results": tools,
            }
        )
    return result


def describe(db, context, row):
    config = get_owned(db, AgentConfig, context, row.agent_config_id)
    owner = db.get(User, row.created_by)
    membership = db.scalar(
        select(Membership).where(
            Membership.tenant_id == context.tenant_id,
            Membership.user_id == row.created_by,
            Membership.role == "admin",
            Membership.status == "active",
        )
    )
    return {
        field: getattr(row, field)
        for field in (
            "id",
            "agent_config_id",
            "name",
            "enabled",
            "version",
            "agent_version",
            "public_tool_ids",
            "revoked_at",
            "created_at",
        )
    } | {
        "requires_republish": config.version != row.agent_version,
        "available": bool(
            row.enabled
            and not row.revoked_at
            and config.enabled
            and config.version == row.agent_version
            and owner
            and owner.status == "active"
            and membership
        ),
    }


def end(db, context, request):
    conv = get_owned(db, Conversation, context, context.conversation_id, lock=True)
    from support_agent.services.chat import expire_active_calls

    expire_active_calls(db, context, conv.id, request)
    visitor = get_owned(db, VisitorSession, context, context.public_session_id, lock=True)
    visitor.ended_at = datetime.now(UTC)
    conv.status = "closed"
    conv.support_state = "resolved"
    record(db, request, "visitor.end", "visitor_session", visitor.id, tenant_id=context.tenant_id)
