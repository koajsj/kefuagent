from datetime import UTC, datetime

from sqlalchemy import select

from support_agent.errors import AppError, forbidden
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
    if conversation.support_state != "ai" and context.role != "admin":
        raise forbidden()
    expire_active_calls(db, context, resource_id, request)
    conversation.status = data.status
    conversation.support_state = "resolved" if data.status == "closed" else "ai"
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
    if conversation.channel == "public" and (
        context.role != "admin" or conversation.support_state != "human" or data.role != "assistant"
    ):
        raise forbidden()
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


def history(db, context, conversation_id, limit, offset, request, newest=False):
    get_owned(db, Conversation, context, conversation_id)
    ordering = (
        [Message.created_at.desc(), Message.id.desc()]
        if newest
        else [Message.created_at, Message.id]
    )
    query = select(Message).where(
        Message.tenant_id == context.tenant_id, Message.conversation_id == conversation_id
    )
    if context.public_session_id is not None:
        # Paginate the public transcript, excluding intermediate model/tool protocol rows.
        query = query.where(
            (Message.role == "user")
            | (
                (Message.role == "assistant")
                & (
                    (Message.source == "manual")
                    | Message.message_metadata["final"].as_boolean().is_(True)
                )
            )
        )
    rows = list(db.scalars(query.order_by(*ordering).limit(limit).offset(offset)))
    if newest:
        rows.reverse()
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
                    if context.public_session_id is not None:
                        from support_agent.services import agent_turns, workspace

                        allowed = workspace.knowledge_ids(db, context, call.agent_config_id)
                        checked[call.id] = agent_turns.current_citations(
                            db, context, call, request, allowed
                        )
                except AppError:
                    checked[call.id] = False
            if not checked[row.model_call_id]:
                result.append(
                    MessageOut.model_validate(row).model_copy(
                        update={
                            "content": "[知识或工具结果交付权限已失效]",
                            "metadata": {"redacted": True},
                        }
                    )
                )
                continue
        result.append(row)
    return result


def set_handling(db, context, conversation_id, data, request):
    conversation = get_owned(db, Conversation, context, conversation_id, lock=True)
    if data.state != "waiting" and context.role != "admin":
        raise forbidden()
    expire_active_calls(db, context, conversation_id, request)
    if conversation.status == "closed" and data.state != "ai":
        raise AppError(409, "conversation_closed", "Reopen the conversation first")
    conversation.support_state = data.state
    conversation.status = "closed" if data.state == "resolved" else "open"
    conversation.updated_at = datetime.now(UTC)
    record(
        db,
        request,
        "conversation.handling",
        "conversation",
        conversation.id,
        tenant_id=context.tenant_id,
        details={"state": data.state},
    )
    db.flush()
    return conversation
