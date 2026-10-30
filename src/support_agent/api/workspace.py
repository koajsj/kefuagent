from uuid import UUID

from fastapi import APIRouter, Request

from support_agent.dependencies import Database, TenantAdmin, TenantContext
from support_agent.models import AgentConfig
from support_agent.rag_schemas import KnowledgeBindings
from support_agent.services import workspace
from support_agent.services.resources import get_owned
from support_agent.workspace_schemas import (
    KnowledgeBindingsOut,
    ReadinessOut,
    StatisticsOut,
    WorkspaceOut,
)

router = APIRouter(tags=["Workspace"])


@router.get("/workspace", response_model=WorkspaceOut)
def info(request: Request, context: TenantContext):
    return {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "role": context.role,
        "external_models_enabled": request.app.state.settings.allow_external_models,
    }


@router.get("/setup-status", response_model=ReadinessOut)
def setup(request: Request, db: Database, context: TenantAdmin):
    return workspace.readiness(db, context, request)


@router.get("/agent-configs/{config_id}/knowledge-bases", response_model=KnowledgeBindingsOut)
def bindings(config_id: UUID, db: Database, context: TenantContext):
    config = get_owned(db, AgentConfig, context, config_id)
    return {
        "knowledge_base_ids": workspace.knowledge_ids(db, context, config_id),
        "config_version": config.version,
    }


@router.put("/agent-configs/{config_id}/knowledge-bases", response_model=KnowledgeBindingsOut)
def set_bindings(
    config_id: UUID, data: KnowledgeBindings, request: Request, db: Database, context: TenantAdmin
):
    return workspace.set_knowledge(db, context, config_id, data, request)


@router.get("/workspace/statistics", response_model=StatisticsOut)
def statistics(db: Database, context: TenantContext):
    return workspace.statistics(db, context)
