"""Fixed service commands. No addresses, SQL, handler paths or scope come from the model."""

from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.dialects.postgresql import insert

from support_agent.desk_schemas import TicketCreate, TicketPatch
from support_agent.errors import AppError, forbidden
from support_agent.maintenance import confirmation
from support_agent.models import Conversation, StaffNotification, Ticket
from support_agent.services import desk, operations
from support_agent.services.resources import get_owned

READ_KEYS = frozenset({"customer_lookup", "ticket_lookup"})
COMMAND_KEYS = frozenset({"ticket_create", "ticket_update", "human_handoff", "notification"})
ALL_KEYS = READ_KEYS | COMMAND_KEYS


def ticket_view(row):
    return {
        "id": str(row.id),
        "title": row.title,
        "status": row.status,
        "priority": row.priority,
        "version": row.version,
    }


def lookup(db, context, call, key, arguments):
    desk.staff(context)
    if key == "customer_lookup":
        row = desk.conversation_customer(db, context, call.conversation_id)
        return {
            "found": row is not None,
            "customer_id": str(row.id) if row else "",
            "name": row.name if row else "",
            "version": row.version if row else 0,
        }
    rows = desk.tickets(db, context, 5, 0, conversation_id=call.conversation_id)
    return {"tickets": [ticket_view(row) for row in rows]}


def still_current(db, context, call, key, result):
    if context.public_session_id is not None:
        return False
    if key in READ_KEYS:
        return lookup(db, context, call, key, {}) == result
    if key in {"ticket_create", "ticket_update", "notification"}:
        row = get_owned(db, Ticket, context, UUID(result["ticket_id"]), lock=True)
        return (
            row.conversation_id == call.conversation_id and row.version == result["ticket_version"]
        )
    if key == "human_handoff":
        row = get_owned(db, Conversation, context, call.conversation_id, lock=True)
        return row.support_state in {"waiting", "human"}
    return False


def execute(db, context, call, execution, key, arguments, request):
    desk.staff(context)
    conversation = get_owned(db, Conversation, context, call.conversation_id, lock=True)
    operations.controlled(db, context, conversation)
    if key == "ticket_create":
        row = desk.create_ticket(
            db,
            context,
            TicketCreate(
                idempotency_key=uuid5(
                    NAMESPACE_URL, f"desk-tool:{call.id}:{confirmation(arguments)}"
                ),
                title=arguments["title"],
                description=arguments["description"],
                conversation_id=conversation.id,
                assignee_id=context.user_id,
            ),
            request,
        )
    elif key in {"ticket_update", "notification"}:
        row = get_owned(db, Ticket, context, UUID(arguments["ticket_id"]), lock=True)
        if row.conversation_id != conversation.id:
            raise forbidden()
        if key == "ticket_update":
            row = desk.update_ticket(
                db,
                context,
                row.id,
                TicketPatch(
                    expected_version=arguments["expected_version"],
                    status=arguments["status"],
                    note=arguments["note"],
                ),
                request,
            )
        else:
            # Notification targets only the ticket's active assigned member, never a model address.
            if row.assignee_id is None:
                raise AppError(
                    409, "notification_recipient_unavailable", "Assign the ticket before notifying"
                )
            operations.operator(db, context, row.assignee_id)
            db.execute(
                insert(StaffNotification)
                .values(
                    id=uuid5(NAMESPACE_URL, f"notification:{execution.id}"),
                    tenant_id=context.tenant_id,
                    ticket_id=row.id,
                    ticket_version=row.version,
                    user_id=row.assignee_id,
                    kind="agent_notification",
                )
                .on_conflict_do_nothing()
            )
    elif key == "human_handoff":
        if conversation.support_state == "ai":
            from datetime import UTC, datetime

            conversation.support_state = "waiting"
            conversation.waiting_since = datetime.now(UTC)
            conversation.version += 1
            operations.log(
                db,
                context,
                conversation,
                request,
                "handling",
                {
                    "state": "waiting",
                    "reason": arguments["reason"],
                    "model_call_id": str(call.id),
                    "source": "authorized_agent_command",
                },
            )
        return {"support_state": conversation.support_state, "reason": arguments["reason"]}
    else:
        raise ValueError("Unknown service command")
    return {"ticket_id": str(row.id), "ticket_version": row.version, "status": row.status}
