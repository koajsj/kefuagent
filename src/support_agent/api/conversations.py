from uuid import UUID

from fastapi import APIRouter, Query, Request

from support_agent.dependencies import Database, TenantContext
from support_agent.models import Conversation
from support_agent.rag_schemas import ChatInput, ChatOut
from support_agent.schemas import (
    ConversationCreate,
    ConversationOut,
    ConversationPatch,
    MessageCreate,
    MessageOut,
)
from support_agent.services import chat, conversations
from support_agent.services.resources import get_owned, list_owned
from support_agent.tool_protocol import AgentTurnInput, AgentTurnOut

router = APIRouter(prefix="/conversations", tags=["Conversations and messages"])


@router.post("", response_model=ConversationOut, status_code=201)
def create(data: ConversationCreate, request: Request, db: Database, context: TenantContext):
    return conversations.create(db, context, data, request)


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    db: Database,
    context: TenantContext,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return list_owned(db, Conversation, context, limit, offset)


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
):
    return conversations.history(db, context, conversation_id, limit, offset, request)


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
