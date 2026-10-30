from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from support_agent.dependencies import Database, TenantAdmin, TenantContext
from support_agent.models import AgentConfig, AgentTool, ToolDefinition, ToolExecution
from support_agent.services import tools
from support_agent.services.resources import get_owned, list_owned
from support_agent.tool_protocol import (
    AgentToolGrant,
    AgentToolOut,
    CapabilityOut,
    ExecutionOut,
    ToolCall,
    ToolOut,
    ToolPatch,
    ToolResult,
    ToolSpec,
)

router = APIRouter(tags=["Tool definitions and execution"])


@router.post("/tools", response_model=ToolOut, status_code=201)
def register(data: ToolSpec, request: Request, db: Database, context: TenantAdmin):
    return tools.register(db, context, data, request)


@router.get("/tools", response_model=list[ToolOut])
def list_tools(
    db: Database,
    context: TenantContext,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return list_owned(db, ToolDefinition, context, limit, offset)


@router.get("/tools/{tool_id}", response_model=ToolOut)
def detail(tool_id: UUID, db: Database, context: TenantContext):
    return get_owned(db, ToolDefinition, context, tool_id)


@router.patch("/tools/{tool_id}", response_model=ToolOut)
def set_enabled(
    tool_id: UUID, data: ToolPatch, request: Request, db: Database, context: TenantAdmin
):
    return tools.set_enabled(db, context, tool_id, data, request)


@router.post("/tools/{tool_id}/validate", response_model=ToolResult)
def validate(tool_id: UUID, data: ToolCall, request: Request, db: Database, context: TenantContext):
    return tools.validate(db, context, tool_id, data, request)


@router.post(
    "/tools/{tool_id}/execute",
    response_model=ToolResult,
    description="Executes an authorized static read-only capability with full context. Legacy context-free calls remain disabled (501).",
    responses={501: {"model": ToolResult}},
)
def execute(
    tool_id: UUID,
    data: ToolCall,
    request: Request,
    db: Database,
    context: TenantContext,
    response: Response,
):
    result = tools.execute(db, context, tool_id, data, request)
    if result.status == "rejected":
        response.status_code = 501
    return result


@router.get("/tool-capabilities", response_model=list[CapabilityOut])
def capabilities(request: Request, context: TenantAdmin):
    return [
        {
            "key": c.key,
            "version": c.version,
            "parameters": c.parameters,
            "output_schema": c.output_schema,
            "execution_type": "read_only" if c.read_only else "write",
        }
        for c in request.app.state.tool_registry.items.values()
    ]


@router.put("/agent-configs/{config_id}/tools/{tool_id}", response_model=AgentToolOut)
def grant(
    config_id: UUID,
    tool_id: UUID,
    data: AgentToolGrant,
    request: Request,
    db: Database,
    context: TenantAdmin,
):
    return tools.grant(db, context, config_id, tool_id, data, request)


@router.get("/agent-configs/{config_id}/tools", response_model=list[AgentToolOut])
def grants(config_id: UUID, db: Database, context: TenantContext):
    get_owned(db, AgentConfig, context, config_id)
    return db.scalars(
        select(AgentTool)
        .where(AgentTool.tenant_id == context.tenant_id, AgentTool.agent_config_id == config_id)
        .limit(100)
    ).all()


@router.get("/tool-executions", response_model=list[ExecutionOut])
def executions(
    request: Request,
    db: Database,
    context: TenantAdmin,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    from support_agent.services.tool_execution import execution_view, reconcile_executions

    reconcile_executions(db, context, request)
    return [
        execution_view(db, context, row, request)
        for row in list_owned(db, ToolExecution, context, limit, offset)
    ]


@router.get("/tool-executions/{execution_id}", response_model=ExecutionOut)
def execution(execution_id: UUID, request: Request, db: Database, context: TenantAdmin):
    from support_agent.services.tool_execution import execution_view, reconcile_executions

    row = get_owned(db, ToolExecution, context, execution_id)
    reconcile_executions(db, context, request, call_id=row.model_call_id)
    return execution_view(db, context, row, request)
