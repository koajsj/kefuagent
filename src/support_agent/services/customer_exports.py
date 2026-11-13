"""Customer portability: reviewed immutable scope, snapshot ZIP and expiring private artifacts."""

import hashlib
import json
import tempfile
import time
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import exists, func, or_, select, text

from support_agent.dependencies import locked_staff_context
from support_agent.errors import AppError, forbidden
from support_agent.maintenance import confirmation
from support_agent.models import (
    AuditEvent,
    Conversation,
    ConversationAttachment,
    ConversationCustomer,
    Customer,
    CustomerExport,
    CustomerMemory,
    Message,
    Ticket,
    TicketEvent,
    VisitorFeedback,
    VisitorSession,
)
from support_agent.services import background, conversations
from support_agent.services.audit import record
from support_agent.services.memory import sensitive
from support_agent.services.resources import get_owned

POLICY = "customer_portability_v1"
PART_SIZE = 4 * 1024 * 1024
ARCHIVE_LIMIT = 512 * 1024 * 1024
ROW_LIMIT = 100000
EXCLUSIONS = [
    "internal_customer_notes",
    "internal_collaboration_notes",
    "staff_identity_and_notifications",
    "auth_tokens_and_credentials",
    "raw_model_tool_trace_and_arbitrary_metadata",
    "internal_message_protocol_rows",
    "other_customers",
    "personal_staff_memories",
    "shared_knowledge",
    "backups_and_provider_copies",
]


def bounded(db, stmt):
    rows = list(db.execute(stmt.limit(10001)))
    if len(rows) > 10000:
        raise AppError(
            409,
            "export_scope_too_large",
            "Review a narrower subject scope before exporting over 10000 related records",
        )
    return [[str(v) if isinstance(v, (UUID, datetime)) else v for v in row] for row in rows]


def scope(db, context, cid):
    customer = get_owned(db, Customer, context, cid)
    links = bounded(
        db,
        select(Conversation.id, Conversation.version, Conversation.updated_at)
        .join(
            ConversationCustomer,
            (ConversationCustomer.tenant_id == Conversation.tenant_id)
            & (ConversationCustomer.conversation_id == Conversation.id),
        )
        .where(Conversation.tenant_id == context.tenant_id, ConversationCustomer.customer_id == cid)
        .order_by(Conversation.id),
    )
    cids = [UUID(row[0]) for row in links]
    # An administrator attests that the linked transcript belongs to this subject.
    # Explicitly reject mixed customer ticket ownership instead of guessing it away.
    if db.scalar(
        select(Ticket.id)
        .where(
            Ticket.tenant_id == context.tenant_id,
            or_(
                Ticket.conversation_id.in_(cids)
                & Ticket.customer_id.is_not(None)
                & (Ticket.customer_id != cid),
                (Ticket.customer_id == cid)
                & exists(
                    select(ConversationCustomer.id).where(
                        ConversationCustomer.tenant_id == context.tenant_id,
                        ConversationCustomer.conversation_id == Ticket.conversation_id,
                        ConversationCustomer.customer_id != cid,
                    )
                ),
            ),
        )
        .limit(1)
    ):
        raise AppError(
            409,
            "export_subject_conflict",
            "A linked conversation contains another customer's ticket",
        )
    tickets = bounded(
        db,
        select(Ticket.id, Ticket.version)
        .where(
            Ticket.tenant_id == context.tenant_id,
            or_(Ticket.customer_id == cid, Ticket.conversation_id.in_(cids)),
        )
        .order_by(Ticket.id),
    )
    attachments = bounded(
        db,
        select(
            ConversationAttachment.id,
            ConversationAttachment.conversation_id,
            ConversationAttachment.sha256,
            ConversationAttachment.status,
            ConversationAttachment.public,
        )
        .where(
            ConversationAttachment.tenant_id == context.tenant_id,
            ConversationAttachment.conversation_id.in_(cids),
        )
        .order_by(ConversationAttachment.id),
    )
    memories = bounded(
        db,
        select(
            CustomerMemory.id,
            CustomerMemory.version,
            CustomerMemory.deleted_at,
            CustomerMemory.expires_at,
        )
        .where(CustomerMemory.tenant_id == context.tenant_id, CustomerMemory.customer_id == cid)
        .order_by(CustomerMemory.id),
    )
    feedback = bounded(
        db,
        select(VisitorFeedback.id, VisitorFeedback.updated_at)
        .where(
            VisitorFeedback.tenant_id == context.tenant_id,
            VisitorFeedback.conversation_id.in_(cids),
        )
        .order_by(VisitorFeedback.id),
    )
    message_counts = bounded(
        db,
        select(Message.conversation_id, func.count(), func.max(Message.created_at))
        .where(Message.tenant_id == context.tenant_id, Message.conversation_id.in_(cids))
        .group_by(Message.conversation_id)
        .order_by(Message.conversation_id),
    )
    if sum(row[1] for row in message_counts) > ROW_LIMIT:
        raise AppError(
            409, "export_scope_too_large", "Transcript exceeds the bounded portability batch"
        )
    snapshot = {
        "policy": POLICY,
        "customer_id": str(cid),
        "customer_version": customer.version,
        "conversations": links,
        "tickets": tickets,
        "attachments": attachments,
        "memories": memories,
        "exportable_memory_ids": [
            row[0]
            for row in memories
            if customer.memory_enabled
            and row[2] is None
            and datetime.fromisoformat(row[3]) > datetime.now(UTC)
        ],
        "feedback": feedback,
        "messages": message_counts,
    }
    return snapshot


def preview(db, context, cid):
    data = scope(db, context, cid)
    return {
        "scope": data,
        "scope_digest": confirmation(data),
        "policy": POLICY,
        "excluded": EXCLUSIONS,
        "requires_review": "Confirm linked transcripts/files concern this customer; third-party content needs authorized review. No automated complete PII classifier.",
        "identity_assurance": "staff_confirmed_not_customer_login",
        "artifact_expiry_hours": 24,
        "physical_cleanup": "local_supported_s3_version_erasure_BLOCKED",
    }


def create(db, context, cid, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"customer-export:{context.tenant_id}:{context.user_id}:{data.request_key}"},
    )
    previous = db.scalar(
        select(CustomerExport).where(
            CustomerExport.tenant_id == context.tenant_id,
            CustomerExport.requested_by == context.user_id,
            CustomerExport.request_key == data.request_key,
        )
    )
    if previous:
        if previous.customer_id != cid or previous.scope_digest != data.scope_digest:
            raise AppError(409, "idempotency_conflict", "Export key belongs to another scope")
        return previous
    snapshot = scope(db, context, cid)
    if confirmation(snapshot) != data.scope_digest:
        raise AppError(409, "export_scope_changed", "Preview changed; review the current scope")
    pending = db.scalar(
        select(func.count())
        .select_from(CustomerExport)
        .where(
            CustomerExport.tenant_id == context.tenant_id,
            CustomerExport.status.in_(["REQUESTED", "BUILDING", "READY"]),
            CustomerExport.expires_at > datetime.now(UTC),
        )
    )
    if pending >= 10:
        raise AppError(429, "export_capacity", "Expire existing exports before creating more")
    row = CustomerExport(
        tenant_id=context.tenant_id,
        customer_id=cid,
        requested_by=context.user_id,
        auth_session_id=request.state.session_id,
        request_key=data.request_key,
        scope=snapshot,
        scope_digest=data.scope_digest,
        parts=[],
        manifest={},
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(row)
    db.flush()
    record(
        db,
        request,
        "customer_export.request",
        "customer_export",
        row.id,
        tenant_id=context.tenant_id,
        details={"customer_id": str(cid), "scope_digest": row.scope_digest, "policy": POLICY},
    )
    return row


def accessible(db, context, eid, request):
    context = locked_staff_context(db, context, request, admin=True)
    row = get_owned(db, CustomerExport, context, eid, lock=True)
    if row.requested_by != context.user_id:
        raise forbidden()
    return row, context


def verify_transcripts(db, context, customer_id, request):
    # A cached archive must obey the same historical source/authorization gate as
    # live message delivery, including knowledge withdrawn after the snapshot.
    for link in scope(db, context, customer_id)["conversations"]:
        offset = 0
        while True:
            batch = conversations.history(db, context, UUID(link[0]), 100, offset, request)
            for message in batch:
                metadata = getattr(message, "message_metadata", None) or getattr(
                    message, "metadata", {}
                )
                if isinstance(metadata, dict) and metadata.get("redacted"):
                    raise AppError(
                        409,
                        "export_source_unavailable",
                        "Transcript source or delivery authorization is unavailable",
                    )
            if len(batch) < 100:
                break
            offset += len(batch)


def checked_text(value):
    if sensitive(value):
        raise AppError(
            409,
            "export_sensitive_content",
            "Known credential material requires source review before portability",
        )
    return value


def build(db, context, job, request, target):
    """Called in one REPEATABLE READ snapshot. JSONL is written row by row."""
    current = scope(db, context, job.customer_id)
    if confirmation(current) != job.scope_digest:
        raise AppError(409, "export_scope_changed", "The confirmed scope changed before snapshot")
    cids = [UUID(x[0]) for x in current["conversations"]]
    tids = [UUID(x[0]) for x in current["tickets"]]
    customer = get_owned(db, Customer, context, job.customer_id)
    count, files = 0, []
    protocol_rows_excluded = 0
    deadline = time.monotonic() + 480

    def lines(archive, name, iterable):
        nonlocal count
        with archive.open(name, "w") as stream:
            for item in iterable:
                count += 1
                if (
                    count > ROW_LIMIT
                    or target.tell() > ARCHIVE_LIMIT
                    or time.monotonic() > deadline
                ):
                    raise AppError(
                        409, "export_scope_too_large", "Export exceeds the bounded archive limit"
                    )
                value = json.dumps(item, ensure_ascii=False, default=str, separators=(",", ":"))
                checked_text(value)
                stream.write((value + "\n").encode())
        files.append(name)

    def records(model, predicate):
        return db.scalars(
            select(model)
            .where(model.tenant_id == context.tenant_id, predicate)
            .order_by(model.id)
            .execution_options(yield_per=100)
        )

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        lines(
            archive,
            "customer.jsonl",
            [
                {
                    key: getattr(customer, key)
                    for key in (
                        "id",
                        "name",
                        "email",
                        "phone",
                        "external_ref",
                        "tags",
                        "status",
                        "created_at",
                        "updated_at",
                    )
                }
            ],
        )
        lines(
            archive,
            "identity_links.jsonl",
            (
                {
                    "conversation_id": x[0],
                    "method": "staff_confirmed",
                    "verified_customer_login": False,
                }
                for x in current["conversations"]
            ),
        )
        lines(
            archive,
            "conversations.jsonl",
            (
                {
                    key: getattr(row, key)
                    for key in (
                        "id",
                        "subject",
                        "channel",
                        "status",
                        "support_state",
                        "created_at",
                        "updated_at",
                    )
                }
                for row in records(Conversation, Conversation.id.in_(cids))
            ),
        )

        def messages():
            nonlocal protocol_rows_excluded
            for cid in cids:
                offset = 0
                while True:
                    batch = conversations.history(db, context, cid, 100, offset, request)
                    for row in batch:
                        metadata = getattr(row, "message_metadata", None) or getattr(
                            row, "metadata", {}
                        )
                        if isinstance(metadata, dict) and metadata.get("redacted"):
                            raise AppError(
                                409,
                                "export_source_denied",
                                "Historical answer delivery is no longer authorized",
                            )
                        if not (
                            row.role == "user"
                            or (
                                row.role == "assistant"
                                and (
                                    row.source in {"manual", "rag"} or metadata.get("final") is True
                                )
                            )
                        ):
                            protocol_rows_excluded += 1
                            continue
                        yield {
                            "id": row.id,
                            "conversation_id": row.conversation_id,
                            "role": row.role,
                            "content": row.content,
                            "source": row.source,
                            "created_at": row.created_at,
                        }
                    if len(batch) < 100:
                        break
                    offset += 100

        lines(archive, "messages.jsonl", messages())
        lines(
            archive,
            "tickets.jsonl",
            (
                {
                    key: getattr(row, key)
                    for key in (
                        "id",
                        "customer_id",
                        "conversation_id",
                        "title",
                        "description",
                        "status",
                        "priority",
                        "due_at",
                        "resolved_at",
                        "version",
                        "created_at",
                        "updated_at",
                    )
                }
                for row in records(Ticket, Ticket.id.in_(tids))
            ),
        )
        # Audit event/transition metadata is allowed; staff identities and arbitrary
        # details/notes are excluded by policy, never copied as raw JSON.
        lines(
            archive,
            "ticket_events.jsonl",
            (
                {
                    "id": row.id,
                    "ticket_id": row.ticket_id,
                    "action": row.action,
                    "created_at": row.created_at,
                    "changes": {
                        key: value
                        for key, value in row.details.get("changes", {}).items()
                        if key in {"status", "priority", "due_at", "resolved_at"}
                    },
                }
                for row in records(TicketEvent, TicketEvent.ticket_id.in_(tids))
            ),
        )
        now = datetime.now(UTC)
        lines(
            archive,
            "customer_memories.jsonl",
            (
                {
                    "id": row.id,
                    "source_conversation_id": row.source_conversation_id,
                    "source_message_id": row.source_message_id,
                    "content": row.content
                    if row.deleted_at is None and row.expires_at > now and customer.memory_enabled
                    else None,
                    "withdrawn": row.deleted_at is not None,
                    "expires_at": row.expires_at,
                }
                for row in records(CustomerMemory, CustomerMemory.customer_id == job.customer_id)
            ),
        )
        lines(
            archive,
            "feedback.jsonl",
            (
                {
                    key: getattr(row, key)
                    for key in (
                        "id",
                        "conversation_id",
                        "rating",
                        "comment",
                        "created_at",
                        "updated_at",
                    )
                }
                for row in records(VisitorFeedback, VisitorFeedback.conversation_id.in_(cids))
            ),
        )
        lines(
            archive,
            "activity.jsonl",
            (
                {
                    "id": row.id,
                    "action": row.action,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "created_at": row.created_at,
                }
                for row in records(
                    AuditEvent,
                    or_(
                        (AuditEvent.resource_type == "customer")
                        & (AuditEvent.resource_id == job.customer_id),
                        AuditEvent.action.in_(
                            [
                                "customer_memory.confirm",
                                "customer_memory.forget",
                                "conversation.customer_link",
                            ]
                        )
                        & (AuditEvent.details["customer_id"].as_string() == str(job.customer_id)),
                        (AuditEvent.resource_type == "ticket") & AuditEvent.resource_id.in_(tids),
                        (AuditEvent.resource_type == "conversation")
                        & AuditEvent.resource_id.in_(cids),
                    ),
                )
            ),
        )
        attachments = []
        for row in records(
            ConversationAttachment, ConversationAttachment.conversation_id.in_(cids)
        ):
            if row.status != "ready":
                raise AppError(
                    409,
                    "export_attachment_unavailable",
                    "An attachment is not ready; no partial export published",
                )
            # Private staff files are internal by policy; the manifest lists them.
            if not row.public and row.visitor_session_id is None:
                attachments.append({"id": str(row.id), "excluded": "internal_staff_attachment"})
                continue
            if row.visitor_session_id:
                visitor = db.get(VisitorSession, row.visitor_session_id)
                if visitor is None or visitor.conversation_id != row.conversation_id:
                    raise AppError(
                        409,
                        "export_subject_conflict",
                        "Attachment owner does not match its conversation",
                    )
            content = request.app.state.storage.read(context.tenant_id, row.id)
            if hashlib.sha256(content).hexdigest() != row.sha256:
                raise AppError(409, "export_attachment_unavailable", "Attachment integrity failed")
            if row.media_type.startswith("text/"):
                checked_text(content.decode("utf-8", errors="replace"))
            name = "attachments/" + str(row.id)
            archive.writestr(name, content)
            if target.tell() > ARCHIVE_LIMIT or time.monotonic() > deadline:
                raise AppError(409, "export_scope_too_large", "Export file size exceeded")
            attachments.append(
                {
                    "id": str(row.id),
                    "conversation_id": str(row.conversation_id),
                    "filename": row.filename,
                    "path": name,
                    "size": row.size_bytes,
                    "sha256": row.sha256,
                }
            )
        manifest = {
            "format": "kefuagent.customer-portability.v1",
            "policy": POLICY,
            "scope_digest": job.scope_digest,
            "internal_message_protocol_rows_excluded": protocol_rows_excluded,
            "snapshot_at": now.isoformat(),
            "customer_id": str(job.customer_id),
            "complete_within_confirmed_policy": True,
            "identity": "staff_confirmed_only_no_separate_CustomerIdentity",
            "files": files,
            "attachments": attachments,
            "excluded": EXCLUSIONS,
            "relation": "immutable ConversationCustomer -> conversation/messages/files/feedback; customer or linked conversation -> tickets -> events; customer -> memory",
            "sensitive_data_review": "administrator_attested_plus_known_credential_pattern_blocking; not_complete_DLP",
            "missing": [],
        }
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, default=str))
    target.flush()
    if target.tell() > ARCHIVE_LIMIT:
        raise AppError(409, "export_scope_too_large", "Export file size exceeded")
    return manifest


def process_one(db, tid, state):
    row = db.scalar(
        select(CustomerExport)
        .where(
            CustomerExport.tenant_id == tid,
            or_(
                CustomerExport.status == "REQUESTED",
                (CustomerExport.status == "BUILDING")
                & (CustomerExport.lease_until <= datetime.now(UTC)),
            ),
        )
        .order_by(CustomerExport.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not row:
        return False
    if row.status == "BUILDING":
        row.status, row.error_category = "FAILED", "export_interrupted"
        db.commit()
        return True
    eid, token = row.id, uuid4()
    row.status, row.lease_token, row.lease_until = (
        "BUILDING",
        token,
        datetime.now(UTC) + timedelta(minutes=10),
    )
    request = background.request_for(state, row)
    db.commit()
    from support_agent.db import set_tenant

    try:
        # First operation of a new transaction, before any tenant/auth query.
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        set_tenant(db, tid)
        row = db.get(CustomerExport, eid)
        context = background.identity(db, row, request, admin=True)
        with tempfile.TemporaryFile() as archive:
            manifest = build(db, context, row, request, archive)
            archive.seek(0)
            parts = []
            while chunk := archive.read(PART_SIZE):
                parts.append(
                    {
                        "id": str(uuid4()),
                        "size": len(chunk),
                        "sha256": hashlib.sha256(chunk).hexdigest(),
                    }
                )
            row.parts = parts  # Ownership is durable before any external write.
            db.commit()
            archive.seek(0)
            for part in parts:
                state.storage.write(tid, UUID(part["id"]), archive.read(part["size"]))
        set_tenant(db, tid)
        row = db.get(CustomerExport, eid, populate_existing=True)
        context = background.identity(db, row, request, admin=True)
        if (
            row.lease_token != token
            or row.status != "BUILDING"
            or row.expires_at <= datetime.now(UTC)
            or confirmation(scope(db, context, row.customer_id)) != row.scope_digest
        ):
            raise AppError(409, "export_scope_changed", "Scope or task changed before publication")
        verify_transcripts(db, context, row.customer_id, request)
        row.status, row.manifest, row.lease_until = "READY", manifest, None
        record(
            db,
            request,
            "customer_export.ready",
            "customer_export",
            eid,
            tenant_id=tid,
            details={"scope_digest": row.scope_digest, "parts": len(parts)},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        set_tenant(db, tid)
        row = db.scalar(
            select(CustomerExport)
            .where(CustomerExport.tenant_id == tid, CustomerExport.id == eid)
            .with_for_update()
        )
        if row.lease_token == token:
            row.status, row.error_category, row.lease_until = (
                "FAILED",
                getattr(exc, "code", None) or "export_failed",
                None,
            )
        record(
            db,
            request,
            "customer_export.failed",
            "customer_export",
            eid,
            tenant_id=tid,
            outcome="failure",
            reason=row.error_category,
        )
        db.commit()
    return True


def download(db, context, eid, request):
    row, context = accessible(db, context, eid, request)
    if row.status != "READY" or row.expires_at <= datetime.now(UTC):
        raise AppError(409, "export_not_ready", "Export is unavailable or expired")
    if confirmation(scope(db, context, row.customer_id)) != row.scope_digest:
        raise AppError(
            409, "export_scope_changed", "Source changed; request a fresh reviewed export"
        )
    verify_transcripts(db, context, row.customer_id, request)
    parts, digest = row.parts, row.scope_digest
    db.commit()
    out = tempfile.TemporaryFile()
    try:
        for part in parts:
            content = request.app.state.storage.read(context.tenant_id, UUID(part["id"]))
            if (
                len(content) != part["size"]
                or hashlib.sha256(content).hexdigest() != part["sha256"]
            ):
                raise AppError(
                    409, "export_integrity_failed", "Export integrity verification failed"
                )
            out.write(content)
        row, context = accessible(db, context, eid, request)
        if (
            row.status != "READY"
            or row.expires_at <= datetime.now(UTC)
            or row.scope_digest != digest
            or confirmation(scope(db, context, row.customer_id)) != digest
        ):
            raise AppError(409, "export_scope_changed", "Source or export changed during download")
        verify_transcripts(db, context, row.customer_id, request)
        record(
            db,
            request,
            "customer_export.download",
            "customer_export",
            eid,
            tenant_id=context.tenant_id,
            details={"scope_digest": digest},
        )
        out.seek(0)
        return out
    except BaseException:
        out.close()
        raise


def cleanup_one(db, tid, state):
    row = db.scalar(
        select(CustomerExport)
        .where(
            CustomerExport.tenant_id == tid,
            CustomerExport.expires_at <= datetime.now(UTC),
            CustomerExport.status != "DELETED",
            or_(
                CustomerExport.lease_until.is_(None),
                CustomerExport.lease_until <= datetime.now(UTC),
            ),
        )
        .order_by(CustomerExport.updated_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not row:
        return False
    row.status = "EXPIRED"  # Expiry is enforced at download even without Worker.
    eid, parts = row.id, row.parts
    row.lease_until = datetime.now(UTC) + timedelta(minutes=5)
    request = background.request_for(state, row)
    db.commit()
    failed = False
    for part in parts:
        try:
            state.storage.delete(tid, UUID(part["id"]))
        except OSError:
            failed = True
    from support_agent.db import set_tenant

    set_tenant(db, tid)
    row = db.scalar(
        select(CustomerExport)
        .where(CustomerExport.tenant_id == tid, CustomerExport.id == eid)
        .with_for_update()
    )
    row.status = "CLEANUP_BLOCKED" if failed else "DELETED"
    row.error_category = "export_storage_cleanup_failed" if failed else None
    row.lease_until = datetime.now(UTC) + timedelta(minutes=5) if failed else None
    record(
        db,
        request,
        "customer_export.cleanup",
        "customer_export",
        eid,
        tenant_id=tid,
        outcome="failure" if failed else "success",
        reason=row.error_category,
    )
    db.commit()
    return True
