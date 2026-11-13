from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select

from support_agent.dependencies import locked_staff_context
from support_agent.errors import AppError
from support_agent.ingestion import MIMES, process_document, validate_upload
from support_agent.models import Document, DocumentChunk, KnowledgeBase
from support_agent.retention import KNOWLEDGE_REFERENCE_DEPENDENCIES
from support_agent.services.audit import record
from support_agent.services.resources import get_owned


def active_base(db, context, kid, *, lock=False):
    base = get_owned(db, KnowledgeBase, context, kid, lock=lock)
    if base.status != "active":
        raise AppError(409, "knowledge_base_deleting", "Knowledge base deletion is pending")
    return base


def create(db, context, data, request):
    context = locked_staff_context(db, context, request, admin=True)
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
    context = locked_staff_context(db, context, request, admin=True)
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
    context = locked_staff_context(db, context, request, admin=True)
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
    if doc is not None and doc.media_type != media:
        raise AppError(
            409,
            "document_format_conflict",
            "Identical content is already registered with a different format. "
            "Use the existing document; changing its format requires a separately reviewed erasure; "
            "existing content and references were not changed.",
        )
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
    return process(db, context, document_id, request, content=content), created


def process(db, context, document_id, request, *, content=None):
    context = locked_staff_context(db, context, request, admin=True)
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
            # Published objects are immutable. A mismatch requires investigation;
            # the storage backend reconciles only its own interrupted pending write.
            storage.write(context.tenant_id, document_id, content)
        raw = storage.read(context.tenant_id, document_id)
        if sha256(raw).hexdigest() != doc.sha256:
            raise OSError("Document digest mismatch")
    except OSError:
        doc.status = "failed"
        doc.error_category = "storage_unavailable"
        doc.chunk_count = 0
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
    suffix = next(ext for ext, mime in MIMES.items() if mime == doc.media_type)
    db.commit()
    chunks, error = process_document(raw, suffix)
    context = locked_staff_context(db, context, request, admin=True)
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
        doc.is_published = False
        db.add_all(
            DocumentChunk(
                id=chunk_id,
                root_chunk_id=chunk_id,
                tenant_id=context.tenant_id,
                document_id=document_id,
                position=i,
                generation=doc.generation,
                **chunk,
            )
            for i, chunk in enumerate(chunks)
            for chunk_id in [uuid4()]
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
    from support_agent.services.vector_index import changed

    changed(db, context.tenant_id, doc.knowledge_base_id)
    return doc


def _deletion_preview(db, context, documents, *, remaining, batch_size, status):
    # No confirmation is issued for an incomplete dependency graph. These are
    # known candidate objects, not an executable erasure plan or a zero-link claim.
    ids = [doc.id for doc in documents]
    chunks = (
        db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.tenant_id == context.tenant_id,
                DocumentChunk.document_id.in_(ids),
            )
        )
        if ids
        else 0
    )
    return {
        "remaining": remaining,
        "batch_size": batch_size,
        "status": status,
        "documents": [
            {
                "id": str(doc.id),
                "filename": doc.filename,
                "status": doc.status,
                "generation": doc.generation,
                "updated_at": doc.updated_at.isoformat(),
            }
            for doc in documents
        ],
        "chunk_versions": chunks,
        "executable": False,
        "blocked_reason": "knowledge_reference_review_required",
        "confirmation": None,
        "unknown_dependencies": {name: None for name in KNOWLEDGE_REFERENCE_DEPENDENCIES},
        "effects": {
            "deleted": [],
            "retained": [
                "documents",
                "document_chunks",
                "private_files",
                "knowledge_bases",
                "agent_knowledge_bases",
            ],
            "requested": ["documents", "all_generations_and_revisions", "private_files"],
            "unknown": ["historical_answer_and_tool_visibility", "feedback_source_links"],
        },
    }


def _block_erasure():
    raise AppError(
        409,
        "knowledge_reference_review_required",
        "Knowledge erasure is blocked: historical JSON references are not fully "
        "enumerated or bound to confirmation. No data or files were deleted. "
        "Use preview=true to inspect the known scope; chunk logical deletion remains available.",
    )


def delete_document(db, context, document_id, request, *, preview=False):
    doc = db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == context.tenant_id)
    )
    if doc is None:
        return None
    if preview:
        return _deletion_preview(db, context, [doc], remaining=1, batch_size=1, status=doc.status)
    _block_erasure()


def delete_base(db, context, kid, request, *, batch_size=25, preview=False):
    base = db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kid, KnowledgeBase.tenant_id == context.tenant_id
        )
    )
    if base is None:
        return None
    if not preview:
        _block_erasure()
    docs = list(
        db.scalars(
            select(Document)
            .where(Document.tenant_id == context.tenant_id, Document.knowledge_base_id == kid)
            .order_by(Document.id)
            .limit(batch_size)
        )
    )
    remaining = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.tenant_id == context.tenant_id, Document.knowledge_base_id == kid)
    )
    return _deletion_preview(
        db, context, docs, remaining=remaining, batch_size=batch_size, status=base.status
    )


def publish_document(db, context, document_id, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    initial = get_owned(db, Document, context, document_id)
    active_base(db, context, initial.knowledge_base_id, lock=True)
    doc = get_owned(db, Document, context, document_id, lock=True)
    if (
        (data.published and doc.status != "ready")
        or doc.generation != data.expected_generation
        or doc.updated_at != data.expected_updated_at
    ):
        raise AppError(
            409, "document_changed", "Document version changed; refresh before publishing"
        )
    if doc.is_published != data.published:
        doc.is_published = data.published
        doc.updated_at = datetime.now(UTC)
        record(
            db,
            request,
            "document.publish" if data.published else "document.withdraw",
            "document",
            doc.id,
            tenant_id=context.tenant_id,
            details={"generation": doc.generation},
        )
        db.flush()
    from support_agent.services.vector_index import changed

    changed(db, context.tenant_id, doc.knowledge_base_id)
    return doc
