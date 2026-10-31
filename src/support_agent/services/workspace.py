"""Workspace configuration and Agent knowledge access, reusing tenant authorization."""

from sqlalchemy import delete, func, select

from support_agent.credentials import Keyring, cipher
from support_agent.errors import AppError
from support_agent.models import AgentConfig, AgentKnowledgeBase, KnowledgeBase, ModelCredential
from support_agent.services.audit import record
from support_agent.services.resources import get_owned


def knowledge_ids(db, context, config_id):
    return list(
        db.scalars(
            select(AgentKnowledgeBase.knowledge_base_id)
            .where(
                AgentKnowledgeBase.tenant_id == context.tenant_id,
                AgentKnowledgeBase.agent_config_id == config_id,
            )
            .order_by(AgentKnowledgeBase.knowledge_base_id)
        )
    )


def set_knowledge(db, context, config_id, data, request):
    config = get_owned(db, AgentConfig, context, config_id, lock=True)
    if data.expected_version is not None and config.version != data.expected_version:
        raise AppError(409, "version_conflict", "Configuration changed; reload before saving")
    for kid in sorted(data.knowledge_base_ids):
        base = get_owned(db, KnowledgeBase, context, kid, lock=True)
        if base.status != "active":
            raise AppError(409, "knowledge_base_deleting", "Knowledge base is not active")
    current = set(knowledge_ids(db, context, config_id))
    selected = set(data.knowledge_base_ids)
    if selected != current:
        db.execute(
            delete(AgentKnowledgeBase).where(
                AgentKnowledgeBase.tenant_id == context.tenant_id,
                AgentKnowledgeBase.agent_config_id == config_id,
            )
        )
        for kid in selected:
            db.add(
                AgentKnowledgeBase(
                    tenant_id=context.tenant_id,
                    agent_config_id=config_id,
                    knowledge_base_id=kid,
                    created_by=context.user_id,
                )
            )
        config.version += 1
        record(
            db,
            request,
            "agent_config.knowledge",
            "agent_config",
            config.id,
            tenant_id=context.tenant_id,
            details={"knowledge_base_count": len(selected)},
        )
        db.flush()
    return {"knowledge_base_ids": sorted(selected), "config_version": config.version}


def readiness(db, context, request):
    settings = request.app.state.settings
    try:
        ring = Keyring(settings)
        if ring.active not in ring.keys:
            raise AppError(503, "credential_key_unavailable", "No active key")
        cipher(ring.keys[ring.active])
        key_ready = True
    except AppError:
        key_ready = False
    enabled_credentials = db.scalar(
        select(func.count())
        .select_from(ModelCredential)
        .where(ModelCredential.tenant_id == context.tenant_id, ModelCredential.enabled.is_(True))
    )
    enabled_agents, demo_agents = db.execute(
        select(
            func.count().filter(AgentConfig.enabled.is_(True)),
            func.count().filter(AgentConfig.enabled.is_(True) & (AgentConfig.provider == "demo")),
        ).where(AgentConfig.tenant_id == context.tenant_id)
    ).one()
    return {
        "external_models_enabled": settings.allow_external_models,
        "credential_encryption_ready": key_ready,
        "public_rate_key_ready": settings.public_rate_key is not None,
        "model_allowed_hosts": settings.model_allowed_hosts,
        "enabled_credentials": enabled_credentials,
        "enabled_agents": enabled_agents,
        "demo_agents": demo_agents,
        "web_origin": settings.web_origin,
        "real_model_verified": False,
    }


def statistics(db, context):
    from support_agent.models import Conversation, Document, ModelCall, ToolExecution

    def count(model):
        return db.scalar(
            select(func.count()).select_from(model).where(model.tenant_id == context.tenant_id)
        )

    calls = db.execute(
        select(
            func.count(),
            func.sum(ModelCall.input_tokens),
            func.sum(ModelCall.output_tokens),
            func.count().filter(
                ModelCall.input_tokens.is_(None) | ModelCall.output_tokens.is_(None)
            ),
            func.count().filter(ModelCall.status == "failed"),
        ).where(ModelCall.tenant_id == context.tenant_id)
    ).one()
    return {
        "agents": count(AgentConfig),
        "conversations": count(Conversation),
        "documents": count(Document),
        "tool_executions": count(ToolExecution),
        "model_calls": calls[0],
        "known_input_tokens": calls[1] or 0,
        "known_output_tokens": calls[2] or 0,
        "calls_with_unknown_usage": calls[3],
        "failed_calls": calls[4],
        "cost": None,
    }
