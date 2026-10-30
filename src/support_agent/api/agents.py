from uuid import UUID

from fastapi import APIRouter, Query, Request

from support_agent.dependencies import Database, TenantAdmin, TenantContext
from support_agent.models import AgentConfig
from support_agent.schemas import AgentCreate, AgentOut, AgentUpdate
from support_agent.services import agents
from support_agent.services.resources import get_owned, list_owned

router = APIRouter(prefix="/agent-configs", tags=["Agent configurations"])


@router.post("", response_model=AgentOut, status_code=201)
def create(data: AgentCreate, request: Request, db: Database, context: TenantAdmin):
    return agents.create(db, context, data, request)


@router.get("", response_model=list[AgentOut])
def list_configs(
    db: Database,
    context: TenantContext,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return list_owned(db, AgentConfig, context, limit, offset)


@router.get("/{config_id}", response_model=AgentOut)
def detail(config_id: UUID, db: Database, context: TenantContext):
    return get_owned(db, AgentConfig, context, config_id)


@router.put("/{config_id}", response_model=AgentOut)
def update(
    config_id: UUID, data: AgentUpdate, request: Request, db: Database, context: TenantAdmin
):
    return agents.update(db, context, config_id, data, request)
