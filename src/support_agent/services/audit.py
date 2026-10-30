from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from support_agent.models import AuditEvent


def record(
    db: Session,
    request,
    action: str,
    resource_type: str,
    resource_id: UUID | None = None,
    *,
    tenant_id: UUID | None = None,
    outcome: str = "success",
    reason: str | None = None,
    details: dict | None = None,
):
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=getattr(request.state, "actor_id", None),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request.state.request_id,
            outcome=outcome,
            reason=reason,
            details=details or {},
        )
    )


def list_events(db: Session, tenant_id: UUID | None, limit: int, offset: int):
    return db.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


def list_platform_events(db: Session, limit: int, offset: int):
    return db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.action.in_(
                [
                    "tenant.create",
                    "tenant.status",
                    "user.create",
                    "user.status",
                    "user.bootstrap",
                    "auth.login",
                    "auth.logout",
                ]
            )
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


def record_failure(db: Session, request, reason: str):
    """Record only route templates and parsed UUIDs, never raw paths, headers or inputs."""
    path = getattr(request.scope.get("route"), "path", "")
    params = request.path_params
    resource_type = "request"
    resource_id = None
    for field, kind in [
        ("execution_id", "tool_execution"),
        ("document_id", "document"),
        ("knowledge_base_id", "knowledge_base"),
        ("credential_id", "credential"),
        ("call_id", "model_call"),
        ("tool_id", "tool"),
        ("config_id", "agent_config"),
        ("conversation_id", "conversation"),
        ("membership_id", "membership"),
        ("user_id", "user"),
        ("tenant_id", "tenant"),
    ]:
        if field in params:
            resource_type = kind
            try:
                resource_id = UUID(str(params[field]))
            except ValueError:
                resource_id = None
            break
    action = "request.denied"
    for prefix, kind in [
        ("/tool-executions", "tool_execution"),
        ("/documents", "document"),
        ("/knowledge-bases", "knowledge_base"),
        ("/model-credentials", "credential"),
        ("/model-calls", "model_call"),
        ("/tools", "tool"),
        ("/agent-configs", "agent_config"),
        ("/conversations", "conversation"),
        ("/memberships", "membership"),
        ("/users", "user"),
        ("/tenants", "tenant"),
    ]:
        if path.startswith("/api/v1" + prefix):
            suffix = {
                "POST": "create",
                "PUT": "update",
                "PATCH": "update",
                "GET": "read",
                "DELETE": "delete",
            }.get(request.method, "denied")
            if path.endswith("/execute"):
                suffix = "execute"
            if path.endswith("/validate"):
                suffix = "validate"
            if path.endswith("/chat"):
                suffix = "chat"
            if path.endswith("/agent-turns"):
                suffix = "agent_turn"
            if path.endswith("/reprocess"):
                suffix = "reprocess"
            if path.endswith("/test-connection"):
                suffix = "connection_test"
            action = kind + "." + suffix
            break
    if path.startswith("/api/v1/auth/"):
        action = "auth." + path.rsplit("/", 1)[-1]
    record(
        db,
        request,
        action,
        resource_type,
        resource_id,
        tenant_id=getattr(request.state, "tenant_id", None),
        outcome="failure",
        reason=reason,
    )
