"""Staff handoff packet from persisted facts; never an invented model summary."""

from sqlalchemy import select

from support_agent.errors import AppError
from support_agent.models import Collaboration, Conversation, ModelCall, Ticket, ToolExecution
from support_agent.services import desk, memory, workspace
from support_agent.services.resources import get_owned


def packet(db, context, conversation_id, request):
    desk.staff(context)
    conversation = get_owned(db, Conversation, context, conversation_id)
    reason = db.scalar(
        select(Collaboration)
        .where(
            Collaboration.tenant_id == context.tenant_id,
            Collaboration.conversation_id == conversation_id,
            Collaboration.kind == "handling",
        )
        .order_by(Collaboration.created_at.desc(), Collaboration.id.desc())
        .limit(1)
    )
    call = db.scalar(
        select(ModelCall)
        .where(
            ModelCall.tenant_id == context.tenant_id, ModelCall.conversation_id == conversation_id
        )
        .order_by(ModelCall.created_at.desc(), ModelCall.id.desc())
        .limit(1)
    )
    sources = []
    sources_state = "UNKNOWN"
    tools = []
    if call:
        from support_agent.services import agent_turns, tool_execution

        executions = list(
            db.scalars(
                select(ToolExecution)
                .where(
                    ToolExecution.tenant_id == context.tenant_id,
                    ToolExecution.model_call_id == call.id,
                )
                .order_by(ToolExecution.created_at, ToolExecution.id)
                .limit(101)
            )
        )
        if len(executions) > 100:
            raise AppError(
                409, "handoff_provenance_limit", "Review the complete run before handoff"
            )
        tools = [
            {
                "execution_id": str(row.id),
                "tool_name": row.tool_name,
                "status": row.status,
                "error_category": row.error_category,
            }
            for row in executions
        ]
        try:
            tool_execution.ensure_delivery(db, context, call, executions, request)
            allowed = workspace.knowledge_ids(db, context, call.agent_config_id)
            current = agent_turns.current_citations(db, context, call, request, allowed)
        except AppError:
            sources_state = "UNAVAILABLE"
        else:
            sources_state = "CURRENT" if current else "UNAVAILABLE"
            if current:
                sources = [
                    {
                        key: item.get(key)
                        for key in ("document_id", "document_name", "chunk_id", "page", "section")
                    }
                    for item in (call.result or {}).get("citations", [])
                ]
    pending = db.scalars(
        select(Ticket)
        .where(
            Ticket.tenant_id == context.tenant_id,
            Ticket.conversation_id == conversation_id,
            Ticket.status.in_(["open", "in_progress"]),
        )
        .order_by(Ticket.updated_at.desc(), Ticket.id)
        .limit(101)
    ).all()
    return {
        "conversation_id": conversation_id,
        "conversation_version": conversation.version,
        "support_state": conversation.support_state,
        "snapshot_kind": "persisted_fact_summary",
        "summary": memory.payload(db, context, conversation_id),
        "reason": (reason.details or {}).get("reason") if reason else None,
        "knowledge_sources": sources,
        "knowledge_sources_state": sources_state,
        "tool_executions": tools,
        "latest_model_call_id": call.id if call else None,
        "pending_tickets": [
            {"id": str(row.id), "title": row.title, "status": row.status} for row in pending[:100]
        ],
        "pending_tickets_truncated": len(pending) > 100,
        "untracked_pending_tasks": "UNKNOWN",
        "client_delivery": "UNKNOWN",
    }
