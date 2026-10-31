from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import delete, func, select

from support_agent.dependencies import resume_context
from support_agent.errors import AppError
from support_agent.ingestion import MIMES, process_document, validate_upload
from support_agent.models import Document, DocumentChunk, KnowledgeBase
from support_agent.services.audit import record
from support_agent.services.resources import get_owned


def active_base(db, context, kid, *, lock=False):
    base = get_owned(db, KnowledgeBase, context, kid, lock=lock)
    if base.status != "active":
        raise AppError(409, "knowledge_base_deleting", "Knowledge base deletion is pending")
    return base


def create(db, context, data, request):
    base = KnowledgeBase(
        **data.model_dump(), tenant_id=context.tenant_id, created_by=context.user_id
    )
    db.add(base)
    db.flush()
    record(
        db, request, "knowledge_base.create", "knowledge_base", base.id, tenant_id=context.tenant_id
    )
    return base


def update(db, context, kid, data, request):
    base = active_base(db, context, kid, lock=True)
    for key, value in data.model_dump().items():
        setattr(base, key, value)
    record(
        db, request, "knowledge_base.update", "knowledge_base", base.id, tenant_id=context.tenant_id
    )
    db.flush()
    return base


def upload(db, context, kid, filename, content, request):
    suffix, media = validate_upload(filename, content)
    active_base(db, context, kid, lock=True)
    digest = sha256(content).hexdigest()
    doc = db.scalar(
        select(Document).where(
            Document.tenant_id == context.tenant_id,
            Document.knowledge_base_id == kid,
            Document.sha256 == digest,
        )
    )
    created = doc is None
    if doc is None:
        doc = Document(
            tenant_id=context.tenant_id,
            knowledge_base_id=kid,
            created_by=context.user_id,
            filename=filename,
            media_type=media,
            size_bytes=len(content),
            sha256=digest,
        )
        db.add(doc)
        db.flush()
        record(db, request, "document.register", "document", doc.id, tenant_id=context.tenant_id)
    elif doc.status in ("ready", "processing"):
        return doc, False
    elif doc.status == "deleting":
        raise AppError(409, "document_deleting", "Document deletion is pending")
    document_id = doc.id
    # Persist the path-owning row before any file write. A crash leaves a recoverable row, not an orphan.
    db.commit()
    context = resume_context(db, context, request, admin=True)
    return process(db, context, document_id, request, content=content), created


def process(db, context, document_id, request, *, content=None):
    initial = get_owned(db, Document, context, document_id)
    active_base(db, context, initial.knowledge_base_id, lock=True)
    doc = get_owned(db, Document, context, document_id, lock=True)
    now = datetime.now(UTC)
    if doc.status == "deleting":
        raise AppError(409, "document_deleting", "Document deletion is pending")
    if doc.status == "processing" and doc.lease_expires_at and doc.lease_expires_at > now:
        raise AppError(409, "document_processing", "Document processing is already active")
    storage = request.app.state.storage
    try:
        if content is not None:
            # Repair only this document's partial file left by an interrupted initial write.
            if (
                storage.exists(context.tenant_id, document_id)
                and storage.read(context.tenant_id, document_id) != content
            ):
                storage.delete(context.tenant_id, document_id)
            storage.write(context.tenant_id, document_id, content)
        raw = storage.read(context.tenant_id, document_id)
        if sha256(raw).hexdigest() != doc.sha256:
            raise OSError("Document digest mismatch")
    except OSError:
        doc.status = "failed"
        doc.error_category = "storage_unavailable"
        doc.chunk_count = 0
        db.execute(
            delete(DocumentChunk).where(
                DocumentChunk.tenant_id == context.tenant_id,
                DocumentChunk.document_id == document_id,
            )
        )
        record(
            db,
            request,
            "document.process",
            "document",
            document_id,
            tenant_id=context.tenant_id,
            outcome="failure",
            reason="storage_unavailable",
        )
        db.flush()
        return doc
    token = uuid4()
    doc.processing_token = token
    doc.lease_expires_at = datetime.now(UTC) + timedelta(seconds=30)
    doc.status = "processing"
    doc.error_category = None
    doc.chunk_count = 0
    db.execute(
        delete(DocumentChunk).where(
            DocumentChunk.tenant_id == context.tenant_id, DocumentChunk.document_id == document_id
        )
    )
    suffix = next(ext for ext, mime in MIMES.items() if mime == doc.media_type)
    db.commit()
    chunks, error = process_document(raw, suffix)
    context = resume_context(db, context, request, admin=True)
    current = get_owned(db, Document, context, document_id)
    active_base(db, context, current.knowledge_base_id, lock=True)
    doc = get_owned(db, Document, context, document_id, lock=True)
    if doc.status != "processing" or doc.processing_token != token:
        raise AppError(409, "document_changed", "Document processing state changed")
    if error:
        doc.status = "failed"
        doc.error_category = error
    else:
        doc.generation += 1
        db.add_all(
            DocumentChunk(
                tenant_id=context.tenant_id,
                document_id=document_id,
                position=i,
                generation=doc.generation,
                **chunk,
            )
            for i, chunk in enumerate(chunks)
        )
        doc.chunk_count = len(chunks)
        doc.status = "ready"
    doc.processing_token = None
    doc.lease_expires_at = None
    record(
        db,
        request,
        "document.process",
        "document",
        document_id,
        tenant_id=context.tenant_id,
        outcome="failure" if error else "success",
        reason=error,
    )
    db.flush()
    return doc


def delete_document(db, context, document_id, request):
    doc = db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == context.tenant_id)
    )
    if doc is None:
        return
    base = db.scalar(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.id == doc.knowledge_base_id, KnowledgeBase.tenant_id == context.tenant_id
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if base is None:
        return
    doc = db.scalar(
        select(Document)
        .where(Document.id == document_id, Document.tenant_id == context.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if doc is None:
        return
    doc.status = "deleting"
    doc.processing_token = None
    doc.lease_expires_at = None
    doc.chunk_count = 0
    db.execute(
        delete(DocumentChunk).where(
            DocumentChunk.tenant_id == context.tenant_id, DocumentChunk.document_id == document_id
        )
    )
    record(
        db,
        request,
        "document.delete_requested",
        "document",
        document_id,
        tenant_id=context.tenant_id,
    )
    db.commit()
    resume_context(db, context, request, admin=True)
    # Serialize concurrent retries so a late unlink cannot delete a newly uploaded file.
    doc = db.scalar(
        select(Document)
        .where(Document.id == document_id, Document.tenant_id == context.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if doc is None:
        return
    try:
        request.app.state.storage.delete(context.tenant_id, document_id)
    except OSError:
        raise AppError(
            503,
            "storage_cleanup_pending",
            "Deletion is hidden from retrieval; retry DELETE to finish cleanup",
        ) from None
    db.delete(doc)
    record(db, request, "document.delete", "document", document_id, tenant_id=context.tenant_id)
    db.flush()


def delete_base(db, context, kid, request, *, batch_size=25, preview=False):
    base = db.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.id == kid, KnowledgeBase.tenant_id == context.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if base is None:
        return None

    def remaining():
        return db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.tenant_id == context.tenant_id, Document.knowledge_base_id == kid)
        )

    if preview:
        docs = db.scalars(
            select(Document)
            .where(Document.tenant_id == context.tenant_id, Document.knowledge_base_id == kid)
            .order_by(Document.id)
            .limit(batch_size)
        ).all()
        return {
            "remaining": remaining(),
            "batch_size": batch_size,
            "status": base.status,
            "documents": [
                {"id": str(doc.id), "filename": doc.filename, "status": doc.status} for doc in docs
            ],
        }
    # The base tombstone hides every chunk immediately, without loading all documents.
    base.status = "deleting"
    record(
        db,
        request,
        "knowledge_base.delete_requested",
        "knowledge_base",
        kid,
        tenant_id=context.tenant_id,
    )
    db.commit()
    context = resume_context(db, context, request, admin=True)
    base = db.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.id == kid, KnowledgeBase.tenant_id == context.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if base is None:
        return None
    docs = list(
        db.scalars(
            select(Document)
            .where(Document.tenant_id == context.tenant_id, Document.knowledge_base_id == kid)
            .order_by(Document.id)
            .limit(batch_size)
            .with_for_update()
        )
    )
    ids = [doc.id for doc in docs]
    for doc in docs:
        doc.status = "deleting"
        doc.processing_token = None
        doc.lease_expires_at = None
        doc.chunk_count = 0
        record(
            db,
            request,
            "document.delete_requested",
            "document",
            doc.id,
            tenant_id=context.tenant_id,
        )
    if ids:
        db.execute(
            delete(DocumentChunk).where(
                DocumentChunk.tenant_id == context.tenant_id, DocumentChunk.document_id.in_(ids)
            )
        )
    db.commit()
    context = resume_context(db, context, request, admin=True)
    # Stable base -> document lock order serializes retries and prevents a late unlink.
    base = db.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.id == kid, KnowledgeBase.tenant_id == context.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if base is None:
        return None
    docs = list(
        db.scalars(
            select(Document)
            .where(Document.tenant_id == context.tenant_id, Document.id.in_(ids))
            .order_by(Document.id)
            .with_for_update()
        )
    )
    for doc in docs:
        try:
            request.app.state.storage.delete(context.tenant_id, doc.id)
        except OSError:
            raise AppError(
                503,
                "storage_cleanup_pending",
                "Deletion is hidden; retry DELETE to resume the bounded batch",
            ) from None
        db.delete(doc)
        record(db, request, "document.delete", "document", doc.id, tenant_id=context.tenant_id)
    db.flush()
    count = remaining()
    if count:
        record(
            db,
            request,
            "knowledge_base.delete_progress",
            "knowledge_base",
            kid,
            tenant_id=context.tenant_id,
            details={"deleted": len(docs), "remaining": count},
        )
        return {"status": "deleting", "deleted": len(docs), "remaining": count}
    db.delete(base)
    record(db, request, "knowledge_base.delete", "knowledge_base", kid, tenant_id=context.tenant_id)
    db.flush()
    return None
