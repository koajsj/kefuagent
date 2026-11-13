"""Materialize bounded authorized data in the server, never in the child process."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from support_agent.models import Conversation, Message
from support_agent.retrieval import reference_is_safe
from support_agent.services import desk_tools, workspace
from support_agent.services.operations import service_times
from support_agent.services.resources import get_owned

SNAPSHOT_KEYS = frozenset(
    {"conversation_status", "conversation_history", "conversation_sla", "knowledge_search"}
    | desk_tools.READ_KEYS
)
PUBLIC_DENIED_KEYS = frozenset({"conversation_history"} | desk_tools.ALL_KEYS)


def materialize(db, context, call, key, arguments, retriever):
    if key in desk_tools.READ_KEYS:
        return desk_tools.lookup(db, context, call, key, arguments)
    conversation = get_owned(db, Conversation, context, call.conversation_id, refresh=True)
    if key == "conversation_status":
        return {
            "status": conversation.status,
            "support_state": conversation.support_state,
            "observed_at": datetime.now(UTC).isoformat(),
        }
    if key == "conversation_sla":
        due = ""
        if conversation.status == "open" and conversation.first_response_at is None:
            seconds = 60 if conversation.priority == "urgent" else 300
            due = (conversation.created_at + timedelta(seconds=seconds)).isoformat()
        return {
            "state": service_times(conversation)["state"],
            "first_response_due_at": due,
            "observed_at": datetime.now(UTC).isoformat(),
        }
    if key == "conversation_history":
        rows = db.execute(
            select(Message.id, Message.content)
            .where(
                Message.tenant_id == context.tenant_id,
                Message.conversation_id == conversation.id,
                Message.source == "agent",
                Message.role == "user",
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(6)
        ).all()
        return {
            "messages": [{"id": str(mid), "content": value[:400]} for mid, value in reversed(rows)]
        }
    if key == "knowledge_search":
        selected = set((call.result or {}).get("knowledge_base_ids", []))
        allowed = [
            kid
            for kid in workspace.knowledge_ids(db, context, call.agent_config_id)
            if str(kid) in selected
        ]
        hits = (
            retriever.search(db, context, allowed, arguments["query"], limit=3) if allowed else []
        )
        return {
            "hits": [{"chunk_id": str(hit.chunk_id), "excerpt": hit.content[:500]} for hit in hits]
        }
    raise ValueError("Unknown snapshot capability")


def still_current(db, context, call, key, result, retriever):
    if key in desk_tools.ALL_KEYS:
        return desk_tools.still_current(db, context, call, key, result)
    if key == "knowledge_search":
        hits = result["hits"]
        ids = [UUID(hit["chunk_id"]) for hit in hits]
        rows = retriever.current_chunks(
            db, context, ids, lock=True, current_only=call.status == "running"
        )
        selected = set((call.result or {}).get("knowledge_base_ids", []))
        allowed = {
            kid
            for kid in workspace.knowledge_ids(db, context, call.agent_config_id)
            if str(kid) in selected
        }
        return all(
            UUID(hit["chunk_id"]) in rows
            and rows[UUID(hit["chunk_id"])][1].knowledge_base_id in allowed
            and hit["excerpt"] in rows[UUID(hit["chunk_id"])][0].content
            and reference_is_safe(rows[UUID(hit["chunk_id"])][0].content)
            for hit in hits
        )
    if key == "conversation_history":
        entries = result["messages"]
        ids = [UUID(entry["id"]) for entry in entries]
        rows = dict(
            db.execute(
                select(Message.id, Message.content).where(
                    Message.tenant_id == context.tenant_id,
                    Message.conversation_id == call.conversation_id,
                    Message.source == "agent",
                    Message.role == "user",
                    Message.id.in_(ids),
                )
            ).all()
        )
        return all(
            UUID(entry["id"]) in rows and rows[UUID(entry["id"])][:400] == entry["content"]
            for entry in entries
        )
    # Operational state is a timestamped observation. Comparing mutable SLA values
    # would invalidate the reply that itself sets first_response_at. Authorization
    # is rechecked by the caller; this check keeps the scope, not the state, current.
    get_owned(db, Conversation, context, call.conversation_id, refresh=True)
    return key in {"conversation_status", "conversation_sla"}
