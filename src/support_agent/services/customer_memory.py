"""Staff-only, opt-in quotations with immutable provenance and non-restorable tombstones.

Customer facts never come from model output and are not automatically sent to models.
Forgetting clears this copy; it does not claim to erase the source conversation or backups.
"""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import func, select, update

from support_agent.dependencies import locked_staff_context
from support_agent.errors import AppError, forbidden
from support_agent.models import (
    Conversation,
    ConversationCustomer,
    Customer,
    CustomerMemory,
    Message,
)
from support_agent.services import operations
from support_agent.services.audit import record
from support_agent.services.resources import get_owned


def listing(db, context, cid, limit, offset):
    customer = get_owned(db, Customer, context, cid)
    if not customer.memory_enabled or customer.status != "active":
        return []
    return db.scalars(
        select(CustomerMemory)
        .where(
            CustomerMemory.tenant_id == context.tenant_id,
            CustomerMemory.customer_id == cid,
            CustomerMemory.deleted_at.is_(None),
            CustomerMemory.expires_at > func.now(),
        )
        .order_by(CustomerMemory.created_at.desc(), CustomerMemory.id)
        .limit(limit)
        .offset(offset)
    ).all()


def consent(db, context, cid, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    customer = get_owned(db, Customer, context, cid, lock=True)
    operations.check_version(customer, data.expected_version)
    customer.memory_enabled = data.enabled
    customer.version += 1
    if not data.enabled:
        db.execute(
            update(CustomerMemory)
            .where(
                CustomerMemory.tenant_id == context.tenant_id,
                CustomerMemory.customer_id == cid,
                CustomerMemory.deleted_at.is_(None),
            )
            .values(content=None, deleted_at=datetime.now(UTC), version=CustomerMemory.version + 1)
        )
    record(
        db,
        request,
        "customer_memory.consent",
        "customer",
        cid,
        tenant_id=context.tenant_id,
        details={"enabled": data.enabled, "customer_version": customer.version},
    )
    db.flush()
    return customer


def create(db, context, cid, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    source = get_owned(db, Message, context, data.source_message_id)
    conversation = get_owned(db, Conversation, context, source.conversation_id, lock=True)
    customer = get_owned(db, Customer, context, cid, lock=True)
    operations.check_version(customer, data.expected_customer_version)
    linked = db.scalar(
        select(ConversationCustomer.id).where(
            ConversationCustomer.tenant_id == context.tenant_id,
            ConversationCustomer.conversation_id == conversation.id,
            ConversationCustomer.customer_id == cid,
        )
    )
    if not linked or source.role != "user":
        raise forbidden()
    if not customer.memory_enabled or customer.status != "active":
        raise AppError(
            409, "customer_memory_disabled", "Enable active customer memory explicitly first"
        )
    if data.content not in source.content or not data.content.strip():
        raise AppError(
            422,
            "memory_source_mismatch",
            "Select an exact quotation from the customer's user message",
        )
    digest = sha256(data.content.encode()).hexdigest()
    existing = db.scalar(
        select(CustomerMemory).where(
            CustomerMemory.tenant_id == context.tenant_id,
            CustomerMemory.customer_id == cid,
            CustomerMemory.source_message_id == source.id,
            CustomerMemory.digest == digest,
        )
    )
    if existing:
        if existing.deleted_at or existing.expires_at <= datetime.now(UTC):
            raise AppError(
                409,
                "memory_not_restorable",
                "Forgotten or expired quotations cannot be restored from history",
            )
        return existing
    count = db.scalar(
        select(func.count())
        .select_from(CustomerMemory)
        .where(
            CustomerMemory.tenant_id == context.tenant_id,
            CustomerMemory.customer_id == cid,
            CustomerMemory.deleted_at.is_(None),
            CustomerMemory.expires_at > func.now(),
        )
    )
    if count >= 100:
        raise AppError(
            409, "customer_memory_limit", "Forget an existing quotation before adding more"
        )
    row = CustomerMemory(
        tenant_id=context.tenant_id,
        customer_id=cid,
        source_conversation_id=source.conversation_id,
        source_message_id=source.id,
        confirmed_by=context.user_id,
        content=data.content,
        digest=digest,
        expires_at=datetime.now(UTC) + timedelta(days=data.lifetime_days),
    )
    db.add(row)
    db.flush()
    record(
        db,
        request,
        "customer_memory.confirm",
        "customer_memory",
        row.id,
        tenant_id=context.tenant_id,
        details={"customer_id": str(cid), "source_message_id": str(source.id)},
    )
    return row


def forget(db, context, cid, mid, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    get_owned(db, Customer, context, cid, lock=True)
    row = get_owned(db, CustomerMemory, context, mid, lock=True)
    if row.customer_id != cid:
        raise forbidden()
    operations.check_version(row, data.expected_version)
    row.content = None
    row.deleted_at = datetime.now(UTC)
    row.version += 1
    record(
        db,
        request,
        "customer_memory.forget",
        "customer_memory",
        row.id,
        tenant_id=context.tenant_id,
        details={"customer_id": str(cid), "version": row.version},
    )
    db.flush()
    return row


def expire(db, tenant_id):
    rows = db.scalars(
        select(CustomerMemory)
        .where(
            CustomerMemory.tenant_id == tenant_id,
            CustomerMemory.deleted_at.is_(None),
            CustomerMemory.expires_at <= func.now(),
        )
        .order_by(CustomerMemory.expires_at, CustomerMemory.id)
        .limit(100)
        .with_for_update(skip_locked=True)
    ).all()
    for row in rows:
        row.content = None
        row.deleted_at = row.expires_at
        row.version += 1
    return len(rows)
