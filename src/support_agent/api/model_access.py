from uuid import UUID

from fastapi import APIRouter, Query, Request

from support_agent.dependencies import Database, TenantAdmin
from support_agent.models import ModelCall, ModelCredential
from support_agent.rag_schemas import CallOut, CredentialCreate, CredentialOut, UsageLimitsOut
from support_agent.services import chat, model_configs
from support_agent.services.resources import get_owned, list_owned

router = APIRouter(tags=["Model access and usage"])


@router.get("/usage-limits", response_model=UsageLimitsOut)
def usage_limits(request: Request, db: Database, context: TenantAdmin):
    from support_agent.services.limits import view

    return view(db, context, request)


@router.post("/model-credentials", response_model=CredentialOut, status_code=201)
def create(data: CredentialCreate, request: Request, db: Database, context: TenantAdmin):
    return model_configs.create_credential(db, context, data, request)


@router.get("/model-credentials", response_model=list[CredentialOut])
def credentials(
    db: Database,
    context: TenantAdmin,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return list_owned(db, ModelCredential, context, limit, offset)


@router.get("/model-credentials/{credential_id}", response_model=CredentialOut)
def credential(credential_id: UUID, db: Database, context: TenantAdmin):
    return get_owned(db, ModelCredential, context, credential_id)


@router.put("/model-credentials/{credential_id}", response_model=CredentialOut)
def update(
    credential_id: UUID,
    data: CredentialCreate,
    request: Request,
    db: Database,
    context: TenantAdmin,
):
    return model_configs.update_credential(db, context, credential_id, data, request)


@router.delete("/model-credentials/{credential_id}", status_code=204)
def delete(credential_id: UUID, request: Request, db: Database, context: TenantAdmin):
    model_configs.delete_credential(db, context, credential_id, request)


@router.post("/agent-configs/{config_id}/test-connection", response_model=CallOut)
def test_connection(config_id: UUID, request: Request, db: Database, context: TenantAdmin):
    return chat.test_connection(db, context, config_id, request)


@router.get("/model-calls", response_model=list[CallOut])
def calls(
    request: Request,
    db: Database,
    context: TenantAdmin,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return chat.reconcile_expired(
        db, context, list_owned(db, ModelCall, context, limit, offset), request
    )


@router.get("/model-calls/{call_id}", response_model=CallOut)
def call(call_id: UUID, request: Request, db: Database, context: TenantAdmin):
    return chat.reconcile_expired(
        db, context, [get_owned(db, ModelCall, context, call_id)], request
    )[0]
