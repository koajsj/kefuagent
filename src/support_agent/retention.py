"""Explicit, bounded tenant retention; disabled policies never select data."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from support_agent.models import (
    AuditEvent,
    Collaboration,
    Conversation,
    ConversationSummary,
    Document,
    DocumentChunk,
    Message,
    ModelCall,
    ToolExecution,
    VisitorFeedback,
    VisitorSession,
)

# These weak links are retained when knowledge is erased. Until every affected
# record is enumerated and bound to confirmation, their impact is UNKNOWN.
KNOWLEDGE_REFERENCE_DEPENDENCIES = (
    "model_calls.result/steps",
    "model_calls.result.knowledge_dependencies",
    "messages.metadata",
    "tool_executions.result",
    "collaboration.details",
    "chunk_embeddings",
    "reply_drafts.content/original_content/citations",
    "customer_exports.manifest/private_parts",
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


def retention_plan(db, tenant_id, policy, *, lock=False, _selected=None):
    from support_agent.maintenance import confirmation

    selected = _select(db, tenant_id, policy, lock=lock) if _selected is None else _selected
    ids = [row.id for row in selected["conversations"]]
    counts = {name: len(rows) for name, rows in selected.items()}

    # Bind identities AND contents, not only counts. Derived search vectors need
    # not be duplicated in the hash. No payload is returned in the preview.
    def snapshot(row):
        values = {
            attr.key: getattr(row, attr.key)
            for attr in row.__mapper__.column_attrs
            if attr.key not in {"search_vector", "chinese_vector"}
        }
        return {"id": str(row.id), "version_digest": confirmation(values)}

    objects = {name: [snapshot(row) for row in rows] for name, rows in selected.items()}
    remaining = max(0, 10000 - sum(counts.values()))
    complete = True

    def children(name, model, field, parent_ids):
        nonlocal remaining, complete
        rows = []
        if parent_ids:
            query = (
                select(model)
                .where(model.tenant_id == tenant_id, field.in_(parent_ids))
                .order_by(model.id)
                .limit(remaining + 1)
            )
            # Document revisions follow the same document -> chunks lock order.
            # Conversation deletion is blocked; don't take unnecessary child locks.
            if lock and model is DocumentChunk:
                query = query.with_for_update().execution_options(populate_existing=True)
            rows = list(db.scalars(query))
        exact = len(rows) <= remaining
        complete = complete and exact
        # None means UNKNOWN, never an invented zero or an exact truncated count.
        counts[name] = len(rows) if exact else None
        objects[name] = [snapshot(row) for row in rows[:remaining]]
        remaining = max(0, remaining - len(rows))

    children(
        "document_chunks",
        DocumentChunk,
        DocumentChunk.document_id,
        [row.id for row in selected["documents"]],
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
        children(name, model, model.conversation_id, ids)
    # New business records and files are retained until the complete impact graph is reviewed.
    business_dependencies = [
        "conversation_customers",
        "tickets",
        "ticket_events",
        "staff_notifications",
        "conversation_attachments",
        "attachment_storage_versions",
        "customer_memories",
        "reply_drafts",
        "customer_exports",
        "customer_export_parts",
    ]
    for name in business_dependencies:
        counts[name] = None if ids else 0
    counts["user_memories"] = None if ids else 0
    counts["conversation_read_cursors"] = None if ids else 0
    config = {
        key: getattr(policy, key)
        for key in ("conversations_days", "visitors_days", "calls_days", "audit_days", "batch_size")
    }
    config["documents"] = getattr(policy, "documents", False)
    # Message deletion cascades into user-scoped memory/cursor tables. A tenant-only
    # maintenance context cannot see their full counts through FORCE RLS. Refuse
    # conversation erasure until a separately reviewed dependency-aware plan exists;
    # never bypass user RLS or present hidden rows as zero in an approval preview.
    unknown = (
        ["user_memories", "conversation_read_cursors", *business_dependencies] if ids else []
    ) + (list(KNOWLEDGE_REFERENCE_DEPENDENCIES) if selected["documents"] else [])
    for name in KNOWLEDGE_REFERENCE_DEPENDENCIES:
        counts[name] = None if selected["documents"] else 0
    blocked = bool(unknown)
    blocked_reason = (
        "user_scoped_cascade_review_required"
        if ids
        else "knowledge_reference_review_required"
        if selected["documents"]
        else "dependency_limit_exceeded"
        if not complete
        else None
    )
    executable = complete and not blocked
    return {
        "tenant_id": str(tenant_id),
        "policy": config,
        "counts": counts,
        "bounded": complete,
        "executable": executable,
        "blocked_reason": blocked_reason,
        "unscoped_dependencies": unknown,
        "objects": objects,
        "effects": {
            "blocked": (
                [
                    "conversations",
                    "messages",
                    "conversation_calls",
                    "tool_executions",
                    "visitor_sessions",
                    "feedback",
                    "collaboration",
                    "summaries",
                ]
                if ids
                else []
            )
            + (["documents", "document_chunks", "private_files"] if selected["documents"] else [])
            + ([name for name in ("audits", "calls") if selected[name]] if not executable else []),
            "deleted": ["audits"] if executable and selected["audits"] else [],
            "redacted": ["calls"] if executable and selected["calls"] else [],
            "retained": [
                "tenants",
                "users",
                "memberships",
                "agents",
                "publications",
                "knowledge_bases",
                "credentials",
                "memory_consents",
            ],
            "unknown": unknown,
            "private_files": {
                "document_ids": [str(row.id) for row in selected["documents"]],
                "state": "UNKNOWN" if selected["documents"] else "NOT_SELECTED",
                "action": "BLOCKED" if selected["documents"] else "NONE",
                "recovery": "retain existing deleting tombstones and files; no unlink attempted",
            },
        },
        "confirmation": confirmation(
            [3, str(tenant_id), config, objects, counts, complete, unknown]
        )
        if executable
        else None,
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
    selected = _select(db, tenant_id, policy, lock=True)
    plan = retention_plan(db, tenant_id, policy, lock=True, _selected=selected)
    if not plan["executable"]:
        if plan["blocked_reason"] == "user_scoped_cascade_review_required":
            raise ValueError(
                "Conversation erasure requires a dependency-aware user memory/read cursor review; "
                "no records were deleted. Disable conversation/visitor retention to process "
                "independent audit or call retention; document erasure is separately blocked."
            )
        if plan["blocked_reason"] == "knowledge_reference_review_required":
            raise ValueError(
                "Knowledge erasure requires a complete historical-reference preview; "
                "no rows or files were deleted. Disable document cleanup to process "
                "independent audit or call retention."
            )
        raise ValueError(
            "Child rows exceed 10000; reduce batch size or review a separate erasure plan"
        )
    if plan["confirmation"] != confirm:
        raise ValueError("Retention selection changed; preview and confirm again")
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
    audit(db, tenant_id, "retention.execute", {"confirmation": confirm, "counts": plan["counts"]})
    db.flush()
    db.commit()
    return {
        "processed": plan["counts"],
        "call_records": "summary_retained_for_idempotency",
        "privacy_erasure_complete": False,
    }
