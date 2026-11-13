"""Private attachments: a committed ownership row precedes immutable file storage."""

from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, or_, select

from support_agent.dependencies import locked_staff_context, resume_context
from support_agent.errors import AppError, missing
from support_agent.ingestion import validate_upload
from support_agent.models import Conversation, ConversationAttachment
from support_agent.services import operations
from support_agent.services.audit import record
from support_agent.services.resources import get_owned


def conversation(db, context, cid, *, lock=False):
    if context.public_session_id is not None and cid != context.conversation_id:
        raise missing()
    return get_owned(db, Conversation, context, cid, lock=lock)


def listing(db, context, cid, limit, offset, request):
    if context.public_session_id is not None:
        from support_agent.services.public_delivery import delivery_guard

        context = delivery_guard(db, context, request)
    conversation(db, context, cid)
    query = select(ConversationAttachment).where(
        ConversationAttachment.tenant_id == context.tenant_id,
        ConversationAttachment.conversation_id == cid,
    )
    if context.public_session_id is not None:
        query = query.where(
            or_(
                ConversationAttachment.public.is_(True),
                ConversationAttachment.visitor_session_id == context.public_session_id,
            )
        )
    return db.scalars(
        query.order_by(ConversationAttachment.created_at, ConversationAttachment.id)
        .limit(limit)
        .offset(offset)
    ).all()


def upload(db, context, cid, key, filename, content, public, request):
    _, media = validate_upload(filename, content)
    context = (
        resume_context(db, context, request)
        if context.public_session_id
        else locked_staff_context(db, context, request)
    )
    if context.public_session_id is not None:
        from support_agent.services.public_delivery import delivery_guard

        context = delivery_guard(db, context, request)
    conv = conversation(db, context, cid, lock=True)
    if conv.status != "open":
        raise AppError(409, "conversation_closed", "Closed conversations cannot receive files")
    if context.public_session_id is None:
        operations.controlled(db, context, conv)
    else:
        public = True
    owner = context.public_session_id or context.user_id
    aid = uuid5(NAMESPACE_URL, f"attachment:{context.tenant_id}:{cid}:{owner}:{key}")
    digest = sha256(content).hexdigest()
    row = db.scalar(
        select(ConversationAttachment)
        .where(
            ConversationAttachment.tenant_id == context.tenant_id, ConversationAttachment.id == aid
        )
        .with_for_update()
    )
    if row:
        if row.sha256 != digest or row.filename != filename or row.public != public:
            raise AppError(
                409, "idempotency_conflict", "Attachment key already has different input"
            )
        if row.status == "ready":
            return row
    else:
        count = db.scalar(
            select(func.count())
            .select_from(ConversationAttachment)
            .where(
                ConversationAttachment.tenant_id == context.tenant_id,
                ConversationAttachment.conversation_id == cid,
            )
        )
        if count >= 20:
            raise AppError(409, "attachment_limit", "Conversation attachment limit reached")
        row = ConversationAttachment(
            id=aid,
            tenant_id=context.tenant_id,
            conversation_id=cid,
            visitor_session_id=context.public_session_id,
            created_by=None if context.public_session_id else context.user_id,
            filename=filename,
            media_type=media,
            size_bytes=len(content),
            sha256=digest,
            public=public,
        )
        db.add(row)
        db.flush()
        record(
            db,
            request,
            "attachment.register",
            "conversation_attachment",
            aid,
            tenant_id=context.tenant_id,
        )
    db.commit()
    try:
        request.app.state.storage.write(context.tenant_id, aid, content)
    except OSError:
        raise AppError(
            503,
            "attachment_storage_unknown",
            "Attachment ownership is retained; retry with the same key and bytes to reconcile",
        ) from None
    context = (
        resume_context(db, context, request)
        if context.public_session_id
        else locked_staff_context(db, context, request)
    )
    if context.public_session_id is not None:
        from support_agent.services.public_delivery import delivery_guard

        context = delivery_guard(db, context, request)
    conv = conversation(db, context, cid, lock=True)
    if conv.status != "open":
        raise AppError(
            409,
            "conversation_closed",
            "Conversation closed during upload; ownership remains pending",
        )
    if context.public_session_id is None:
        operations.controlled(db, context, conv)
    row = get_owned(db, ConversationAttachment, context, aid, lock=True)
    row.status = "ready"
    record(
        db,
        request,
        "attachment.upload",
        "conversation_attachment",
        aid,
        tenant_id=context.tenant_id,
    )
    db.flush()
    return row


def download(db, context, cid, aid, request):
    conversation(db, context, cid)
    row = get_owned(db, ConversationAttachment, context, aid)
    if row.conversation_id != cid or (
        context.public_session_id is not None
        and not row.public
        and row.visitor_session_id != context.public_session_id
    ):
        raise missing()
    if row.status != "ready":
        raise AppError(409, "attachment_not_ready", "File state is not confirmed ready")
    expected = row.sha256
    db.commit()
    try:
        data = request.app.state.storage.read(context.tenant_id, aid)
    except OSError:
        raise AppError(
            503, "attachment_storage_unknown", "Attachment storage is unavailable"
        ) from None
    context = (
        resume_context(db, context, request)
        if context.public_session_id is not None
        else locked_staff_context(db, context, request)
    )
    if context.public_session_id is not None:
        from support_agent.services.public_delivery import delivery_guard

        context = delivery_guard(db, context, request)
    conversation(db, context, cid, lock=True)
    row = get_owned(db, ConversationAttachment, context, aid, lock=True)
    if row.status != "ready" or row.sha256 != expected or sha256(data).hexdigest() != expected:
        raise AppError(409, "attachment_changed", "Attachment integrity or visibility changed")
    if (
        context.public_session_id is not None
        and not row.public
        and row.visitor_session_id != context.public_session_id
    ):
        raise missing()
    return data, row.filename
