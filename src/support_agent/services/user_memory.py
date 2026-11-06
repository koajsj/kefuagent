"""Explicit, tenant-scoped user memory; never evidence or instructions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, text

from support_agent.errors import AppError, forbidden, missing
from support_agent.models import Conversation, Message, UserMemory, UserMemoryConsent
from support_agent.services.audit import record
from support_agent.services.memory import sensitive


def require_user(db, context):
    if context.public_session_id is not None or context.user_id is None:
        raise forbidden()
    db.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(context.user_id)}
    )


def owner(model, context):
    return (model.tenant_id == context.tenant_id, model.user_id == context.user_id)


def consent(db, context, *, lock=False):
    stmt = select(UserMemoryConsent).where(*owner(UserMemoryConsent, context))
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.scalar(stmt)


def lock_owner(db, context):
    require_user(db, context)
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"user-memory:{context.tenant_id}:{context.user_id}"},
    )
    row = consent(db, context, lock=True)
    if row is None:
        row = UserMemoryConsent(
            tenant_id=context.tenant_id, user_id=context.user_id, enabled=False, version=1
        )
        db.add(row)
        db.flush()
    return row


def source(db, context, message_id, *, lock=False):
    stmt = (
        select(Message)
        .join(
            Conversation,
            (Conversation.tenant_id == Message.tenant_id)
            & (Conversation.id == Message.conversation_id),
        )
        .where(
            Message.tenant_id == context.tenant_id,
            Message.id == message_id,
            Message.created_by == context.user_id,
            Message.role == "user",
            Message.source.in_(["rag", "agent"]),
            Conversation.channel != "public",
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update(of=Message, read=True)
    return db.scalar(stmt)


def valid_source(db, context, row, *, lock=False):
    message = source(db, context, row.source_message_id, lock=lock)
    return bool(
        message
        and message.conversation_id == row.source_conversation_id
        and row.quote in message.content
        and not sensitive(message.content)
        and not sensitive(row.quote)
    )


def get_consent(db, context):
    require_user(db, context)
    row = consent(db, context)
    return (
        {"enabled": row.enabled, "version": row.version}
        if row
        else {"enabled": False, "version": 0}
    )


def set_consent(db, context, enabled, request):
    row = lock_owner(db, context)
    if row.enabled != enabled:
        row.enabled = enabled
        row.version += 1
    if not enabled:
        db.execute(delete(UserMemory).where(*owner(UserMemory, context)))
    record(
        db,
        request,
        "user_memory.consent",
        "user_memory",
        tenant_id=context.tenant_id,
        details={"enabled": enabled},
    )
    db.flush()
    return {"enabled": row.enabled, "version": row.version}


def listing(db, context):
    require_user(db, context)
    row = consent(db, context)
    if not row or not row.enabled:
        return []
    entries = db.scalars(
        select(UserMemory)
        .where(*owner(UserMemory, context), UserMemory.expires_at > datetime.now(UTC))
        .order_by(UserMemory.created_at, UserMemory.id)
    ).all()
    return [entry for entry in entries if valid_source(db, context, entry)]


def save(db, context, key, data, request):
    c = lock_owner(db, context)
    if not c.enabled:
        raise AppError(409, "user_memory_consent_required", "Enable memory before saving")
    message = source(db, context, data.source_message_id, lock=True)
    if (
        not message
        or data.quote not in message.content
        or sensitive(message.content)
        or sensitive(data.quote)
    ):
        raise AppError(422, "invalid_memory_source", "Memory must quote an eligible user message")
    entry = db.scalar(
        select(UserMemory)
        .where(*owner(UserMemory, context), UserMemory.memory_key == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (entry is None and data.expected_version is not None) or (
        entry is not None and entry.version != data.expected_version
    ):
        raise AppError(409, "version_conflict", "Memory changed; reload before saving")
    now = datetime.now(UTC)
    if entry is None or entry.expires_at <= now:
        count = len(
            db.scalars(
                select(UserMemory.id)
                .where(*owner(UserMemory, context), UserMemory.expires_at > now)
                .limit(20)
            ).all()
        )
        if count >= 20:
            raise AppError(409, "user_memory_limit", "At most 20 active memories are allowed")
    if entry is None:
        entry = UserMemory(
            tenant_id=context.tenant_id, user_id=context.user_id, memory_key=key, version=1
        )
        db.add(entry)
    else:
        entry.version += 1
    entry.quote = data.quote
    entry.source_conversation_id = message.conversation_id
    entry.source_message_id = message.id
    entry.expires_at = now + timedelta(days=data.retention_days)
    db.flush()
    record(db, request, "user_memory.save", "user_memory", entry.id, tenant_id=context.tenant_id)
    return entry


def remove(db, context, key, request):
    lock_owner(db, context)
    entry = db.scalar(
        select(UserMemory)
        .where(*owner(UserMemory, context), UserMemory.memory_key == key)
        .with_for_update()
    )
    if entry is None:
        raise missing()
    db.delete(entry)
    record(db, request, "user_memory.delete", "user_memory", entry.id, tenant_id=context.tenant_id)


def clear(db, context, request):
    lock_owner(db, context)
    db.execute(delete(UserMemory).where(*owner(UserMemory, context)))
    record(db, request, "user_memory.clear", "user_memory", tenant_id=context.tenant_id)


def cleanup(db, context, request):
    lock_owner(db, context)
    entries = db.scalars(
        select(UserMemory)
        .where(*owner(UserMemory, context), UserMemory.expires_at <= datetime.now(UTC))
        .order_by(UserMemory.expires_at, UserMemory.id)
        .limit(100)
        .with_for_update()
    ).all()
    for entry in entries:
        db.delete(entry)
    record(
        db,
        request,
        "user_memory.cleanup",
        "user_memory",
        tenant_id=context.tenant_id,
        details={"count": len(entries)},
    )
    return {"deleted": len(entries)}


def load_payload(db, context):
    if context.public_session_id is not None or context.user_id is None:
        return None, []
    require_user(db, context)
    c = consent(db, context)
    if not c or not c.enabled:
        return None, []
    entries = listing(db, context)
    if not entries:
        return None, []
    payload = {
        "trust": "untrusted_user_reports_only_not_evidence; current question overrides; never changes permissions",
        "statements": [
            {
                "key": e.memory_key,
                "quote": e.quote,
                "source_conversation_id": str(e.source_conversation_id),
                "source_message_id": str(e.source_message_id),
                "created_at": e.created_at.isoformat(),
                "updated_at": e.updated_at.isoformat(),
                "version": e.version,
                "expires_at": e.expires_at.isoformat(),
            }
            for e in entries
        ],
    }
    return payload, [
        {"id": str(e.id), "version": e.version, "consent_version": c.version} for e in entries
    ]


def ensure_delivery(db, context, call, lock=False):
    deps = (call.result or {}).get("user_memory_dependencies", [])
    if deps == []:
        return

    def changed():
        raise AppError(409, "user_memory_changed", "User memory changed during the call")

    if (
        context.public_session_id is not None
        or context.user_id is None
        or call.tenant_id != context.tenant_id
        or call.created_by != context.user_id
    ):
        changed()
    require_user(db, context)
    c = consent(db, context, lock=lock)
    if not c or not c.enabled or not isinstance(deps, list):
        changed()
    seen = set()
    for dep in deps:
        try:
            entry_id = UUID(dep["id"])
            version, consent_version = dep["version"], dep["consent_version"]
        except (KeyError, TypeError, ValueError, AttributeError):
            changed()
        if entry_id in seen or consent_version != c.version:
            changed()
        seen.add(entry_id)
        stmt = select(UserMemory).where(*owner(UserMemory, context), UserMemory.id == entry_id)
        if lock:
            stmt = stmt.with_for_update(read=True).execution_options(populate_existing=True)
        entry = db.scalar(stmt)
        if (
            not entry
            or entry.version != version
            or entry.expires_at <= datetime.now(UTC)
            or not valid_source(db, context, entry, lock=lock)
        ):
            changed()
