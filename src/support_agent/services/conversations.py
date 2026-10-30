from datetime import UTC, datetime

from sqlalchemy import select

from support_agent.errors import AppError
from support_agent.models import Conversation, Message
from support_agent.services.audit import record
from support_agent.services.chat import expire_active_calls
from support_agent.services.resources import get_owned


def create(db, context, data, request):
    conversation = Conversation(
        **data.model_dump(), tenant_id=context.tenant_id, created_by=context.user_id
    )
    db.add(conversation)
    db.flush()
    record(
        db,
        request,
        "conversation.create",
        "conversation",
        conversation.id,
        tenant_id=context.tenant_id,
    )
    return conversation


def set_status(db, context, resource_id, data, request):
    conversation = get_owned(db, Conversation, context, resource_id, lock=True)
    expire_active_calls(db, context, resource_id, request)
    conversation.status = data.status
    db.flush()
    record(
        db,
        request,
        "conversation.status",
        "conversation",
        conversation.id,
        tenant_id=context.tenant_id,
    )
    return conversation


def append_message(db, context, conversation_id, data, request):
    conversation = get_owned(db, Conversation, context, conversation_id, lock=True)
    expire_active_calls(db, context, conversation_id, request)
    if conversation.status != "open":
        raise AppError(
            409, "conversation_closed", "Closed conversations cannot receive new messages"
        )
    message = Message(
        tenant_id=context.tenant_id,
        conversation_id=conversation_id,
        created_by=context.user_id,
        role=data.role,
        content=data.content,
        message_metadata=data.metadata,
    )
    db.add(message)
    conversation.updated_at = datetime.now(UTC)
    db.flush()
    record(db, request, "message.create", "message", message.id, tenant_id=context.tenant_id)
    return message


def history(db, context, conversation_id, limit, offset, request):
    get_owned(db, Conversation, context, conversation_id)
    rows = db.scalars(
        select(Message)
        .where(Message.tenant_id == context.tenant_id, Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
        .limit(limit)
        .offset(offset)
    ).all()
    from support_agent.models import ModelCall, ToolExecution
    from support_agent.schemas import MessageOut
    from support_agent.services.tool_execution import ensure_delivery

    checked = {}
    result = []
    for row in rows:
        if row.source == "agent" and row.role != "user":
            if row.model_call_id not in checked:
                call = get_owned(db, ModelCall, context, row.model_call_id)
                executions = db.scalars(
                    select(ToolExecution).where(
                        ToolExecution.tenant_id == context.tenant_id,
                        ToolExecution.model_call_id == call.id,
                    )
                ).all()
                try:
                    ensure_delivery(db, context, call, executions, request)
                    checked[call.id] = True
                except AppError:
                    checked[call.id] = False
            if not checked[row.model_call_id]:
                result.append(
                    MessageOut.model_validate(row).model_copy(
                        update={
                            "content": "[工具结果交付权限已失效]",
                            "metadata": {"redacted": True},
                        }
                    )
                )
                continue
        result.append(row)
    return result
