"""Versioned pgvector indexing; withdrawn, superseded and unauthorized rows never participate."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import exists, func, or_, select

from support_agent.dependencies import locked_staff_context, resume_context
from support_agent.errors import AppError
from support_agent.models import (
    AgentConfig,
    ChunkEmbedding,
    Document,
    DocumentChunk,
    KnowledgeIndex,
    ModelCall,
)
from support_agent.services import background, model_runtime, workspace
from support_agent.services.audit import record
from support_agent.services.knowledge import active_base
from support_agent.services.resources import get_owned


def eligible(tid, kid):
    return (
        select(DocumentChunk)
        .join(
            Document,
            (Document.tenant_id == DocumentChunk.tenant_id)
            & (Document.id == DocumentChunk.document_id),
        )
        .where(
            DocumentChunk.tenant_id == tid,
            Document.tenant_id == tid,
            Document.knowledge_base_id == kid,
            Document.status == "ready",
            Document.is_published.is_(True),
            DocumentChunk.generation == Document.generation,
            DocumentChunk.is_current.is_(True),
            DocumentChunk.is_deleted.is_(False),
        )
    )


def profile(db, context, kid, *, lock=False):
    active_base(db, context, kid)
    stmt = (
        select(KnowledgeIndex)
        .where(
            KnowledgeIndex.tenant_id == context.tenant_id, KnowledgeIndex.knowledge_base_id == kid
        )
        .execution_options(populate_existing=True)
    )
    return db.scalar(stmt.with_for_update() if lock else stmt)


def save(db, context, kid, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    config = get_owned(db, AgentConfig, context, data.agent_config_id, lock=True)
    active_base(db, context, kid, lock=True)
    if (
        not config.enabled
        or config.provider != "openai_compatible"
        or not config.base_url
        or kid not in workspace.knowledge_ids(db, context, config.id)
    ):
        raise AppError(
            409,
            "embedding_configuration_unavailable",
            "Select an enabled real Agent authorized for this knowledge base",
        )
    row = profile(db, context, kid, lock=True)
    if data.expected_version != (row.version if row else 0):
        raise AppError(409, "index_version_conflict", "Refresh the index configuration")
    if row and row.state == "RUNNING" and row.lease_until > datetime.now(UTC):
        raise AppError(409, "index_busy", "Wait for the active indexing lease")
    if row is None:
        row = KnowledgeIndex(tenant_id=context.tenant_id, knowledge_base_id=kid, version=1)
        db.add(row)
    else:
        row.version += 1
    row.agent_config_id, row.model, row.endpoint = (
        config.id,
        data.model,
        config.base_url.rstrip("/"),
    )
    row.requested_by, row.auth_session_id = context.user_id, request.state.session_id
    row.enabled, row.rerank = data.enabled, data.rerank
    row.state, row.error_category = ("QUEUED" if data.enabled else "DISABLED"), None
    row.lease_token, row.lease_until = None, None
    record(
        db,
        request,
        "knowledge_index.configure",
        "knowledge_base",
        kid,
        tenant_id=context.tenant_id,
        details={"version": row.version, "enabled": row.enabled, "dimensions": 1536},
    )
    db.flush()
    return row


def queue(db, context, kid, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    row = profile(db, context, kid, lock=True)
    if row is None or not row.enabled or row.version != data.expected_version:
        raise AppError(409, "index_version_conflict", "An enabled current index is required")
    if row.state == "RUNNING" and row.lease_until > datetime.now(UTC):
        raise AppError(409, "index_busy", "An indexing batch is already active")
    if data.rebuild:
        row.version += 1  # Old model-space vectors immediately stop participating.
    row.state, row.error_category = "QUEUED", None
    row.lease_token, row.lease_until = None, None
    row.requested_by, row.auth_session_id = context.user_id, request.state.session_id
    record(
        db,
        request,
        "knowledge_index.queue",
        "knowledge_base",
        kid,
        tenant_id=context.tenant_id,
        details={"version": row.version, "rebuild": data.rebuild},
    )
    return row


def changed(db, tid, kid):
    # Called in the same knowledge-write transaction. No model work or hidden retries.
    row = db.scalar(
        select(KnowledgeIndex)
        .where(KnowledgeIndex.tenant_id == tid, KnowledgeIndex.knowledge_base_id == kid)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row and row.enabled and row.state != "RUNNING":
        row.state = "QUEUED"


def status(db, context, kid):
    row = profile(db, context, kid)
    from support_agent.product_schemas import IndexOut

    total = db.scalar(select(func.count()).select_from(eligible(context.tenant_id, kid).subquery()))
    ready = 0
    if row:
        ready = db.scalar(
            select(func.count()).select_from(
                eligible(context.tenant_id, kid)
                .where(
                    exists(
                        select(ChunkEmbedding.id).where(
                            ChunkEmbedding.tenant_id == context.tenant_id,
                            ChunkEmbedding.index_id == row.id,
                            ChunkEmbedding.index_version == row.version,
                            ChunkEmbedding.chunk_id == DocumentChunk.id,
                        )
                    )
                )
                .subquery()
            )
        )
    return {
        "configuration": IndexOut.model_validate(row).model_dump(mode="json") if row else None,
        "dimensions": 1536,
        "eligible_chunks": total,
        "indexed_chunks": ready,
        "missing_chunks": total - ready,
        "physical_erasure": "BLOCKED",
    }


def ensure_dispatch(db, context, call, request, config, model):
    # Called after source locks, before reservations: Agent -> base -> document -> index.
    snapshot = (call.result or {}).get("embedding_index")
    if not isinstance(snapshot, dict):
        raise AppError(409, "index_provenance_unknown", "Index dispatch provenance is unknown")
    try:
        iid, token = UUID(snapshot["id"]), UUID(snapshot["lease_token"])
    except (KeyError, ValueError, TypeError, AttributeError):
        raise AppError(
            409, "index_provenance_unknown", "Index dispatch provenance is unknown"
        ) from None
    row = get_owned(db, KnowledgeIndex, context, iid, lock=True)
    # Gates are already held by the gateway; recheck role/session after lock waits.
    context = resume_context(db, context, request, admin=True)
    if (
        not row.enabled
        or row.state != "RUNNING"
        or row.version != snapshot.get("version")
        or row.lease_token != token
        or row.lease_until is None
        or row.lease_until <= datetime.now(UTC)
        or row.agent_config_id != call.agent_config_id
        or row.requested_by != context.user_id
        or row.auth_session_id != request.state.session_id
        or row.model != model
        or row.endpoint != (config.base_url or "").rstrip("/")
    ):
        raise AppError(409, "index_configuration_changed", "Index dispatch is no longer authorized")
    return row.lease_until


def process_one(db, tid, state):
    row = db.scalar(
        select(KnowledgeIndex)
        .where(
            KnowledgeIndex.tenant_id == tid,
            KnowledgeIndex.enabled.is_(True),
            or_(
                KnowledgeIndex.state == "QUEUED",
                (KnowledgeIndex.state == "RUNNING")
                & (KnowledgeIndex.lease_until <= datetime.now(UTC)),
            ),
        )
        .order_by(KnowledgeIndex.updated_at, KnowledgeIndex.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not row:
        return False
    if row.state == "RUNNING":
        row.state, row.error_category = "FAILED", "index_interrupted_unknown"
        row.lease_token, row.lease_until = None, None
        db.commit()
        return True  # Explicit retry only; never blindly repeat a paid unknown call.
    token, version, iid = uuid4(), row.version, row.id
    row.state, row.lease_token, row.lease_until = (
        "RUNNING",
        token,
        datetime.now(UTC) + timedelta(seconds=180),
    )
    request = background.request_for(state, row)
    db.commit()
    from support_agent.db import set_tenant

    set_tenant(db, tid)
    row = db.get(KnowledgeIndex, iid)
    call_id = None
    try:
        context = background.identity(db, row, request, admin=True)
        config = get_owned(db, AgentConfig, context, row.agent_config_id, lock=True)
        # Knowledge writers take this base lock before the index lock too. Keep
        # the final missing-chunk check and READY transition in the same snapshot.
        active_base(db, context, row.knowledge_base_id, lock=True)
        row = get_owned(db, KnowledgeIndex, context, iid, lock=True)
        if (
            row.state != "RUNNING"
            or row.lease_token != token
            or row.version != version
            or not row.enabled
            or row.lease_until <= datetime.now(UTC)
        ):
            raise AppError(409, "index_configuration_changed", "Index lease is no longer active")
        if config.base_url.rstrip(
            "/"
        ) != row.endpoint or row.knowledge_base_id not in workspace.knowledge_ids(
            db, context, config.id
        ):
            raise AppError(409, "index_configuration_changed", "Index endpoint or grant changed")
        chunk = db.scalar(
            eligible(tid, row.knowledge_base_id)
            .where(
                ~exists(
                    select(ChunkEmbedding.id).where(
                        ChunkEmbedding.tenant_id == tid,
                        ChunkEmbedding.index_id == iid,
                        ChunkEmbedding.index_version == version,
                        ChunkEmbedding.chunk_id == DocumentChunk.id,
                    )
                )
            )
            .order_by(DocumentChunk.id)
            .limit(1)
        )
        if chunk is None:
            row.state, row.lease_until, row.lease_token = "READY", None, None
            db.commit()
            return True
        cid, digest, content = (
            chunk.id,
            hashlib.sha256(chunk.content.encode()).hexdigest(),
            chunk.content,
        )
        from support_agent.services.memory import sensitive

        if sensitive(content):
            raise AppError(409, "embedding_sensitive_content", "Remove credentials before indexing")
        embedding_model = row.model
        call = background.model_call(db, context, config.id, request, kind="embedding")
        call.result = call.result | {
            "embedding_index": {"id": str(iid), "version": version, "lease_token": str(token)}
        }
        call_id = call.id
        db.commit()
        result = model_runtime.complete(
            db,
            context,
            call_id,
            request,
            messages=[],
            embedding_input=content,
            embedding_model=embedding_model,
            # The source was read before commit. Revalidate its current published
            # version inside the gateway transaction before dispatching its text.
            knowledge_sources=(cid,),
            purpose="index_embedding",
            prompt_id=None,
            timeout=120,
        )
        context = locked_staff_context(db, context, request, admin=True)
        config = get_owned(db, AgentConfig, context, row.agent_config_id, lock=True)
        call = get_owned(db, ModelCall, context, call_id)
        if (
            not config.enabled
            or config.version != call.config_version
            or row.knowledge_base_id not in workspace.knowledge_ids(db, context, config.id)
        ):
            raise AppError(
                409, "index_configuration_changed", "Index authorization changed before publication"
            )
        # Keep Agent -> base -> document -> index order, including grant changes.
        current = state.retriever.current_chunks(db, context, [cid], lock=True, current_only=True)
        row = db.scalar(
            select(KnowledgeIndex)
            .where(KnowledgeIndex.tenant_id == tid, KnowledgeIndex.id == iid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            row.version != version
            or row.lease_token != token
            or not row.enabled
            or row.state != "RUNNING"
            or row.lease_until <= datetime.now(UTC)
        ):
            raise AppError(
                409, "index_configuration_changed", "Index version changed during embedding"
            )
        if (
            cid in current
            and hashlib.sha256(current[cid][0].content.encode()).hexdigest() == digest
        ):
            embedding = db.scalar(
                select(ChunkEmbedding)
                .where(
                    ChunkEmbedding.tenant_id == tid,
                    ChunkEmbedding.index_id == iid,
                    ChunkEmbedding.chunk_id == cid,
                )
                .with_for_update()
            )
            if embedding is None:
                embedding = ChunkEmbedding(tenant_id=tid, index_id=iid, chunk_id=cid)
                db.add(embedding)
            (
                embedding.embedding,
                embedding.content_digest,
                embedding.index_version,
                embedding.model_call_id,
            ) = list(result.embedding), digest, version, call_id
        background.finish(db, context, get_owned(db, ModelCall, context, call_id), request)
        row.state, row.error_category, row.lease_until = "QUEUED", None, None
        row.lease_token = None
        record(
            db,
            request,
            "knowledge_index.chunk",
            "knowledge_base",
            row.knowledge_base_id,
            tenant_id=tid,
            details={"chunk_id": str(cid), "version": version, "call_id": str(call_id)},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        set_tenant(db, tid)
        row = db.scalar(
            select(KnowledgeIndex)
            .where(KnowledgeIndex.tenant_id == tid, KnowledgeIndex.id == iid)
            .with_for_update()
        )
        code = getattr(exc, "code", None) or getattr(exc, "category", None) or "index_failed"
        if row.lease_token == token:
            row.state, row.error_category, row.lease_until = "FAILED", code, None
            row.lease_token = None
        if call_id:
            background.finish(db, context, db.get(ModelCall, call_id), request, error=code)
        record(
            db,
            request,
            "knowledge_index.failed",
            "knowledge_base",
            row.knowledge_base_id,
            tenant_id=tid,
            outcome="failure",
            reason=code,
        )
        db.commit()
    return True
