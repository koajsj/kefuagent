from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from support_agent.dependencies import Database, TenantAdmin, TenantContext
from support_agent.errors import AppError
from support_agent.ingestion import MAX_FILE_BYTES
from support_agent.models import Document, KnowledgeBase
from support_agent.rag_schemas import (
    DocumentOut,
    KnowledgeCreate,
    KnowledgeOut,
    SearchHit,
    SearchInput,
)
from support_agent.services import knowledge
from support_agent.services.resources import get_owned, list_owned

router = APIRouter(tags=["Knowledge"])


@router.post("/knowledge-bases", response_model=KnowledgeOut, status_code=201)
def create(data: KnowledgeCreate, request: Request, db: Database, context: TenantAdmin):
    return knowledge.create(db, context, data, request)


@router.get("/knowledge-bases", response_model=list[KnowledgeOut])
def bases(
    db: Database,
    context: TenantContext,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return list_owned(db, KnowledgeBase, context, limit, offset)


@router.get("/knowledge-bases/{knowledge_base_id}", response_model=KnowledgeOut)
def detail(knowledge_base_id: UUID, db: Database, context: TenantContext):
    return get_owned(db, KnowledgeBase, context, knowledge_base_id)


@router.patch("/knowledge-bases/{knowledge_base_id}", response_model=KnowledgeOut)
def update(
    knowledge_base_id: UUID,
    data: KnowledgeCreate,
    request: Request,
    db: Database,
    context: TenantAdmin,
):
    return knowledge.update(db, context, knowledge_base_id, data, request)


@router.delete("/knowledge-bases/{knowledge_base_id}", status_code=204)
def delete_base(knowledge_base_id: UUID, request: Request, db: Database, context: TenantAdmin):
    knowledge.delete_base(db, context, knowledge_base_id, request)


@router.post(
    "/knowledge-bases/{knowledge_base_id}/documents",
    response_model=DocumentOut,
    status_code=201,
    responses={200: {"model": DocumentOut, "description": "Identical content already registered"}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "additionalProperties": False,
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
)
async def upload(
    knowledge_base_id: UUID,
    request: Request,
    response: Response,
    db: Database,
    context: TenantAdmin,
):
    async with request.form(max_files=1, max_fields=0, max_part_size=MAX_FILE_BYTES) as form:
        file = form.get("file")
        if len(form.multi_items()) != 1 or not isinstance(file, UploadFile):
            raise AppError(422, "invalid_document", "Upload exactly one file")
        content = await file.read(MAX_FILE_BYTES + 1)
        result, created = await run_in_threadpool(
            knowledge.upload, db, context, knowledge_base_id, file.filename, content, request
        )
        response.status_code = 201 if created else 200
        return result


@router.get("/knowledge-bases/{knowledge_base_id}/documents", response_model=list[DocumentOut])
def documents(
    knowledge_base_id: UUID,
    db: Database,
    context: TenantContext,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    from sqlalchemy import select

    get_owned(db, KnowledgeBase, context, knowledge_base_id)
    return db.scalars(
        select(Document)
        .where(
            Document.tenant_id == context.tenant_id, Document.knowledge_base_id == knowledge_base_id
        )
        .order_by(Document.created_at, Document.id)
        .limit(limit)
        .offset(offset)
    ).all()


@router.get("/documents/{document_id}", response_model=DocumentOut)
def document(document_id: UUID, db: Database, context: TenantContext):
    return get_owned(db, Document, context, document_id)


@router.post("/documents/{document_id}/reprocess", response_model=DocumentOut)
def reprocess(document_id: UUID, request: Request, db: Database, context: TenantAdmin):
    return knowledge.process(db, context, document_id, request)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: UUID, request: Request, db: Database, context: TenantAdmin):
    knowledge.delete_document(db, context, document_id, request)


@router.post("/knowledge-bases/{knowledge_base_id}/search", response_model=list[SearchHit])
def search(
    knowledge_base_id: UUID,
    data: SearchInput,
    request: Request,
    db: Database,
    context: TenantContext,
):
    return request.app.state.retriever.search(
        db, context, [knowledge_base_id], data.query, data.limit
    )
