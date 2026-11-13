"""Private product workflows; every endpoint uses staff identity and tenant RLS."""

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from starlette.background import BackgroundTask

from support_agent.dependencies import Database, TenantAdmin, TenantContext
from support_agent.models import CustomerExport
from support_agent.product_schemas import (
    DraftAction,
    DraftCreate,
    DraftOut,
    ExportOut,
    ExportPreview,
    ExportRequest,
    IndexConfig,
    IndexOut,
    IndexRequest,
    IndexStatus,
    RetrievalInput,
    RetrievalOut,
)
from support_agent.services import customer_exports, drafts, search, vector_index

router = APIRouter(tags=["Private product capabilities"])


@router.get("/knowledge-bases/{kid}/index", response_model=IndexStatus)
def index_status(kid: UUID, db: Database, context: TenantAdmin):
    return vector_index.status(db, context, kid)


@router.put("/knowledge-bases/{kid}/index", response_model=IndexOut)
def index_config(
    kid: UUID, data: IndexConfig, request: Request, db: Database, context: TenantAdmin
):
    return vector_index.save(db, context, kid, data, request)


@router.post("/knowledge-bases/{kid}/index", response_model=IndexOut)
def index_queue(
    kid: UUID, data: IndexRequest, request: Request, db: Database, context: TenantAdmin
):
    return vector_index.queue(db, context, kid, data, request)


@router.post("/knowledge-bases/{kid}/diagnostics", response_model=RetrievalOut)
def retrieval(
    kid: UUID, data: RetrievalInput, request: Request, db: Database, context: TenantAdmin
):
    return search.diagnose(db, context, kid, data, request)


@router.get("/customers/{cid}/export-preview", response_model=ExportPreview)
def export_preview(cid: UUID, db: Database, context: TenantAdmin):
    return customer_exports.preview(db, context, cid)


@router.post("/customers/{cid}/exports", response_model=ExportOut)
def export_request(
    cid: UUID, data: ExportRequest, request: Request, db: Database, context: TenantAdmin
):
    return customer_exports.create(db, context, cid, data, request)


@router.get("/customers/{cid}/exports", response_model=list[ExportOut])
def export_list(
    cid: UUID,
    db: Database,
    context: TenantAdmin,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    from support_agent.models import Customer
    from support_agent.services.resources import get_owned

    get_owned(db, Customer, context, cid)
    return list(
        db.scalars(
            select(CustomerExport)
            .where(
                CustomerExport.tenant_id == context.tenant_id,
                CustomerExport.customer_id == cid,
                CustomerExport.requested_by == context.user_id,
            )
            .order_by(CustomerExport.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )


@router.get("/customer-exports/{eid}", response_model=ExportOut)
def export_detail(eid: UUID, request: Request, db: Database, context: TenantAdmin):
    return customer_exports.accessible(db, context, eid, request)[0]


@router.get("/customer-exports/{eid}/content")
def export_download(eid: UUID, request: Request, db: Database, context: TenantAdmin):
    archive = customer_exports.download(db, context, eid, request)
    return StreamingResponse(
        iter(lambda: archive.read(65536), b""),
        media_type="application/octet-stream",
        background=BackgroundTask(archive.close),
        headers={
            "Content-Disposition": f'attachment; filename="customer-export-{eid}.zip"',
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/conversations/{cid}/drafts", response_model=DraftOut)
def draft_create(
    cid: UUID, data: DraftCreate, request: Request, db: Database, context: TenantContext
):
    return drafts.create(db, context, cid, data, request)


@router.get("/conversations/{cid}/drafts", response_model=list[DraftOut])
def draft_list(
    cid: UUID,
    request: Request,
    db: Database,
    context: TenantContext,
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    return drafts.listing(db, context, cid, request, limit=limit, offset=offset)


@router.get("/reply-drafts/{did}", response_model=DraftOut)
def draft_detail(did: UUID, request: Request, db: Database, context: TenantContext):
    return drafts.view(db, context, did, request)


@router.post("/reply-drafts/{did}/actions", response_model=DraftOut)
def draft_action(
    did: UUID, data: DraftAction, request: Request, db: Database, context: TenantContext
):
    return drafts.action(db, context, did, data, request)
