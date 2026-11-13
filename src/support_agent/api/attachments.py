from datetime import datetime
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from support_agent.api.public_delivery import Visitor
from support_agent.dependencies import Database, TenantContext
from support_agent.errors import AppError
from support_agent.ingestion import MAX_FILE_BYTES
from support_agent.schemas import Output
from support_agent.services import attachments

router = APIRouter(tags=["Conversation attachments"])


class AttachmentOut(Output):
    id: UUID
    filename: str
    size_bytes: int
    status: str
    public: bool
    created_at: datetime


async def receive(request, db, context, cid, key):
    async with request.form(max_files=1, max_fields=1, max_part_size=MAX_FILE_BYTES) as form:
        file = form.get("file")
        visibility = form.get("public", "false")
        if (
            not isinstance(file, UploadFile)
            or set(form) - {"file", "public"}
            or len(form.multi_items()) > 2
            or visibility not in {"true", "false"}
        ):
            raise AppError(
                422, "invalid_document", "Upload one file and optional explicit public visibility"
            )
        content = await file.read(MAX_FILE_BYTES + 1)
        return await run_in_threadpool(
            attachments.upload,
            db,
            context,
            cid,
            key,
            file.filename,
            content,
            visibility == "true",
            request,
        )


def file_response(db, context, cid, aid, request):
    data, filename = attachments.download(db, context, cid, aid, request)
    return Response(
        data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe=""),
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/conversations/{cid}/attachments", response_model=list[AttachmentOut])
def listing(
    cid: UUID,
    request: Request,
    db: Database,
    context: TenantContext,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return attachments.listing(db, context, cid, limit, offset, request)


@router.post("/conversations/{cid}/attachments", response_model=AttachmentOut, status_code=201)
async def upload(
    cid: UUID, upload_id: UUID, request: Request, db: Database, context: TenantContext
):
    return await receive(request, db, context, cid, upload_id)


@router.get("/conversations/{cid}/attachments/{aid}/content")
def download(cid: UUID, aid: UUID, request: Request, db: Database, context: TenantContext):
    return file_response(db, context, cid, aid, request)


@router.get("/public/{pid}/sessions/{sid}/attachments", response_model=list[AttachmentOut])
def public_listing(
    request: Request,
    db: Database,
    context: Visitor,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return attachments.listing(db, context, context.conversation_id, limit, offset, request)


@router.post(
    "/public/{pid}/sessions/{sid}/attachments", response_model=AttachmentOut, status_code=201
)
async def public_upload(upload_id: UUID, request: Request, db: Database, context: Visitor):
    return await receive(request, db, context, context.conversation_id, upload_id)


@router.get("/public/{pid}/sessions/{sid}/attachments/{aid}/content")
def public_download(aid: UUID, request: Request, db: Database, context: Visitor):
    return file_response(db, context, context.conversation_id, aid, request)
