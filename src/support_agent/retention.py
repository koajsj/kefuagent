"""Explicit, bounded tenant retention; disabled policies never select data."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select

from support_agent.models import (
    AuditEvent,
    Collaboration,
    Conversation,
    ConversationSummary,
    Document,
    Message,
    ModelCall,
    ToolExecution,
    VisitorFeedback,
    VisitorSession,
)


def _select(db, tenant_id, policy, *, lock=False):
    from support_agent.maintenance import scope

    scope(db, tenant_id, "retention")
    now = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    for field in ("conversations_days", "visitors_days", "calls_days", "audit_days"):
        value = getattr(policy, field)
        if value is not None and not (30 if field == "audit_days" else 2) <= value <= 36500:
            raise ValueError("Retention must preserve quota windows (>=2 days), audit >=30 days")
    if not 1 <= policy.batch_size <= 100:
        raise ValueError("Batch size must be 1..100")

    def query(model, *criteria):
        stmt = (
            select(model)
            .where(model.tenant_id == tenant_id, *criteria)
            .order_by(model.id)
            .limit(policy.batch_size)
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return db.scalars(stmt).all()

    active = (
        select(ModelCall.id)
        .where(
            ModelCall.tenant_id == tenant_id,
            ModelCall.conversation_id == Conversation.id,
            ModelCall.status == "running",
        )
        .exists()
    )

    def recent_activity(cutoff):
        return or_(
            select(Message.id)
            .where(
                Message.tenant_id == tenant_id,
                Message.conversation_id == Conversation.id,
                Message.created_at >= cutoff,
            )
            .exists(),
            select(ModelCall.id)
            .where(
                ModelCall.tenant_id == tenant_id,
                ModelCall.conversation_id == Conversation.id,
                ModelCall.created_at >= min(cutoff, now - timedelta(days=2)),
            )
            .exists(),
        )

    filters = []
    if policy.conversations_days:
        cutoff = now - timedelta(days=policy.conversations_days)
        filters.append(
            (Conversation.status == "closed")
            & (Conversation.updated_at < cutoff)
            & ~recent_activity(cutoff)
        )
    if policy.visitors_days:
        old_visitor = (
            select(VisitorSession.id)
            .where(
                VisitorSession.tenant_id == tenant_id,
                VisitorSession.conversation_id == Conversation.id,
                VisitorSession.expires_at < now - timedelta(days=policy.visitors_days),
            )
            .exists()
        )
        cutoff = now - timedelta(days=policy.visitors_days)
        filters.append(old_visitor & (Conversation.updated_at < cutoff) & ~recent_activity(cutoff))
    conversations = query(Conversation, or_(*filters), ~active) if filters else []
    calls = (
        query(
            ModelCall,
            ModelCall.conversation_id.is_(None),
            ModelCall.status != "running",
            ModelCall.result["retention_redacted"].as_boolean().is_distinct_from(True),
            ModelCall.created_at < now - timedelta(days=policy.calls_days),
        )
        if policy.calls_days
        else []
    )
    audits = (
        query(AuditEvent, AuditEvent.created_at < now - timedelta(days=policy.audit_days))
        if policy.audit_days
        else []
    )
    # Only finish explicitly requested document deletion, never age-delete ready knowledge.
    documents = (
        query(Document, Document.status == "deleting")
        if getattr(policy, "documents", False)
        else []
    )
    return {
        "conversations": conversations,
        "calls": calls,
        "audits": audits,
        "documents": documents,
    }


def retention_plan(db, tenant_id, policy, *, lock=False):
    from support_agent.maintenance import confirmation

    selected = _select(db, tenant_id, policy, lock=lock)
    ids = [row.id for row in selected["conversations"]]
    counts = {name: len(rows) for name, rows in selected.items()}
    from support_agent.models import DocumentChunk

    counts["document_chunks"] = (
        db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id.in_([row.id for row in selected["documents"]]),
            )
        )
        if selected["documents"]
        else 0
    )
    for name, model in (
        ("messages", Message),
        ("collaboration", Collaboration),
        ("summaries", ConversationSummary),
        ("feedback", VisitorFeedback),
        ("tool_executions", ToolExecution),
        ("visitor_sessions", VisitorSession),
        ("conversation_calls", ModelCall),
    ):
        counts[name] = (
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.tenant_id == tenant_id, model.conversation_id.in_(ids))
            )
            if ids
            else 0
        )
    fingerprint = {
        name: [(str(row.id), str(getattr(row, "updated_at", row.created_at))) for row in rows]
        for name, rows in selected.items()
    }
    config = {
        key: getattr(policy, key)
        for key in ("conversations_days", "visitors_days", "calls_days", "audit_days", "batch_size")
    }
    config["documents"] = getattr(policy, "documents", False)
    return {
        "tenant_id": str(tenant_id),
        "policy": config,
        "counts": counts,
        "bounded": True,
        "executable": sum(counts.values()) <= 10000,
        "confirmation": confirmation([str(tenant_id), config, fingerprint, counts]),
    }


def apply_retention(db, tenant_id, policy, confirm, storage):
    from support_agent.maintenance import audit, scope

    scope(db, tenant_id, "retention")
    receipt = db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action == "retention.execute",
            AuditEvent.details["confirmation"].astext == confirm,
        )
    )
    if receipt:
        return {"already_applied": True}
    plan = retention_plan(db, tenant_id, policy, lock=True)
    if plan["confirmation"] != confirm:
        raise ValueError("Retention selection changed; preview and confirm again")
    if not plan["executable"]:
        raise ValueError(
            "Child rows exceed 10000; reduce batch size or review a separate erasure plan"
        )
    selected = _select(db, tenant_id, policy, lock=True)
    conversation_ids = [row.id for row in selected["conversations"]]
    if conversation_ids:
        for model in (Message, ToolExecution, ModelCall, VisitorSession, Conversation):
            field = model.id if model is Conversation else model.conversation_id
            db.execute(
                delete(model).where(model.tenant_id == tenant_id, field.in_(conversation_ids))
            )
    for row in selected["calls"]:
        # Keep minimal idempotency/outcome/usage identity; an old connection-test key cannot re-bill.
        complete = row.usage_complete
        row.steps = [
            {
                "status": "retained_summary",
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "attempts": row.attempts,
                "usage_complete": complete,
            }
        ]
        row.result = {"retention_redacted": True}
    for row in selected["audits"]:
        db.delete(row)
    for row in selected["documents"]:
        # On filesystem/DB failure the existing deleting row is recoverable; missing files are OK.
        storage.delete(tenant_id, row.id)
        db.delete(row)
    audit(db, tenant_id, "retention.execute", {"confirmation": confirm, "counts": plan["counts"]})
    db.flush()
    db.commit()
    return {
        "processed": plan["counts"],
        "call_records": "summary_retained_for_idempotency",
        "privacy_erasure_complete": False,
    }
