from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from support_agent.dependencies import Database, TenantContext
from support_agent.models import Conversation, ModelCall
from support_agent.operations_schemas import (
    CollaborationOut,
    NoteInput,
    OperationsPatch,
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

router = APIRouter(prefix="/conversations", tags=["Conversations and messages"])


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
    return conversations.create(db, context, data, request)


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
    sort: Literal["newest", "oldest"] = "newest",
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
        sort=sort,
    )


@router.get("/{conversation_id}", response_model=ConversationOut)
def detail(conversation_id: UUID, db: Database, context: TenantContext):
    return get_owned(db, Conversation, context, conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationOut)
def status(
    conversation_id: UUID,
    data: ConversationPatch,
    request: Request,
    db: Database,
    context: TenantContext,
):
    return conversations.set_status(db, context, conversation_id, data, request)


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
):
    return conversations.history(db, context, conversation_id, limit, offset, request, newest)


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
    return conversations.set_handling(db, context, conversation_id, data, request)


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
    return operations.update(db, context, conversation_id, data, request)


@router.get("/{conversation_id}/collaboration", response_model=list[CollaborationOut])
def collaboration(
    conversation_id: UUID,
    db: Database,
    context: TenantContext,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
):
    return operations.notes(db, context, conversation_id, limit, offset)


@router.post("/{conversation_id}/collaboration", response_model=CollaborationOut, status_code=201)
def note(
    conversation_id: UUID, data: NoteInput, request: Request, db: Database, context: TenantContext
):
    return operations.add_note(db, context, conversation_id, data, request)


@router.get("/{conversation_id}/summary", response_model=SummaryOut | None)
def summary(conversation_id: UUID, db: Database, context: TenantContext):
    from support_agent.services.memory import latest

    get_owned(db, Conversation, context, conversation_id)
    return latest(db, context, conversation_id)
