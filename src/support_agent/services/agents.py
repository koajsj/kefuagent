from support_agent.errors import AppError
from support_agent.models import AgentConfig
from support_agent.providers import validate_base_url
from support_agent.services.audit import record
from support_agent.services.resources import get_owned


def create(db, context, data, request):
    if data.base_url is not None:
        validate_base_url(data.base_url, request.app.state.settings.model_allowed_hosts)
    config = AgentConfig(
        **data.model_dump(), tenant_id=context.tenant_id, created_by=context.user_id
    )
    db.add(config)
    db.flush()
    record(
        db, request, "agent_config.create", "agent_config", config.id, tenant_id=context.tenant_id
    )
    return config


def update(db, context, resource_id, data, request):
    config = get_owned(db, AgentConfig, context, resource_id, lock=True)
    if data.base_url is not None:
        validate_base_url(data.base_url, request.app.state.settings.model_allowed_hosts)
    if config.version != data.expected_version:
        raise AppError(409, "version_conflict", "Configuration has changed; reload and retry")
    for field, value in data.model_dump(exclude={"expected_version"}).items():
        setattr(config, field, value)
    config.version += 1
    db.flush()
    record(
        db, request, "agent_config.update", "agent_config", config.id, tenant_id=context.tenant_id
    )
    return config
