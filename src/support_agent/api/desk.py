from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import or_, select

from support_agent.dependencies import Database, TenantAdmin, TenantContext
from support_agent.desk_schemas import (
    CustomerCreate,
    CustomerLink,
    CustomerMemoryConsent,
    CustomerMemoryCreate,
    CustomerMemoryForget,
    CustomerMemoryOut,
    CustomerOut,
    CustomerPatch,
    NotificationOut,
    TicketCreate,
    TicketEventOut,
    TicketOut,
    TicketPatch,
    TicketStatus,
)
from support_agent.errors import AppError
from support_agent.models import (
    AuditEvent,
    ConversationCustomer,
    Customer,
    StaffNotification,
    Ticket,
    TicketEvent,
)
from support_agent.services import customer_memory, desk
from support_agent.services.resources import get_owned

router = APIRouter(tags=["Private service desk"])


@router.get("/customers", response_model=list[CustomerOut])
def customers(
    db: Database,
    context: TenantContext,
    q: str | None = Query(None, max_length=120),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return desk.customers(db, context, limit, offset, q)


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(data: CustomerCreate, request: Request, db: Database, context: TenantContext):
    return desk.create_customer(db, context, data, request)


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def customer(customer_id: UUID, db: Database, context: TenantContext):
    return get_owned(db, Customer, context, customer_id)


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: UUID, data: CustomerPatch, request: Request, db: Database, context: TenantAdmin
):
    return desk.update_customer(db, context, customer_id, data, request)


@router.get("/customers/{customer_id}/conversations")
def customer_conversations(
    customer_id: UUID,
    db: Database,
    context: TenantContext,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    get_owned(db, Customer, context, customer_id)
    rows = db.scalars(
        select(ConversationCustomer)
        .where(
            ConversationCustomer.tenant_id == context.tenant_id,
            ConversationCustomer.customer_id == customer_id,
        )
        .order_by(ConversationCustomer.created_at.desc(), ConversationCustomer.id)
        .limit(limit)
        .offset(offset)
    )
    return [
        {
            "conversation_id": row.conversation_id,
            "linked_at": row.created_at,
            "identity_method": "staff_confirmed",
        }
        for row in rows
    ]


@router.get("/customers/{customer_id}/activity")
def customer_activity(
    customer_id: UUID,
    db: Database,
    context: TenantContext,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    get_owned(db, Customer, context, customer_id)
    related_ticket = (
        select(Ticket.id)
        .where(
            Ticket.tenant_id == context.tenant_id,
            Ticket.customer_id == customer_id,
            Ticket.id == AuditEvent.resource_id,
        )
        .exists()
    )
    rows = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == context.tenant_id,
            or_(
                (AuditEvent.resource_type == "customer") & (AuditEvent.resource_id == customer_id),
                AuditEvent.action.in_(
                    [
                        "customer_memory.confirm",
                        "customer_memory.forget",
                        "conversation.customer_link",
                    ]
                )
                & (AuditEvent.details["customer_id"].as_string() == str(customer_id)),
                (AuditEvent.resource_type == "ticket") & related_ticket,
            ),
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        .limit(limit)
        .offset(offset)
    ).all()
    # Metadata only. No arbitrary audit payload, contact details, notes or message contents.
    return [
        {
            "id": row.id,
            "action": row.action,
            "actor_id": row.actor_id,
            "resource_id": row.resource_id,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/customers/{customer_id}/export")
def export_customer(customer_id: UUID, db: Database, context: TenantAdmin):
    row = get_owned(db, Customer, context, customer_id)
    return {
        "profile": CustomerOut.model_validate(row),
        "scope": "profile_only",
        "complete_export": False,
        "excluded": ["messages", "tickets", "audit", "backups", "provider_copies"],
    }


@router.delete("/customers/{customer_id}", status_code=204)
def delete_customer(customer_id: UUID, db: Database, context: TenantAdmin):
    get_owned(db, Customer, context, customer_id)
    raise AppError(
        409,
        "customer_erasure_blocked",
        "Customer erasure requires a complete reviewed conversation, memory, JSON and retention impact plan; no data deleted",
    )


@router.get("/conversations/{conversation_id}/customer", response_model=CustomerOut | None)
def conversation_customer(conversation_id: UUID, db: Database, context: TenantContext):
    return desk.conversation_customer(db, context, conversation_id)


@router.get("/customers/{customer_id}/memories", response_model=list[CustomerMemoryOut])
def memories(
    customer_id: UUID,
    db: Database,
    context: TenantContext,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return customer_memory.listing(db, context, customer_id, limit, offset)


@router.put("/customers/{customer_id}/memory-consent", response_model=CustomerOut)
def memory_consent(
    customer_id: UUID,
    data: CustomerMemoryConsent,
    request: Request,
    db: Database,
    context: TenantAdmin,
):
    return customer_memory.consent(db, context, customer_id, data, request)


@router.post("/customers/{customer_id}/memories", response_model=CustomerMemoryOut, status_code=201)
def create_memory(
    customer_id: UUID,
    data: CustomerMemoryCreate,
    request: Request,
    db: Database,
    context: TenantAdmin,
):
    return customer_memory.create(db, context, customer_id, data, request)


@router.post(
    "/customers/{customer_id}/memories/{memory_id}/forget", response_model=CustomerMemoryOut
)
def forget_memory(
    customer_id: UUID,
    memory_id: UUID,
    data: CustomerMemoryForget,
    request: Request,
    db: Database,
    context: TenantAdmin,
):
    return customer_memory.forget(db, context, customer_id, memory_id, data, request)


@router.put("/conversations/{conversation_id}/customer")
def link_customer(
    conversation_id: UUID,
    data: CustomerLink,
    request: Request,
    db: Database,
    context: TenantContext,
):
    return desk.link_customer(db, context, conversation_id, data, request)


@router.get("/tickets", response_model=list[TicketOut])
def tickets(
    db: Database,
    context: TenantContext,
    status: TicketStatus | None = None,
    customer_id: UUID | None = None,
    conversation_id: UUID | None = None,
    overdue: bool = False,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return desk.tickets(
        db,
        context,
        limit,
        offset,
        status=status,
        customer_id=customer_id,
        conversation_id=conversation_id,
        overdue=overdue,
    )


@router.post("/tickets", response_model=TicketOut, status_code=201)
def create_ticket(data: TicketCreate, request: Request, db: Database, context: TenantContext):
    return desk.create_ticket(db, context, data, request)


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
def ticket(ticket_id: UUID, db: Database, context: TenantContext):
    return get_owned(db, Ticket, context, ticket_id)


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
def update_ticket(
    ticket_id: UUID, data: TicketPatch, request: Request, db: Database, context: TenantContext
):
    return desk.update_ticket(db, context, ticket_id, data, request)


@router.get("/tickets/{ticket_id}/events", response_model=list[TicketEventOut])
def ticket_events(
    ticket_id: UUID,
    db: Database,
    context: TenantContext,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    get_owned(db, Ticket, context, ticket_id)
    return db.scalars(
        select(TicketEvent)
        .where(TicketEvent.tenant_id == context.tenant_id, TicketEvent.ticket_id == ticket_id)
        .order_by(TicketEvent.created_at.desc(), TicketEvent.id)
        .limit(limit)
        .offset(offset)
    ).all()


@router.get("/staff-notifications", response_model=list[NotificationOut])
def notifications(
    db: Database,
    context: TenantContext,
    unread: bool = False,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(StaffNotification).where(
        StaffNotification.tenant_id == context.tenant_id,
        StaffNotification.user_id == context.user_id,
    )
    if unread:
        query = query.where(StaffNotification.read_at.is_(None))
    return db.scalars(
        query.order_by(StaffNotification.created_at.desc(), StaffNotification.id)
        .limit(limit)
        .offset(offset)
    ).all()


@router.post("/staff-notifications/{notification_id}/read", response_model=NotificationOut)
def read_notification(notification_id: UUID, db: Database, context: TenantContext):
    from datetime import UTC, datetime

    from support_agent.errors import missing

    row = db.scalar(
        select(StaffNotification)
        .where(
            StaffNotification.id == notification_id,
            StaffNotification.tenant_id == context.tenant_id,
            StaffNotification.user_id == context.user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise missing()
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
    db.flush()
    return row


@router.get("/autonomy-policy")
def autonomy_policy(context: TenantContext):
    from support_agent.autonomy import POLICY_VERSION, RISK_NAMES

    return {
        "version": POLICY_VERSION,
        "levels": [{"risk": key, "name": value} for key, value in RISK_NAMES.items()],
        "default_max_risk": 1,
        "maximum_configurable_risk": 2,
        "r3_execution": "fixed_transactional_commands_with_independent_approval",
        "authority": "deployment_capability_and_server_grants",
        "model_can_grant": False,
        "limits": {"model_steps": 5, "tool_calls": 4, "seconds": 120},
        "monetary_budget_enforcement": "BLOCKED_until_pricing_and_atomic_reservations",
    }


@router.get("/conversations/{conversation_id}/handoff")
def handoff_packet(conversation_id: UUID, request: Request, db: Database, context: TenantContext):
    from support_agent.services.handoff import packet

    return packet(db, context, conversation_id, request)
