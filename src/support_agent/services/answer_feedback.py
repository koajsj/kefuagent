"""Human answer reviews stored as typed collaboration notes; never training or memory."""

from uuid import UUID, uuid5

from sqlalchemy import select

from support_agent.dependencies import locked_staff_context
from support_agent.errors import AppError, forbidden, missing
from support_agent.models import AgentConfig, Collaboration, Conversation, Message, ModelCall
from support_agent.services import conversations, operations
from support_agent.services.audit import record
from support_agent.services.resources import get_owned

KIND = "answer_feedback_v1"


def _view(row):
    details = row.details
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "message_id": details["message_id"],
        "call_id": details["call_id"],
        "question_message_id": details.get("question_message_id"),
        "revision": details.get("revision", 0),
        "category": details["category"],
        "status": details["status"],
        "comment": row.content,
        "citation_chunk_ids": details["citation_chunk_ids"],
        "resolution_category": details.get("resolution_category"),
        "resolution_note": details.get("resolution_note", ""),
        "related_chunk_ids": details.get("related_chunk_ids", []),
        "related_sources": details.get("related_sources", []),
        "created_at": row.created_at,
    }


def _answer(db, context, cid, call_id, request):
    call = get_owned(db, ModelCall, context, call_id)
    if call.conversation_id != cid:
        raise missing()
    row = db.scalar(
        select(Message)
        .where(
            Message.tenant_id == context.tenant_id,
            Message.conversation_id == cid,
            Message.model_call_id == call_id,
            Message.role == "assistant",
            (Message.source == "rag") | Message.message_metadata["final"].as_boolean().is_(True),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
    )
    if row is None:
        raise AppError(409, "answer_unavailable", "Only a persisted final answer can be reviewed")
    # Reuse transcript source/tool/memory delivery checks, not just citation presence.
    visible = conversations.history(db, context, cid, 1, 0, request, at=row.id)[0]
    metadata = visible.message_metadata if isinstance(visible, Message) else visible.metadata
    if metadata.get("redacted"):
        raise AppError(409, "answer_unavailable", "Answer delivery permissions have changed")
    return row


def _question_id(db, context, cid, call_id):
    rows = list(
        db.scalars(
            select(Message.id)
            .where(
                Message.tenant_id == context.tenant_id,
                Message.conversation_id == cid,
                Message.model_call_id == call_id,
                Message.role == "user",
                Message.source.in_(["rag", "agent"]),
            )
            .limit(2)
        )
    )
    # Do not guess a question from temporal proximity or an internal note.
    return str(rows[0]) if len(rows) == 1 else None


def _sources(db, context, cid, call_id, chunk_ids, request, original_citations):
    if not chunk_ids:
        return []
    call = get_owned(db, ModelCall, context, call_id)
    if call.conversation_id != cid:
        raise missing()
    from support_agent.services import workspace

    get_owned(db, AgentConfig, context, call.agent_config_id, lock=True)
    allowed = set(workspace.knowledge_ids(db, context, call.agent_config_id))
    rows = request.app.state.retriever.current_chunks(db, context, chunk_ids, lock=True)
    if any(
        chunk_id not in rows
        or (chunk_id not in original_citations and not rows[chunk_id][0].is_current)
        or (context.role != "admin" and rows[chunk_id][1].knowledge_base_id not in allowed)
        for chunk_id in chunk_ids
    ):
        raise AppError(
            409, "feedback_source_unavailable", "Knowledge sources are unavailable or unauthorized"
        )
    return [
        {
            "chunk_id": str(chunk_id),
            "document_id": str(rows[chunk_id][1].id),
            "knowledge_base_id": str(rows[chunk_id][1].knowledge_base_id),
        }
        for chunk_id in chunk_ids
    ]


def listing(
    db,
    context,
    cid,
    request,
    *,
    call_id=None,
    status=None,
    category=None,
    limit=30,
    before=None,
    mine=False,
):
    get_owned(db, Conversation, context, cid)
    query = select(Collaboration).where(
        Collaboration.tenant_id == context.tenant_id,
        Collaboration.conversation_id == cid,
        Collaboration.details["type"].astext == KIND,
    )
    if call_id:
        query = query.where(Collaboration.details["call_id"].astext == str(call_id))
    if status:
        query = query.where(Collaboration.details["status"].astext == status)
    if category:
        query = query.where(Collaboration.details["category"].astext == category)
    if mine:
        query = query.where(Collaboration.actor_id == context.user_id)
    if before:
        from sqlalchemy import tuple_

        anchor = get_owned(db, Collaboration, context, before)
        if anchor.conversation_id != cid or anchor.details.get("type") != KIND:
            raise missing()
        query = query.where(
            tuple_(Collaboration.created_at, Collaboration.id)
            < tuple_(anchor.created_at, anchor.id)
        )
    # Review comments are internal collaboration notes. Return only server-stored
    # IDs, never resurrect the original answer or citation text after revocation.
    return [
        _view(row)
        for row in db.scalars(
            query.order_by(Collaboration.created_at.desc(), Collaboration.id.desc()).limit(limit)
        )
    ]


def create(db, context, cid, data, request):
    context = locked_staff_context(db, context, request)
    if context.public_session_id is not None:
        raise forbidden()
    get_owned(db, Conversation, context, cid, lock=True)
    answer = _answer(db, context, cid, data.call_id, request)
    identity = uuid5(cid, f"answer-review:{context.user_id}:{answer.id}")
    previous = db.scalar(
        select(Collaboration).where(
            Collaboration.tenant_id == context.tenant_id, Collaboration.id == identity
        )
    )
    if previous:
        if previous.content != data.comment or previous.details.get("category") != data.category:
            raise AppError(409, "feedback_exists", "This answer already has your review")
        return _view(previous)
    row = Collaboration(
        id=identity,
        tenant_id=context.tenant_id,
        conversation_id=cid,
        actor_id=context.user_id,
        kind="note",
        content=data.comment,
        details={
            "type": KIND,
            "call_id": str(data.call_id),
            "message_id": str(answer.id),
            "category": data.category,
            "status": "open",
            "revision": 1,
            "question_message_id": _question_id(db, context, cid, data.call_id),
            "citation_chunk_ids": list(
                dict.fromkeys(
                    str(UUID(c["chunk_id"])) for c in answer.message_metadata.get("citations", [])
                )
            ),
        },
    )
    db.add(row)
    db.flush()
    record(
        db,
        request,
        "answer_feedback.create",
        "conversation",
        cid,
        tenant_id=context.tenant_id,
        details={
            "feedback_id": str(row.id),
            "call_id": str(data.call_id),
            "category": data.category,
        },
    )
    return _view(row)


def update(db, context, cid, feedback_id, data, request):
    context = locked_staff_context(db, context, request)
    conversation = get_owned(db, Conversation, context, cid, lock=True)
    operations.controlled(db, context, conversation)
    row = get_owned(db, Collaboration, context, feedback_id, lock=True)
    if row.conversation_id != cid or row.details.get("type") != KIND:
        raise missing()
    if (
        row.details["status"] != data.expected_status
        or row.details.get("revision", 0) != data.expected_revision
    ):
        raise AppError(409, "feedback_changed", "Review status changed; reload first")
    call_id = UUID(row.details["call_id"])
    answer = _answer(db, context, cid, call_id, request)
    related = list(
        dict.fromkeys(
            data.related_chunk_ids
            if "related_chunk_ids" in data.model_fields_set
            else [UUID(value) for value in row.details.get("related_chunk_ids", [])]
        )
    )
    original_citations = {UUID(c["chunk_id"]) for c in answer.message_metadata.get("citations", [])}
    sources = _sources(db, context, cid, call_id, related, request, original_citations)
    changes = {
        "status": data.status,
        "resolution_category": data.resolution_category
        if "resolution_category" in data.model_fields_set
        else row.details.get("resolution_category"),
        "resolution_note": data.resolution_note
        if "resolution_note" in data.model_fields_set
        else row.details.get("resolution_note", ""),
        "related_chunk_ids": [str(chunk_id) for chunk_id in related],
        "related_sources": sources,
        "question_message_id": _question_id(db, context, cid, call_id),
    }
    if any(
        row.details.get(
            key, [] if key == "related_chunk_ids" else "" if key == "resolution_note" else None
        )
        != value
        for key, value in changes.items()
    ):
        row.details = row.details | changes
        row.details = row.details | {"revision": row.details.get("revision", 0) + 1}
        record(
            db,
            request,
            "answer_feedback.update",
            "conversation",
            cid,
            tenant_id=context.tenant_id,
            details={"feedback_id": str(row.id), "status": data.status},
        )
        db.flush()
    return _view(row)
