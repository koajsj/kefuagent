from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from support_agent.dependencies import Database, TenantContext, locked_staff_context
from support_agent.feedback_schemas import (
    AnswerFeedbackCreate,
    AnswerFeedbackOut,
    AnswerFeedbackPatch,
    FeedbackCategory,
    FeedbackStatus,
)
from support_agent.models import Conversation, ModelCall
from support_agent.operations_schemas import (
    CollaborationOut,
    NoteInput,
    OperationsPatch,
    ReadCursorInput,
    ReadCursorOut,
    SummaryOut,
)
from support_agent.rag_schemas import CallOut, ChatInput, ChatOut
from support_agent.schemas import (
    ConversationCreate,
    ConversationHandling,
    ConversationOut,
    ConversationPatch,
    MessageCreate,
    MessageOut,
)
from support_agent.services import chat, conversations, operations
from support_agent.services.resources import get_owned
from support_agent.tool_protocol import AgentTurnInput, AgentTurnOut
from support_agent.trace_schemas import TraceOut

router = APIRouter(prefix="/conversations", tags=["Conversations and messages"])


@router.get("/{conversation_id}/runs/{call_id}/trace", response_model=TraceOut)
def trace(
    conversation_id: UUID, call_id: UUID, request: Request, db: Database, context: TenantContext
):
    from support_agent.services.traces import get_trace

    return get_trace(db, context, conversation_id, call_id, request)


@router.get("/{conversation_id}/answer-feedback", response_model=list[AnswerFeedbackOut])
def answer_reviews(
    conversation_id: UUID,
    request: Request,
    db: Database,
    context: TenantContext,
    call_id: UUID | None = None,
    status: FeedbackStatus | None = None,
    category: FeedbackCategory | None = None,
    limit: int = Query(30, ge=1, le=100),
    before: UUID | None = None,
    mine: bool = False,
):
    from support_agent.services import answer_feedback

    return answer_feedback.listing(
        db,
        context,
        conversation_id,
        request,
        call_id=call_id,
        status=status,
        category=category,
        limit=limit,
        before=before,
        mine=mine,
    )


@router.post(
    "/{conversation_id}/answer-feedback", response_model=AnswerFeedbackOut, status_code=201
)
def create_answer_review(
    conversation_id: UUID,
    data: AnswerFeedbackCreate,
    request: Request,
    db: Database,
    context: TenantContext,
):
    from support_agent.services import answer_feedback

    return answer_feedback.create(db, context, conversation_id, data, request)


@router.patch("/{conversation_id}/answer-feedback/{feedback_id}", response_model=AnswerFeedbackOut)
def change_answer_review(
    conversation_id: UUID,
    feedback_id: UUID,
    data: AnswerFeedbackPatch,
    request: Request,
    db: Database,
    context: TenantContext,
):
    from support_agent.services import answer_feedback

    return answer_feedback.update(db, context, conversation_id, feedback_id, data, request)


@router.get("/{conversation_id}/runs/{call_id}", response_model=CallOut)
def run(
    conversation_id: UUID, call_id: UUID, request: Request, db: Database, context: TenantContext
):
    from support_agent.errors import missing

    get_owned(db, Conversation, context, conversation_id)
    row = get_owned(db, ModelCall, context, call_id)
    if row.conversation_id != conversation_id:
        raise missing()
    return chat.reconcile_expired(db, context, [row], request)[0]


@router.post("", response_model=ConversationOut, status_code=201)
def create(data: ConversationCreate, request: Request, db: Database, context: TenantContext):
    return operations.describe_conversations(
        db, context, [conversations.create(db, context, data, request)]
    )[0]


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    db: Database,
    context: TenantContext,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
    q: str = Query("", max_length=100),
    queue: Literal["all", "pending", "unassigned", "mine", "human", "ai", "resolved"] = "all",
    assignee_id: UUID | None = None,
    priority: Literal["low", "normal", "high", "urgent"] | None = None,
    tag: str | None = Query(None, min_length=1, max_length=40),
    sort: Literal[
        "newest", "oldest", "activity", "customer_activity", "priority", "sla"
    ] = "activity",
):
    return operations.listing(
        db,
        context,
        limit=limit,
        offset=offset,
        q=q,
        queue=queue,
        assignee_id=assignee_id,
        priority=priority,
        tag=tag,
        sort=sort,
    )


@router.get("/{conversation_id}", response_model=ConversationOut)
def detail(conversation_id: UUID, db: Database, context: TenantContext):
    return operations.describe_conversations(
        db, context, [get_owned(db, Conversation, context, conversation_id)]
    )[0]


@router.patch("/{conversation_id}", response_model=ConversationOut)
def status(
    conversation_id: UUID,
    data: ConversationPatch,
    request: Request,
    db: Database,
    context: TenantContext,
):
    return operations.describe_conversations(
        db, context, [conversations.set_status(db, context, conversation_id, data, request)]
    )[0]


@router.post("/{conversation_id}/messages", response_model=MessageOut, status_code=201)
def append(
    conversation_id: UUID,
    data: MessageCreate,
    request: Request,
    db: Database,
    context: TenantContext,
):
    return conversations.append_message(db, context, conversation_id, data, request)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def history(
    conversation_id: UUID,
    request: Request,
    db: Database,
    context: TenantContext,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    newest: bool = False,
    after: UUID | None = None,
    before: UUID | None = None,
):
    return conversations.history(
        db, context, conversation_id, limit, offset, request, newest, after=after, before=before
    )


@router.post("/{conversation_id}/read", response_model=ReadCursorOut)
def mark_read(
    conversation_id: UUID,
    data: ReadCursorInput,
    request: Request,
    db: Database,
    context: TenantContext,
):
    context = locked_staff_context(db, context, request)
    return operations.read_cursor(db, context, conversation_id, data.message_id)


@router.get("/{conversation_id}/messages/{message_id}", response_model=MessageOut)
def source_message(
    conversation_id: UUID, message_id: UUID, request: Request, db: Database, context: TenantContext
):
    rows = conversations.history(db, context, conversation_id, 1, 0, request, at=message_id)
    if not rows:
        from support_agent.errors import missing

        raise missing()
    return rows[0]


@router.post("/{conversation_id}/chat", response_model=ChatOut)
def turn(
    conversation_id: UUID, data: ChatInput, request: Request, db: Database, context: TenantContext
):
    return chat.turn(db, context, conversation_id, data, request)


@router.post("/{conversation_id}/agent-turns", response_model=AgentTurnOut)
def agent_turn(
    conversation_id: UUID,
    data: AgentTurnInput,
    request: Request,
    db: Database,
    context: TenantContext,
):
    from support_agent.services.agent_turns import turn

    return turn(db, context, conversation_id, data, request)


@router.get("/{conversation_id}/calls", response_model=list[CallOut])
def conversation_calls(
    conversation_id: UUID,
    request: Request,
    db: Database,
    context: TenantContext,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    get_owned(db, Conversation, context, conversation_id)
    rows = db.scalars(
        select(ModelCall)
        .where(
            ModelCall.tenant_id == context.tenant_id, ModelCall.conversation_id == conversation_id
        )
        .order_by(ModelCall.created_at.desc(), ModelCall.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return chat.reconcile_expired(db, context, rows, request)


@router.post("/{conversation_id}/handling", response_model=ConversationOut)
def handling(
    conversation_id: UUID,
    data: ConversationHandling,
    request: Request,
    db: Database,
    context: TenantContext,
):
    return operations.describe_conversations(
        db, context, [conversations.set_handling(db, context, conversation_id, data, request)]
    )[0]


@router.post(
    "/{conversation_id}/agent-turns/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "SSE stage/delta/completed/pending/failed/timed_out; 200 is not a success outcome",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
def stream_turn(
    conversation_id: UUID,
    data: AgentTurnInput,
    request: Request,
    db: Database,
    context: TenantContext,
):
    from support_agent.streaming import response

    get_owned(db, Conversation, context, conversation_id)
    return response(request, context, conversation_id, data)


@router.patch("/{conversation_id}/operations", response_model=ConversationOut)
def update_operations(
    conversation_id: UUID,
    data: OperationsPatch,
    request: Request,
    db: Database,
    context: TenantContext,
):
    return operations.describe_conversations(
        db, context, [operations.update(db, context, conversation_id, data, request)]
    )[0]


@router.get("/{conversation_id}/collaboration", response_model=list[CollaborationOut])
def collaboration(
    conversation_id: UUID,
    db: Database,
    context: TenantContext,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
    before: UUID | None = None,
):
    return operations.notes(db, context, conversation_id, limit, offset, before)


@router.post("/{conversation_id}/collaboration", response_model=CollaborationOut, status_code=201)
def note(
    conversation_id: UUID, data: NoteInput, request: Request, db: Database, context: TenantContext
):
    return operations.add_note(db, context, conversation_id, data, request)


@router.get("/{conversation_id}/summary", response_model=SummaryOut | None)
def summary(conversation_id: UUID, db: Database, context: TenantContext):
    import json

    from support_agent.services.memory import latest, safe_previous

    get_owned(db, Conversation, context, conversation_id)
    row = latest(db, context, conversation_id)
    if row is None:
        return None
    items, _ = safe_previous(db, context, conversation_id, row)
    return SummaryOut.model_validate(row).model_copy(
        update={"content": json.dumps(items, ensure_ascii=False)}
    )
