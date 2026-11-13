from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from support_agent.chunk_schemas import ChunkEdit, ChunkMutation, ChunkRestore, ChunkVersion
from support_agent.dependencies import Database, TenantAdmin, TenantContext
from support_agent.errors import AppError
from support_agent.ingestion import MAX_FILE_BYTES
from support_agent.models import Document, KnowledgeBase
from support_agent.rag_schemas import (
    ChunkOut,
    DocumentOut,
    DocumentPublication,
    KnowledgeCreate,
    KnowledgeDeletionPreview,
    KnowledgeOut,
    SearchHit,
    SearchInput,
)
from support_agent.search_text import HAN, latin_expression, query_expression, query_groups
from support_agent.services import chunk_versions, knowledge
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


@router.delete(
    "/knowledge-bases/{knowledge_base_id}",
    status_code=204,
    responses={
        200: {"model": KnowledgeDeletionPreview, "description": "Non-executable deletion preview"},
        409: {"description": "Historical-reference dependency review required"},
    },
)
def delete_base(
    knowledge_base_id: UUID,
    request: Request,
    db: Database,
    context: TenantAdmin,
    batch_size: int = Query(25, ge=1, le=100),
    preview: bool = False,
):
    progress = knowledge.delete_base(
        db, context, knowledge_base_id, request, batch_size=batch_size, preview=preview
    )
    if progress is not None:
        return JSONResponse(progress, status_code=200)
    return Response(status_code=204)


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


@router.delete(
    "/documents/{document_id}",
    status_code=204,
    responses={
        200: {"model": KnowledgeDeletionPreview, "description": "Non-executable deletion preview"},
        409: {"description": "Historical-reference dependency review required"},
    },
)
def delete_document(
    document_id: UUID,
    request: Request,
    db: Database,
    context: TenantAdmin,
    preview: bool = False,
):
    plan = knowledge.delete_document(db, context, document_id, request, preview=preview)
    if plan is not None:
        return JSONResponse(plan, status_code=200)
    return Response(status_code=204)


@router.post("/knowledge-bases/{knowledge_base_id}/search", response_model=list[SearchHit])
def search(
    knowledge_base_id: UUID,
    data: SearchInput,
    request: Request,
    db: Database,
    context: TenantContext,
):
    groups = query_groups(data.query)
    if (
        not any(len(group) == 1 and HAN.fullmatch(group[0]) for group in groups)
        and not query_expression(groups)
        and not latin_expression(groups)
    ):
        raise AppError(
            422,
            "unsupported_query",
            "No searchable terms. Use Chinese characters or an English keyword; "
            "this is not a statement that the knowledge base contains no answer.",
        )
    return request.app.state.retriever.search(
        db, context, [knowledge_base_id], data.query, data.limit
    )


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkOut])
def chunks(
    document_id: UUID,
    db: Database,
    context: TenantContext,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    generation: int | None = Query(None, ge=1),
    include_deleted: bool = False,
):
    from sqlalchemy import select

    from support_agent.errors import forbidden
    from support_agent.models import DocumentChunk

    document = get_owned(db, Document, context, document_id)
    if generation is not None or include_deleted:
        if context.role != "admin":
            raise forbidden()
    elif document.status != "ready":
        return []
    knowledge.active_base(db, context, document.knowledge_base_id)
    target_generation = generation if generation is not None else document.generation
    stmt = (
        select(DocumentChunk)
        .join(
            Document,
            (Document.tenant_id == DocumentChunk.tenant_id)
            & (Document.id == DocumentChunk.document_id),
        )
        .join(
            KnowledgeBase,
            (KnowledgeBase.tenant_id == Document.tenant_id)
            & (KnowledgeBase.id == Document.knowledge_base_id),
        )
        .where(
            DocumentChunk.tenant_id == context.tenant_id,
            DocumentChunk.document_id == document.id,
            DocumentChunk.generation == target_generation,
            DocumentChunk.is_current.is_(True),
            KnowledgeBase.status == "active",
        )
        .order_by(DocumentChunk.position)
        .limit(limit)
        .offset(offset)
    )
    if not include_deleted:
        stmt = stmt.where(DocumentChunk.is_deleted.is_(False))
    if generation is None and not include_deleted:
        stmt = stmt.where(
            Document.status == "ready",
            Document.generation == target_generation,
            Document.is_published.is_(True) if context.role != "admin" else True,
        )
    return db.scalars(stmt).all()


@router.get(
    "/documents/{document_id}/chunks/{chunk_id}/versions", response_model=list[ChunkVersion]
)
def chunk_history(
    document_id: UUID,
    chunk_id: UUID,
    db: Database,
    context: TenantAdmin,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return chunk_versions.versions(db, context, document_id, chunk_id, limit, offset)


@router.patch("/documents/{document_id}/chunks/{chunk_id}", response_model=ChunkVersion)
def edit_chunk(
    document_id: UUID,
    chunk_id: UUID,
    data: ChunkEdit,
    request: Request,
    db: Database,
    context: TenantAdmin,
):
    return chunk_versions.change(db, context, document_id, chunk_id, data, request, "edit")


@router.delete("/documents/{document_id}/chunks/{chunk_id}", response_model=ChunkVersion)
def delete_chunk(
    document_id: UUID,
    chunk_id: UUID,
    data: ChunkMutation,
    request: Request,
    db: Database,
    context: TenantAdmin,
):
    return chunk_versions.change(db, context, document_id, chunk_id, data, request, "delete")


@router.post("/documents/{document_id}/chunks/{chunk_id}/restore", response_model=ChunkVersion)
def restore_chunk(
    document_id: UUID,
    chunk_id: UUID,
    data: ChunkRestore,
    request: Request,
    db: Database,
    context: TenantAdmin,
):
    return chunk_versions.change(db, context, document_id, chunk_id, data, request, "restore")


@router.post("/documents/{document_id}/publication", response_model=DocumentOut)
def document_publication(
    document_id: UUID,
    data: DocumentPublication,
    request: Request,
    db: Database,
    context: TenantAdmin,
):
    return knowledge.publish_document(db, context, document_id, data, request)
