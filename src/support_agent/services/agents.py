from sqlalchemy import select

from support_agent.dependencies import locked_staff_context
from support_agent.errors import AppError
from support_agent.models import AgentConfig, AuditEvent
from support_agent.providers import validate_base_url
from support_agent.services.audit import record
from support_agent.services.resources import get_owned


def listing(db, context, limit, offset, q):
    stmt = select(AgentConfig).where(AgentConfig.tenant_id == context.tenant_id)
    if q.strip():
        stmt = stmt.where(AgentConfig.name.icontains(q.strip(), autoescape=True))
    return db.scalars(
        stmt.order_by(AgentConfig.created_at, AgentConfig.id).limit(limit).offset(offset)
    ).all()


def create(db, context, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    if data.base_url is not None:
        validate_base_url(data.base_url, request.app.state.settings.model_allowed_hosts)
    config = AgentConfig(
        **data.model_dump(), tenant_id=context.tenant_id, created_by=context.user_id
    )
    db.add(config)
    db.flush()
    record(
        db,
        request,
        "agent_config.create",
        "agent_config",
        config.id,
        tenant_id=context.tenant_id,
        details={"config_version": config.version},
    )
    return config


def update(db, context, resource_id, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    config = get_owned(db, AgentConfig, context, resource_id, lock=True)
    if data.base_url is not None:
        validate_base_url(data.base_url, request.app.state.settings.model_allowed_hosts)
    if config.version != data.expected_version:
        raise AppError(409, "version_conflict", "Configuration has changed; reload and retry")
    values = data.model_dump(exclude={"expected_version"})
    changed = sorted(field for field, value in values.items() if value != getattr(config, field))
    for field, value in values.items():
        setattr(config, field, value)
    config.version += 1
    db.flush()
    record(
        db,
        request,
        "agent_config.update",
        "agent_config",
        config.id,
        tenant_id=context.tenant_id,
        details={"config_version": config.version, "changed_fields": changed},
    )
    return config


def changes(db, context, config_id, limit, offset):
    get_owned(db, AgentConfig, context, config_id)
    rows = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == context.tenant_id,
            AuditEvent.resource_type == "agent_config",
            AuditEvent.resource_id == config_id,
            AuditEvent.action.in_(
                ["agent_config.create", "agent_config.update", "agent_config.knowledge"]
            ),
            AuditEvent.outcome == "success",
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        {
            "id": row.id,
            "actor_id": row.actor_id,
            "action": row.action,
            "created_at": row.created_at,
            "request_id": row.request_id,
            "config_version": row.details.get("config_version"),
            "changed_fields": row.details.get("changed_fields", []),
        }
        for row in rows
    ]
