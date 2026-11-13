"""Tenant-scoped CRM and tickets; all mutations are staff commands, never raw model SQL."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from support_agent.dependencies import locked_staff_context
from support_agent.errors import AppError, forbidden
from support_agent.maintenance import confirmation
from support_agent.models import (
    Conversation,
    ConversationCustomer,
    Customer,
    Membership,
    StaffNotification,
    Ticket,
    TicketEvent,
    User,
)
from support_agent.services import operations
from support_agent.services.audit import record
from support_agent.services.resources import get_owned

TRANSITIONS = {
    "open": {"in_progress", "resolved", "closed"},
    "in_progress": {"open", "resolved", "closed"},
    "resolved": {"open", "in_progress", "closed"},
    "closed": {"open"},
}


def staff(context):
    if context.public_session_id is not None or context.user_id is None:
        raise forbidden()


def customers(db, context, limit, offset, q=None):
    staff(context)
    query = select(Customer).where(Customer.tenant_id == context.tenant_id)
    if q:
        query = query.where(Customer.name.icontains(q, autoescape=True))
    return db.scalars(
        query.order_by(Customer.updated_at.desc(), Customer.id).limit(limit).offset(offset)
    ).all()


def create_customer(db, context, data, request):
    context = locked_staff_context(db, context, request)
    staff(context)
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"customer:{context.tenant_id}:{data.idempotency_key}"},
    )
    digest = confirmation(data.model_dump(mode="json", exclude={"idempotency_key"}))
    existing = db.scalar(
        select(Customer).where(
            Customer.tenant_id == context.tenant_id,
            Customer.idempotency_key == data.idempotency_key,
        )
    )
    if existing:
        if existing.input_digest != digest or existing.created_by != context.user_id:
            raise AppError(
                409, "idempotency_conflict", "Customer key already has different owner or input"
            )
        return existing
    row = Customer(
        tenant_id=context.tenant_id,
        created_by=context.user_id,
        input_digest=digest,
        **data.model_dump(),
    )
    db.add(row)
    db.flush()
    record(db, request, "customer.create", "customer", row.id, tenant_id=context.tenant_id)
    return row


def update_customer(db, context, cid, data, request):
    context = locked_staff_context(db, context, request)
    staff(context)
    if context.role != "admin":
        raise forbidden()
    row = get_owned(db, Customer, context, cid, lock=True)
    operations.check_version(row, data.expected_version)
    fields = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    for key, value in fields.items():
        setattr(row, key, value)
    row.version += 1
    db.flush()
    record(
        db,
        request,
        "customer.update",
        "customer",
        row.id,
        tenant_id=context.tenant_id,
        details={"version": row.version, "changed_fields": sorted(fields)},
    )
    return row


def link_customer(db, context, conversation_id, data, request):
    context = locked_staff_context(db, context, request)
    staff(context)
    row = get_owned(db, Conversation, context, conversation_id, lock=True)
    operations.controlled(db, context, row)
    operations.check_version(row, data.expected_version)
    customer = get_owned(db, Customer, context, data.customer_id, lock=True)
    if customer.status != "active":
        raise AppError(409, "customer_archived", "Archived customers cannot receive new links")
    link = db.scalar(
        select(ConversationCustomer)
        .where(
            ConversationCustomer.tenant_id == context.tenant_id,
            ConversationCustomer.conversation_id == conversation_id,
        )
        .with_for_update()
    )
    if link and link.customer_id != customer.id:
        raise AppError(
            409,
            "customer_link_conflict",
            "Existing customer identity requires a separate reviewed correction",
        )
    conflict = db.scalar(
        select(Ticket.id)
        .where(
            Ticket.tenant_id == context.tenant_id,
            Ticket.conversation_id == conversation_id,
            Ticket.customer_id.is_not(None),
            Ticket.customer_id != customer.id,
        )
        .limit(1)
    )
    if conflict:
        raise AppError(
            409,
            "customer_link_conflict",
            "An existing ticket has a different customer; review identity before linking",
        )
    if not link:
        link = ConversationCustomer(
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            customer_id=customer.id,
            created_by=context.user_id,
        )
        db.add(link)
        row.version += 1
        record(
            db,
            request,
            "conversation.customer_link",
            "conversation",
            row.id,
            tenant_id=context.tenant_id,
            details={"customer_id": str(customer.id), "method": "staff_confirmed"},
        )
        db.flush()
    return {
        "customer_id": customer.id,
        "conversation_id": row.id,
        "conversation_version": row.version,
        "identity_method": "staff_confirmed",
        "visitor_identity_verified": False,
    }


def conversation_customer(db, context, cid):
    staff(context)
    get_owned(db, Conversation, context, cid)
    return db.scalar(
        select(Customer)
        .join(
            ConversationCustomer,
            (ConversationCustomer.tenant_id == Customer.tenant_id)
            & (ConversationCustomer.customer_id == Customer.id),
        )
        .where(
            ConversationCustomer.tenant_id == context.tenant_id,
            ConversationCustomer.conversation_id == cid,
        )
    )


def ticket_event(db, context, ticket, action, details):
    db.add(
        TicketEvent(
            tenant_id=context.tenant_id,
            ticket_id=ticket.id,
            actor_id=context.user_id,
            action=action,
            details=details,
        )
    )


def create_ticket(db, context, data, request):
    context = locked_staff_context(db, context, request)
    staff(context)
    if data.conversation_id:
        conversation = get_owned(db, Conversation, context, data.conversation_id, lock=True)
        operations.controlled(db, context, conversation)
    # Serialize a client key before reading it; no duplicate mutation on concurrent replay.
    key = f"ticket:{context.tenant_id}:{data.idempotency_key}"
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
    digest = confirmation(data.model_dump(mode="json", exclude={"idempotency_key"}))
    existing = db.scalar(
        select(Ticket).where(
            Ticket.tenant_id == context.tenant_id, Ticket.idempotency_key == data.idempotency_key
        )
    )
    if existing:
        if existing.input_digest != digest or existing.created_by != context.user_id:
            raise AppError(
                409, "idempotency_conflict", "Ticket key already has different owner or input"
            )
        return existing
    fields = data.model_dump(exclude={"idempotency_key"})
    if data.conversation_id:
        linked = conversation_customer(db, context, data.conversation_id)
        if linked and data.customer_id and linked.id != data.customer_id:
            raise AppError(
                409,
                "customer_link_conflict",
                "Ticket customer differs from the confirmed conversation link",
            )
        fields["customer_id"] = linked.id if linked else data.customer_id
    if fields["customer_id"]:
        customer = get_owned(db, Customer, context, fields["customer_id"], lock=True)
        if customer.status != "active":
            raise AppError(409, "customer_archived", "Customer is archived")
    if data.assignee_id:
        operations.operator(db, context, data.assignee_id)
        if context.role != "admin" and data.assignee_id != context.user_id:
            raise forbidden()
    row = Ticket(
        tenant_id=context.tenant_id,
        created_by=context.user_id,
        idempotency_key=data.idempotency_key,
        input_digest=digest,
        **fields,
    )
    db.add(row)
    db.flush()
    ticket_event(
        db,
        context,
        row,
        "created",
        {
            "status": row.status,
            "version": row.version,
            "priority": row.priority,
            "assignee_id": str(row.assignee_id) if row.assignee_id else None,
            "customer_id": str(row.customer_id) if row.customer_id else None,
            "conversation_id": str(row.conversation_id) if row.conversation_id else None,
            "due_at": row.due_at.isoformat() if row.due_at else None,
        },
    )
    record(db, request, "ticket.create", "ticket", row.id, tenant_id=context.tenant_id)
    return row


def update_ticket(db, context, tid, data, request):
    context = locked_staff_context(db, context, request)
    staff(context)
    row = get_owned(db, Ticket, context, tid, lock=True)
    if context.role != "admin" and row.assignee_id != context.user_id:
        raise forbidden()
    operations.check_version(row, data.expected_version)
    fields = data.model_dump(exclude_unset=True, exclude={"expected_version", "note"})
    if "assignee_id" in fields:
        if context.role != "admin":
            raise forbidden()
        if fields["assignee_id"]:
            operations.operator(db, context, fields["assignee_id"])
    target = fields.get("status", row.status)
    if target != row.status and target not in TRANSITIONS[row.status]:
        raise AppError(409, "ticket_transition_invalid", "This ticket transition is not allowed")
    changed = {key: value for key, value in fields.items() if value != getattr(row, key)}
    if changed or data.note:
        previous = {key: getattr(row, key) for key in changed}
        if target != row.status:
            row.resolved_at = datetime.now(UTC) if target in {"resolved", "closed"} else None
        for key, value in changed.items():
            setattr(row, key, value)
        row.version += 1
        ticket_event(
            db,
            context,
            row,
            "updated",
            {
                "changed_fields": sorted(changed),
                "changes": {
                    key: {
                        "before": str(previous[key]) if previous[key] is not None else None,
                        "after": str(changed[key]) if changed[key] is not None else None,
                    }
                    for key in changed
                },
                "status": row.status,
                "version": row.version,
                "note": data.note,
            },
        )
        record(
            db,
            request,
            "ticket.update",
            "ticket",
            row.id,
            tenant_id=context.tenant_id,
            details={"changed_fields": sorted(changed), "version": row.version},
        )
        db.flush()
    return row


def tickets(
    db,
    context,
    limit,
    offset,
    *,
    status=None,
    customer_id=None,
    conversation_id=None,
    overdue=False,
):
    staff(context)
    query = select(Ticket).where(Ticket.tenant_id == context.tenant_id)
    if status:
        query = query.where(Ticket.status == status)
    if customer_id:
        get_owned(db, Customer, context, customer_id)
        query = query.where(Ticket.customer_id == customer_id)
    if conversation_id:
        get_owned(db, Conversation, context, conversation_id)
        query = query.where(Ticket.conversation_id == conversation_id)
    if overdue:
        query = query.where(Ticket.status.in_(["open", "in_progress"]), Ticket.due_at < func.now())
    return db.scalars(
        query.order_by(Ticket.updated_at.desc(), Ticket.id).limit(limit).offset(offset)
    ).all()


def notify_overdue(db, tenant_id):
    """Bounded worker transaction. In-app notifications only, never claim external delivery."""
    notified = (
        select(StaffNotification.id)
        .where(
            StaffNotification.tenant_id == tenant_id,
            StaffNotification.ticket_id == Ticket.id,
            StaffNotification.ticket_version == Ticket.version,
            StaffNotification.user_id == Membership.user_id,
            StaffNotification.kind == "ticket_overdue",
        )
        .correlate(Ticket, Membership)
        .exists()
    )
    eligible_recipient = (
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
            User.status == "active",
            ~notified,
            or_(
                Membership.user_id == Ticket.assignee_id,
                and_(Ticket.assignee_id.is_(None), Membership.role == "admin"),
            ),
        )
        .correlate(Ticket)
        .exists()
    )
    rows = db.scalars(
        select(Ticket)
        .where(
            eligible_recipient,
            Ticket.tenant_id == tenant_id,
            Ticket.status.in_(["open", "in_progress"]),
            Ticket.due_at < func.now(),
        )
        .order_by(Ticket.due_at, Ticket.id)
        .limit(100)
        .with_for_update(skip_locked=True)
    ).all()
    for ticket in rows:
        users = (
            select(Membership.user_id)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.status == "active",
                User.status == "active",
            )
        )
        users = (
            users.where(Membership.user_id == ticket.assignee_id)
            if ticket.assignee_id
            else users.where(Membership.role == "admin")
        )
        recipients = list(db.scalars(users))
        if not recipients:
            continue
        for uid in recipients:
            db.execute(
                insert(StaffNotification)
                .values(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    user_id=uid,
                    ticket_id=ticket.id,
                    ticket_version=ticket.version,
                    kind="ticket_overdue",
                )
                .on_conflict_do_nothing()
            )
    return len(rows)
