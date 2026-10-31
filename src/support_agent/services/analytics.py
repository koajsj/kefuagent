"""Bounded UTC cohort metrics; no message scans and no inferred answer correctness."""

from collections import Counter, defaultdict
from datetime import UTC, timedelta

from sqlalchemy import func, select

from support_agent.errors import AppError
from support_agent.models import (
    Conversation,
    ModelCall,
    ToolExecution,
    VisitorFeedback,
    VisitorSession,
)
from support_agent.services.operations import service_times


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def report(db, context, start, end):
    if start.tzinfo is None or end.tzinfo is None:
        raise AppError(422, "invalid_time_range", "Use explicit UTC offsets")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if not timedelta(0) < end - start <= timedelta(days=90):
        raise AppError(422, "invalid_time_range", "Use a UTC half-open interval of at most 90 days")

    def bounded(model):
        rows = list(
            db.scalars(
                select(model)
                .where(
                    model.tenant_id == context.tenant_id,
                    model.created_at >= start,
                    model.created_at < end,
                )
                .order_by(model.created_at, model.id)
                .limit(10001)
            )
        )
        if len(rows) > 10000:
            raise AppError(
                422,
                "analytics_range_too_large",
                "Narrow the time range; more than 10000 records in one category",
            )
        return rows

    conversations, calls, tools = (
        bounded(model) for model in (Conversation, ModelCall, ToolExecution)
    )
    ids = [row.id for row in conversations]
    latest = (
        db.execute(
            select(ModelCall.conversation_id, ModelCall.status)
            .where(
                ModelCall.tenant_id == context.tenant_id,
                ModelCall.conversation_id.in_(ids),
                ModelCall.kind.in_(["chat", "agent"]),
            )
            .distinct(ModelCall.conversation_id)
            .order_by(ModelCall.conversation_id, ModelCall.created_at.desc(), ModelCall.id.desc())
        ).all()
        if ids
        else []
    )
    statuses = dict(latest)
    feedback_rows = (
        db.execute(
            select(VisitorFeedback.rating, func.count())
            .where(
                VisitorFeedback.tenant_id == context.tenant_id,
                VisitorFeedback.conversation_id.in_(ids),
            )
            .group_by(VisitorFeedback.rating)
        ).all()
        if ids
        else []
    )
    ratings = dict(feedback_rows)
    visitors = (
        db.scalar(
            select(func.count())
            .select_from(VisitorSession)
            .where(
                VisitorSession.tenant_id == context.tenant_id,
                VisitorSession.conversation_id.in_(ids),
            )
        )
        if ids
        else 0
    )
    satisfied, dissatisfied = ratings.get("satisfied", 0), ratings.get("dissatisfied", 0)
    resolved = [row for row in conversations if row.support_state == "resolved"]
    times = [service_times(row) for row in conversations]

    def average(field):
        values = [row[field] for row in times if row[field] is not None]
        return sum(values) / len(values) if values else None

    handoffs = sum(row.ever_human or row.waiting_since is not None for row in conversations)
    knowledge_calls = [
        call
        for call in calls
        if call.kind == "chat" or (call.result or {}).get("knowledge_base_ids")
    ]
    completed_knowledge = [
        call for call in knowledge_calls if call.status in {"answered", "unresolved"}
    ]
    valid_citations = sum(
        bool((call.result or {}).get("citations")) for call in completed_knowledge
    )
    day_rows = {}
    day = start.date()
    while day < end.date() or (day == end.date() and end.time().isoformat() != "00:00:00"):
        day_rows[str(day)] = dict(
            day=str(day),
            conversations=0,
            ai=0,
            human=0,
            calls=0,
            input_tokens=0,
            output_tokens=0,
            unknown_usage_calls=0,
        )
        day += timedelta(days=1)
    for row in conversations:
        bucket = day_rows[str(row.created_at.astimezone(UTC).date())]
        bucket["conversations"] += 1
        bucket["human" if row.ever_human else "ai"] += 1
    models = defaultdict(
        lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "unknown_usage_calls": 0}
    )
    for call in calls:
        bucket = day_rows[str(call.created_at.astimezone(UTC).date())]
        bucket["calls"] += 1
        bucket["unknown_usage_calls"] += not call.usage_complete
        bucket["input_tokens"] += call.input_tokens or 0
        bucket["output_tokens"] += call.output_tokens or 0
        # Per-model metrics count durable provider steps, including summary/fallback attempts.
        for step in call.steps:
            model = models[step.get("model", call.model)]
            model["calls"] += 1
            model["input_tokens"] += step.get("input_tokens") or 0
            model["output_tokens"] += step.get("output_tokens") or 0
            model["unknown_usage_calls"] += not step.get("usage_complete", False)
    category_counts = Counter(row.category or "未分类" for row in conversations)
    return {
        "start": start,
        "end": end,
        "conversations": {
            "total": len(conversations),
            "pending": sum(row.support_state == "waiting" for row in conversations),
            "resolved": len(resolved),
            "avg_first_response_seconds": average("first_response_seconds"),
            "avg_resolution_seconds": average("resolution_seconds"),
            "handoff_rate": ratio(handoffs, len(conversations)),
            "overdue": sum(row["state"] == "overdue" for row in times),
            "ai_resolved": sum(
                not row.ever_human
                and row.waiting_since is None
                and statuses.get(row.id) == "answered"
                for row in resolved
            ),
            "ai_to_human": handoffs,
            "ai_unresolved": sum(
                row.support_state != "resolved" and statuses.get(row.id) == "unresolved"
                for row in conversations
            ),
        },
        "ai": {
            "retrieval_use_rate": ratio(
                len(knowledge_calls), sum(call.kind in {"chat", "agent"} for call in calls)
            ),
            "valid_citation_rate": ratio(valid_citations, len(completed_knowledge)),
            "tool_success_rate": ratio(sum(row.status == "succeeded" for row in tools), len(tools)),
        },
        "usage": {
            "calls": len(calls),
            "failed": sum(call.status == "failed" for call in calls),
            "input_tokens": sum(call.input_tokens or 0 for call in calls),
            "output_tokens": sum(call.output_tokens or 0 for call in calls),
            "unknown_usage_calls": sum(not call.usage_complete for call in calls),
            "known_cost": None,
            "unknown_cost_calls": len(calls),
            "models": [{"model": model, **metrics} for model, metrics in sorted(models.items())],
        },
        "trend": list(day_rows.values()),
        "categories": [
            {"category": name, "count": count} for name, count in category_counts.most_common(20)
        ],
        "unresolved": [
            {"id": row.id, "subject": row.subject}
            for row in conversations
            if row.support_state != "resolved"
            and (row.support_state == "waiting" or statuses.get(row.id) == "unresolved")
        ][:10],
        "feedback": {
            "satisfied": satisfied,
            "dissatisfied": dissatisfied,
            "unrated": visitors - satisfied - dissatisfied,
            "satisfaction_rate": ratio(satisfied, satisfied + dissatisfied),
        },
    }
