from datetime import UTC, datetime
from uuid import uuid5

from sqlalchemy import func, select, text, tuple_

from support_agent.dependencies import locked_staff_context, resume_context
from support_agent.errors import AppError, forbidden
from support_agent.maintenance import confirmation
from support_agent.models import Conversation, Message
from support_agent.services import operations
from support_agent.services.audit import record
from support_agent.services.chat import expire_active_calls
from support_agent.services.resources import get_owned


def create(db, context, data, request):
    context = locked_staff_context(db, context, request)
    # Authorization gates precede command locks, held through creation and audit commit.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {
            "key": f"conversation-create:{context.tenant_id}:{context.user_id}:{data.idempotency_key}"
        },
    )
    # Authorization gates block revocation, but cannot stop a Session expiring while we wait.
    context = resume_context(db, context, request)
    fields = data.model_dump(exclude={"idempotency_key"})
    digest = confirmation({"version": 1, **fields})
    existing = db.scalar(
        select(Conversation).where(
            Conversation.tenant_id == context.tenant_id,
            Conversation.created_by == context.user_id,
            Conversation.idempotency_key == data.idempotency_key,
        )
    )
    if existing is not None:
        if existing.input_digest != digest:
            raise AppError(409, "idempotency_conflict", "Conversation key has different input")
        # Return current state; never restore creation-time status, title or assignment.
        record(
            db,
            request,
            "conversation.create_replay",
            "conversation",
            existing.id,
            tenant_id=context.tenant_id,
        )
        return existing
    conversation = Conversation(
        **fields,
        tenant_id=context.tenant_id,
        created_by=context.user_id,
        idempotency_key=data.idempotency_key,
        input_digest=digest,
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
    context = locked_staff_context(db, context, request, admin=True)
    conversation = get_owned(db, Conversation, context, resource_id, lock=True)
    if context.role != "admin":
        raise forbidden()
    expire_active_calls(db, context, resource_id, request)
    conversation.status = data.status
    conversation.support_state = "resolved" if data.status == "closed" else "ai"
    conversation.resolved_at = datetime.now(UTC) if data.status == "closed" else None
    conversation.version += 1
    operations.log(
        db,
        context,
        conversation,
        request,
        "handling",
        {"state": conversation.support_state, "explicit_reopen": data.status == "open"},
    )
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
    context = locked_staff_context(db, context, request)
    conversation = get_owned(db, Conversation, context, conversation_id, lock=True)
    message_id = uuid5(conversation_id, f"staff-message:{context.user_id}:{data.idempotency_key}")
    existing = db.scalar(
        select(Message).where(Message.tenant_id == context.tenant_id, Message.id == message_id)
    )
    if existing is not None:
        if (
            existing.conversation_id != conversation_id
            or existing.created_by != context.user_id
            or existing.source != "manual"
            or existing.role != data.role
            or existing.content != data.content
            or existing.message_metadata != data.metadata
        ):
            raise AppError(409, "idempotency_conflict", "Message key already has different input")
        return existing
    if conversation.status != "open":
        raise AppError(
            409, "conversation_closed", "Closed conversations cannot receive new messages"
        )
    if data.role == "assistant" and (
        context.role != "admin" or conversation.support_state == "human"
    ):
        operations.controlled(db, context, conversation)
        if conversation.support_state != "human":
            raise forbidden()
    if conversation.channel == "public":
        if conversation.support_state != "human" or data.role != "assistant":
            raise forbidden()
        operations.controlled(db, context, conversation)
        operations.public_reply_guard(db, context, conversation, request)
    expire_active_calls(db, context, conversation_id, request)
    message = Message(
        id=message_id,
        tenant_id=context.tenant_id,
        conversation_id=conversation_id,
        created_by=context.user_id,
        role=data.role,
        content=data.content,
        # The transaction may have started before waiting for the conversation lock.
        created_at=func.clock_timestamp(),
        message_metadata=data.metadata,
    )
    db.add(message)
    if data.role == "assistant" and conversation.first_response_at is None:
        conversation.first_response_at = datetime.now(UTC)
    conversation.updated_at = datetime.now(UTC)
    db.flush()
    record(db, request, "message.create", "message", message.id, tenant_id=context.tenant_id)
    return message


def history(
    db,
    context,
    conversation_id,
    limit,
    offset,
    request,
    newest=False,
    *,
    after=None,
    before=None,
    at=None,
):
    get_owned(db, Conversation, context, conversation_id)
    if after and before:
        raise AppError(422, "invalid_cursor", "Use either after or before, not both")
    descending = bool(before) or (newest and not after)
    ordering = (
        [Message.created_at.desc(), Message.id.desc()]
        if descending
        else [Message.created_at, Message.id]
    )
    query = select(Message).where(
        Message.tenant_id == context.tenant_id, Message.conversation_id == conversation_id
    )
    if at is not None:
        query = query.where(Message.id == at)
    if after or before:
        anchor = get_owned(db, Message, context, after or before)
        if anchor.conversation_id != conversation_id:
            from support_agent.errors import missing

            raise missing()
        position = tuple_(Message.created_at, Message.id)
        boundary = tuple_(anchor.created_at, anchor.id)
        query = query.where(position > boundary if after else position < boundary)
        offset = 0
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
    if descending:
        rows.reverse()
    from support_agent.models import ModelCall, ReplyDraft, ToolExecution
    from support_agent.schemas import MessageOut
    from support_agent.services.tool_execution import ensure_delivery

    # Batch associations for this page; permission/source checks below remain per call.
    drafts = {
        draft.sent_message_id: draft
        for draft in db.scalars(
            select(ReplyDraft).where(
                ReplyDraft.tenant_id == context.tenant_id,
                ReplyDraft.conversation_id == conversation_id,
                ReplyDraft.sent_message_id.in_([row.id for row in rows]),
                ReplyDraft.status == "ACCEPTED",
            )
        )
    }
    call_ids = {
        row.model_call_id for row in rows if row.source in {"agent", "rag"} and row.role != "user"
    } | {draft.model_call_id for draft in drafts.values() if draft.model_call_id}
    calls = (
        {
            call.id: call
            for call in db.scalars(
                select(ModelCall).where(
                    ModelCall.tenant_id == context.tenant_id, ModelCall.id.in_(call_ids)
                )
            )
        }
        if call_ids
        else {}
    )
    executions_by_call = {}
    if call_ids:
        for execution in db.scalars(
            select(ToolExecution).where(
                ToolExecution.tenant_id == context.tenant_id,
                ToolExecution.model_call_id.in_(call_ids),
            )
        ):
            executions_by_call.setdefault(execution.model_call_id, []).append(execution)
    checked = {}
    result = []
    for row in rows:
        call_id = drafts[row.id].model_call_id if row.id in drafts else row.model_call_id
        if row.role != "user" and (row.source in {"agent", "rag"} or row.id in drafts):
            if call_id not in checked:
                call = calls.get(call_id)
                if call is None:
                    from support_agent.errors import missing

                    raise missing()
                executions = executions_by_call.get(call.id, [])
                try:
                    ensure_delivery(db, context, call, executions, request)
                    checked[call.id] = True
                    from support_agent.services import agent_turns, workspace

                    allowed = workspace.knowledge_ids(db, context, call.agent_config_id)
                    checked[call.id] = agent_turns.current_citations(
                        db, context, call, request, allowed
                    )
                except AppError:
                    checked[call.id] = False
            if not checked[call_id]:
                result.append(
                    MessageOut.model_validate(row).model_copy(
                        update={
                            "content": "[知识或工具结果交付权限已失效]",
                            "metadata": {"redacted": True},
                        }
                    )
                )
                continue
        if row.id in drafts:
            # Also mark suggestions accepted before the provenance metadata existed.
            result.append(
                MessageOut.model_validate(row).model_copy(
                    update={
                        "metadata": row.message_metadata
                        | {"reply_draft_id": str(drafts[row.id].id)}
                    }
                )
            )
            continue
        result.append(row)
    return result


def set_handling(db, context, conversation_id, data, request):
    context = locked_staff_context(db, context, request)
    row = get_owned(db, Conversation, context, conversation_id, lock=True)
    operations.check_version(row, data.expected_version)
    if row.status == "closed":
        raise AppError(409, "conversation_closed", "Use the explicit reopen action first")
    state = data.state
    if state == "human":
        if row.assignee_id not in {None, context.user_id}:
            raise AppError(409, "already_assigned", "Transfer the assigned conversation explicitly")
        if context.role != "admin" and row.support_state not in {"waiting", "human"}:
            raise forbidden()
    elif state == "waiting":
        if row.support_state == "human":
            operations.controlled(db, context, row)
    elif context.role != "admin":
        operations.controlled(db, context, row)
        if row.support_state != "human":
            raise forbidden()
    expire_active_calls(db, context, conversation_id, request)
    if row.support_state == state:
        return row
    previous = row.support_state
    now = datetime.now(UTC)
    if state == "waiting":
        row.waiting_since = now
        row.human_started_at = None
    if state == "human":
        operations.operator(db, context, context.user_id)
        row.assignee_id = context.user_id
        row.human_started_at = now
        row.ever_human = True
    row.support_state = state
    row.status = "closed" if state == "resolved" else "open"
    row.resolved_at = now if state == "resolved" else None
    row.updated_at = now
    row.version += 1
    operations.log(
        db,
        context,
        row,
        request,
        "handling",
        {
            "previous": previous,
            "state": state,
            "version": row.version,
            "assignee": str(row.assignee_id) if row.assignee_id else None,
        },
    )
    db.flush()
    return row
