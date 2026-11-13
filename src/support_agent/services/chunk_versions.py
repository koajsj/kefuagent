from datetime import UTC, datetime

from sqlalchemy import select

from support_agent.dependencies import locked_staff_context
from support_agent.errors import AppError, forbidden, missing
from support_agent.models import Document, DocumentChunk
from support_agent.services.audit import record
from support_agent.services.knowledge import active_base
from support_agent.services.resources import get_owned


def _document(db, context, document_id, *, lock=False):
    doc = get_owned(db, Document, context, document_id)
    active_base(db, context, doc.knowledge_base_id, lock=lock)
    return get_owned(db, Document, context, document_id, lock=lock)


def _chunk(db, context, doc, chunk_id):
    chunk = db.scalar(
        select(DocumentChunk).where(
            DocumentChunk.tenant_id == context.tenant_id,
            DocumentChunk.document_id == doc.id,
            DocumentChunk.id == chunk_id,
        )
    )
    if chunk is None:
        raise missing()
    return chunk


def versions(db, context, document_id, chunk_id, limit, offset):
    doc = _document(db, context, document_id)
    chunk = _chunk(db, context, doc, chunk_id)
    return db.scalars(
        select(DocumentChunk)
        .where(
            DocumentChunk.tenant_id == context.tenant_id,
            DocumentChunk.document_id == doc.id,
            DocumentChunk.generation == chunk.generation,
            DocumentChunk.root_chunk_id == chunk.root_chunk_id,
        )
        .order_by(DocumentChunk.revision.desc())
        .limit(limit)
        .offset(offset)
    ).all()


def change(db, context, document_id, chunk_id, data, request, action):
    context = locked_staff_context(db, context, request)
    if context.role != "admin":
        raise forbidden()
    doc = _document(db, context, document_id, lock=True)
    chunk = _chunk(db, context, doc, chunk_id)
    if doc.status != "ready" or chunk.generation != doc.generation:
        raise AppError(409, "document_changed", "Document generation is no longer current")
    current = db.scalar(
        select(DocumentChunk).where(
            DocumentChunk.tenant_id == context.tenant_id,
            DocumentChunk.document_id == doc.id,
            DocumentChunk.generation == doc.generation,
            DocumentChunk.root_chunk_id == chunk.root_chunk_id,
            DocumentChunk.is_current.is_(True),
        )
    )
    if current is None or current.id != data.expected_current_id:
        raise AppError(409, "chunk_changed", "Chunk has changed; reload its current version")
    if action == "edit":
        if current.is_deleted:
            raise AppError(409, "chunk_deleted", "Restore the chunk before editing")
        source = current
        content = data.content
        deleted = False
    elif action == "delete":
        if current.is_deleted:
            raise AppError(409, "chunk_deleted", "Chunk is already deleted")
        source, content, deleted = current, current.content, True
    else:
        source = _chunk(db, context, doc, data.source_version_id)
        if (
            source.root_chunk_id != current.root_chunk_id
            or source.generation != current.generation
            or source.is_deleted
        ):
            raise AppError(
                422, "invalid_chunk_version", "Select a non-deleted version in this lineage"
            )
        content, deleted = source.content, False
    current.is_current = False
    db.flush()
    result = DocumentChunk(
        tenant_id=context.tenant_id,
        document_id=doc.id,
        root_chunk_id=current.root_chunk_id,
        position=current.position,
        generation=current.generation,
        revision=current.revision + 1,
        is_current=True,
        is_deleted=deleted,
        content=content,
        page=source.page,
        section=source.section,
        revised_by=context.user_id,
        revision_reason=data.reason,
    )
    db.add(result)
    doc.is_published = False
    doc.updated_at = datetime.now(UTC)
    if current.is_deleted != deleted:
        doc.chunk_count += -1 if deleted else 1
    db.flush()
    record(
        db,
        request,
        "chunk." + action,
        "document_chunk",
        result.id,
        tenant_id=context.tenant_id,
        details={
            "document_id": str(doc.id),
            "root_chunk_id": str(current.root_chunk_id),
            "revision": result.revision,
            "source_version_id": str(source.id),
        },
    )
    from support_agent.services.vector_index import changed

    changed(db, context.tenant_id, doc.knowledge_base_id)
    return result
