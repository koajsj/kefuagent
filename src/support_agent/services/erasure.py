"""Dependency-aware erasure assessments. Unknown ownership is never authority to purge."""

from sqlalchemy import func, select, text

from support_agent.dependencies import locked_staff_context
from support_agent.models import Base, Conversation, Customer, ErasureRequest, Membership, User
from support_agent.services.audit import record
from support_agent.services.resources import get_owned

# JSON and external media have no enforceable ownership index. A FK graph alone
# cannot prove absence of personal data, including data copied to shared records.
BLOCKERS = {
    "user_scoped_rls": "Personal memory/cursors require each owner's context; tenant administration cannot enumerate them",
    "shared_records_and_retention": "Actor references and multi-party tickets/messages lack approved subject/retention rules",
    "unindexed_copies": "Historical JSON, trace, summaries, audit details and approved-operation ciphertext may contain copies",
    "storage_versions": "S3 object versions/replicas and attachment uploads in flight lack a version-aware purge manifest",
    "product_copies": "Chunk embeddings, private export parts/manifests, draft originals/citations and temporary files require coordinated subject-aware purging",
    "backup_replay": "Backup expiry and restored-data suppression are operator-managed, not enforceable online",
}


def preview(db, context, data):
    model = {"user": User, "customer": Customer, "conversation": Conversation}[data.subject_type]
    if model is User:
        row = db.scalar(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(User.id == data.subject_id, Membership.tenant_id == context.tenant_id)
        )
        if row is None:
            from support_agent.errors import missing

            raise missing()
    else:
        get_owned(db, model, context, data.subject_id)
    # Return dependency names, never payloads or counts hidden by owner RLS.
    graph = []
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_key_constraints:
            graph.append(
                {
                    "from": table.name,
                    "columns": [e.parent.name for e in fk.elements],
                    "to": fk.referred_table.name,
                    "target_columns": [e.column.name for e in fk.elements],
                    "on_delete": fk.ondelete or "NO ACTION",
                }
            )
    visible = {}
    if model is Conversation:
        from support_agent.models import ConversationAttachment, Message, ModelCall, Ticket

        for child in (Message, ModelCall, ConversationAttachment, Ticket):
            visible[child.__tablename__] = db.scalar(
                select(func.count())
                .select_from(child)
                .where(
                    child.tenant_id == context.tenant_id, child.conversation_id == data.subject_id
                )
            )
    return {
        "status": "BLOCKED",
        "accepted_for_purge": False,
        "access_blocked": False,
        "complete": False,
        "subject_type": data.subject_type,
        "subject_id": str(data.subject_id),
        "visible_counts": visible,
        "unknown_counts": [
            "user_memories",
            "conversation_read_cursors",
            "historical_json",
            "chunk_embeddings",
            "customer_export_parts",
            "reply_drafts",
            "storage_versions",
            "backups",
        ],
        "blockers": BLOCKERS,
        "foreign_keys": graph,
        "unindexed_payload_columns": [
            f"{t.name}.{c.name}"
            for t in Base.metadata.sorted_tables
            for c in t.columns
            if c.type.__class__.__name__ in {"JSONB", "Text", "String"}
        ],
        "absent_models": [
            "CustomerIdentity",
            "AgentRun (represented by ModelCall)",
            "AgentTrace (audit/steps projection)",
        ],
        "audit_boundary": "This request records identifiers and reason codes only; no source payload is copied. Existing audit is retained pending subject/retention review.",
    }


def request_erasure(db, context, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"erasure:{context.tenant_id}:{data.subject_type}:{data.subject_id}"},
    )
    assessment = preview(db, context, data)
    row = db.scalar(
        select(ErasureRequest)
        .where(
            ErasureRequest.tenant_id == context.tenant_id,
            ErasureRequest.subject_type == data.subject_type,
            ErasureRequest.subject_id == data.subject_id,
        )
        .with_for_update()
    )
    if row is None:
        row = ErasureRequest(
            tenant_id=context.tenant_id,
            requested_by=context.user_id,
            subject_type=data.subject_type,
            subject_id=data.subject_id,
            status="REQUESTED",
            assessment={},
        )
        db.add(row)
        db.flush()
        record(
            db, request, "erasure.requested", "erasure_request", row.id, tenant_id=context.tenant_id
        )
    else:
        row.attempts += 1
    # Not accepted: don't pretend access was blocked, don't touch source records,
    # and never expose an execution confirmation while any dependency is UNKNOWN.
    row.assessment = assessment
    row.status = "BLOCKED"
    record(
        db,
        request,
        "erasure.blocked",
        "erasure_request",
        row.id,
        tenant_id=context.tenant_id,
        outcome="rejected",
        reason="dependency_ownership_unknown",
        details={"attempt": row.attempts, "blockers": list(BLOCKERS)},
    )
    db.flush()
    return row
