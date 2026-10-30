from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from support_agent.dependencies import Database, TenantAdmin
from support_agent.models import Publication
from support_agent.public_schemas import (
    PublicationCreate,
    PublicationOut,
    PublicationPatch,
    PublicInfo,
    PublicMessage,
    PublicRun,
    VisitorOut,
    VisitorTurn,
)
from support_agent.services import public_delivery as delivery
from support_agent.services.resources import list_owned
from support_agent.tool_protocol import AgentTurnOut

router = APIRouter(tags=["Public delivery"])


@router.post("/publications", response_model=PublicationOut, status_code=201)
def create(data: PublicationCreate, request: Request, db: Database, context: TenantAdmin):
    return delivery.describe(db, context, delivery.create(db, context, data, request))


@router.get("/publications", response_model=list[PublicationOut])
def publications(
    db: Database,
    context: TenantAdmin,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return [
        delivery.describe(db, context, row)
        for row in list_owned(db, Publication, context, limit, offset)
    ]


@router.patch("/publications/{pid}", response_model=PublicationOut)
def change(pid: UUID, data: PublicationPatch, request: Request, db: Database, context: TenantAdmin):
    return delivery.describe(db, context, delivery.change(db, context, pid, data, request))


@router.delete("/publications/{pid}", status_code=204)
def revoke(pid: UUID, request: Request, db: Database, context: TenantAdmin):
    delivery.revoke(db, context, pid, request)


@router.get("/public/{pid}", response_model=PublicInfo)
def info(pid: UUID, request: Request, db: Database):
    row, config, _ = delivery.locate(db, pid, request)
    return {
        "id": row.id,
        "name": row.name,
        "mode": "demo" if config.provider == "demo" else "model",
        "version": row.version,
    }


@router.post("/public/{pid}/sessions", response_model=VisitorOut, status_code=201)
def start(pid: UUID, request: Request, db: Database):
    return delivery.start(db, pid, request)


def visitor(pid: UUID, sid: UUID, request: Request, db: Database):
    return delivery.authenticate(db, pid, sid, request)


Visitor = Annotated[object, Depends(visitor)]


@router.post("/public/{pid}/sessions/{sid}/turns", response_model=AgentTurnOut)
def turn(data: VisitorTurn, request: Request, db: Database, context: Visitor):
    return delivery.turn(db, context, data, request)


@router.get("/public/{pid}/sessions/{sid}/messages", response_model=list[PublicMessage])
def history(
    request: Request,
    db: Database,
    context: Visitor,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return delivery.history(db, context, request, limit, offset)


@router.post("/public/{pid}/sessions/{sid}/end", status_code=204)
def end(request: Request, db: Database, context: Visitor):
    delivery.end(db, context, request)


@router.get("/public/{pid}/sessions/{sid}/status", response_model=PublicRun | None)
def status(request: Request, db: Database, context: Visitor):
    from sqlalchemy import select

    from support_agent.models import ModelCall
    from support_agent.services.chat import reconcile_expired

    context = delivery.delivery_guard(db, context, request)
    row = db.scalar(
        select(ModelCall)
        .where(
            ModelCall.tenant_id == context.tenant_id,
            ModelCall.conversation_id == context.conversation_id,
            ModelCall.visitor_session_id == context.public_session_id,
        )
        .order_by(ModelCall.created_at.desc())
        .limit(1)
    )
    return reconcile_expired(db, context, [row], request)[0] if row else None
