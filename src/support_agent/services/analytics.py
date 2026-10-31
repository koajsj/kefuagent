"""Bounded UTC cohort metrics; no message scans and no inferred answer correctness."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from support_agent.errors import AppError
from support_agent.models import Conversation, ModelCall, ToolExecution


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def report(db, context, start, end):
    if start.tzinfo is None or end.tzinfo is None:
        raise AppError(422, "invalid_time_range", "Use explicit UTC offsets")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if not timedelta(0) < end - start <= timedelta(days=90):
        raise AppError(422, "invalid_time_range", "Use a UTC half-open interval of at most 90 days")

    tenant = context.tenant_id
    for model in (Conversation, ModelCall, ToolExecution):
        bounded = (
            select(model.id)
            .where(model.tenant_id == tenant, model.created_at >= start, model.created_at < end)
            .limit(10001)
            .subquery()
        )
        if db.scalar(select(func.count()).select_from(bounded)) > 10000:
            raise AppError(
                422,
                "analytics_range_too_large",
                "Narrow the time range; more than 10000 records in one category",
            )

    params = {"tenant": tenant, "start": start, "end": end, "now": datetime.now(UTC)}
    cohort = """SELECT * FROM conversations
        WHERE tenant_id = :tenant AND created_at >= :start AND created_at < :end"""
    calls = """SELECT * FROM model_calls
        WHERE tenant_id = :tenant AND created_at >= :start AND created_at < :end"""

    # PostgreSQL JSON truth matching Python's bool for JSON values, including empty containers.
    def truth(value):
        return f"({value} IS NOT NULL AND {value} NOT IN ('null'::jsonb, 'false'::jsonb, '0'::jsonb, '\"\"'::jsonb, '[]'::jsonb, '{{}}'::jsonb))"

    def rows(sql):
        return db.execute(text(sql), params).mappings().all()

    def one(sql):
        return db.execute(text(sql), params).mappings().one()

    conv = one(f"""
        WITH cohort AS ({cohort}), latest AS (
            SELECT DISTINCT ON (m.conversation_id) m.conversation_id, m.status
            FROM model_calls m JOIN cohort c ON c.id = m.conversation_id
            WHERE m.tenant_id = :tenant AND m.kind IN ('chat', 'agent')
            ORDER BY m.conversation_id, m.created_at DESC, m.id DESC
        )
        SELECT count(*) AS total,
            count(*) FILTER (WHERE c.support_state = 'waiting') AS pending,
            count(*) FILTER (WHERE c.support_state = 'resolved') AS resolved,
            avg(extract(epoch FROM (c.first_response_at - c.created_at))) AS first_response,
            avg(greatest(0, extract(epoch FROM (c.resolved_at - c.created_at))))
                FILTER (WHERE c.resolved_at IS NOT NULL) AS resolution,
            count(*) FILTER (WHERE c.ever_human OR c.waiting_since IS NOT NULL) AS handoffs,
            count(*) FILTER (WHERE c.status = 'open' AND (
                (c.first_response_at IS NULL AND extract(epoch FROM (:now - c.created_at)) >= CASE WHEN c.priority = 'urgent' THEN 60 ELSE 300 END)
                OR (c.support_state = 'waiting' AND c.waiting_since IS NOT NULL AND
                    extract(epoch FROM (coalesce(c.human_started_at, c.resolved_at, :now) - c.waiting_since)) >= CASE WHEN c.priority = 'urgent' THEN 60 ELSE 300 END)
                OR extract(epoch FROM (:now - c.created_at)) >= CASE WHEN c.priority = 'urgent' THEN 3600 ELSE 86400 END
            )) AS overdue,
            count(*) FILTER (WHERE c.support_state = 'resolved' AND NOT c.ever_human
                AND c.waiting_since IS NULL AND latest.status = 'answered') AS ai_resolved,
            count(*) FILTER (WHERE c.support_state != 'resolved' AND latest.status = 'unresolved') AS ai_unresolved
        FROM cohort c LEFT JOIN latest ON latest.conversation_id = c.id
    """)
    step_truth = truth("step.value -> 'usage_complete'")
    kb_truth = truth("c.result -> 'knowledge_base_ids'")
    citation_truth = truth("c.result -> 'citations'")
    usage_complete = f"""CASE WHEN jsonb_array_length(c.steps) > 0 THEN NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(c.steps) AS step(value) WHERE NOT {step_truth}
    ) ELSE coalesce(c.attempts = 0, false) END"""
    call_stats = one(f"""
        WITH calls AS ({calls}), enriched AS (
            SELECT c.*, ({usage_complete}) AS complete,
                (c.kind = 'chat' OR {kb_truth}) AS knowledge,
                {citation_truth} AS citation
            FROM calls c
        )
        SELECT count(*) AS total, count(*) FILTER (WHERE status = 'failed') AS failed,
            coalesce(sum(input_tokens), 0) AS input_tokens, coalesce(sum(output_tokens), 0) AS output_tokens,
            count(*) FILTER (WHERE NOT complete) AS unknown,
            count(*) FILTER (WHERE kind IN ('chat', 'agent')) AS retrieval_total,
            count(*) FILTER (WHERE knowledge) AS knowledge,
            count(*) FILTER (WHERE knowledge AND status IN ('answered', 'unresolved')) AS completed,
            count(*) FILTER (WHERE knowledge AND status IN ('answered', 'unresolved') AND citation) AS cited
        FROM enriched
    """)
    tool_stats = one("""SELECT count(*) AS total, count(*) FILTER (WHERE status = 'succeeded') AS succeeded
        FROM tool_executions WHERE tenant_id = :tenant AND created_at >= :start AND created_at < :end""")
    model_rows = rows(f"""
        WITH calls AS ({calls})
        SELECT CASE WHEN step.value ? 'model' THEN step.value ->> 'model' ELSE c.model END AS model,
            count(*) AS calls,
            coalesce(sum(coalesce((step.value ->> 'input_tokens')::bigint, 0)), 0) AS input_tokens,
            coalesce(sum(coalesce((step.value ->> 'output_tokens')::bigint, 0)), 0) AS output_tokens,
            count(*) FILTER (WHERE NOT {step_truth}) AS unknown_usage_calls
        FROM calls c CROSS JOIN LATERAL jsonb_array_elements(c.steps) AS step(value)
        GROUP BY 1 ORDER BY 1
    """)
    trends = rows(f"""
        WITH cohort AS ({cohort}), calls AS ({calls}), daily_conversations AS (
            SELECT (created_at AT TIME ZONE 'UTC')::date AS day, count(*) AS conversations,
                count(*) FILTER (WHERE ever_human) AS human, count(*) FILTER (WHERE NOT ever_human) AS ai
            FROM cohort GROUP BY 1
        ), daily_calls AS (
            SELECT (c.created_at AT TIME ZONE 'UTC')::date AS day, count(*) AS calls,
                coalesce(sum(c.input_tokens), 0) AS input_tokens, coalesce(sum(c.output_tokens), 0) AS output_tokens,
                count(*) FILTER (WHERE NOT ({usage_complete})) AS unknown_usage_calls
            FROM calls c GROUP BY 1
        )
        SELECT coalesce(a.day, b.day) AS day, coalesce(a.conversations, 0) AS conversations,
            coalesce(a.ai, 0) AS ai, coalesce(a.human, 0) AS human, coalesce(b.calls, 0) AS calls,
            coalesce(b.input_tokens, 0) AS input_tokens, coalesce(b.output_tokens, 0) AS output_tokens,
            coalesce(b.unknown_usage_calls, 0) AS unknown_usage_calls
        FROM daily_conversations a FULL JOIN daily_calls b ON a.day = b.day
    """)
    categories = rows(f"""WITH cohort AS ({cohort}), ranked AS (
        SELECT coalesce(nullif(category, ''), '未分类') AS category,
            row_number() OVER (ORDER BY created_at, id) AS position FROM cohort
        ) SELECT category, count(*) AS count FROM ranked GROUP BY category
        ORDER BY count(*) DESC, min(position) LIMIT 20""")
    unresolved = rows(f"""WITH cohort AS ({cohort}), latest AS (
        SELECT DISTINCT ON (m.conversation_id) m.conversation_id, m.status FROM model_calls m
        JOIN cohort c ON c.id = m.conversation_id WHERE m.tenant_id = :tenant AND m.kind IN ('chat', 'agent')
        ORDER BY m.conversation_id, m.created_at DESC, m.id DESC
        ) SELECT c.id, c.subject FROM cohort c LEFT JOIN latest ON latest.conversation_id = c.id
        WHERE c.support_state != 'resolved' AND (c.support_state = 'waiting' OR latest.status = 'unresolved')
        ORDER BY c.created_at, c.id LIMIT 10""")
    feedback = one(f"""WITH cohort AS ({cohort})
        SELECT (SELECT count(*) FROM visitor_feedback f JOIN cohort c ON c.id = f.conversation_id
                WHERE f.tenant_id = :tenant AND f.rating = 'satisfied') AS satisfied,
            (SELECT count(*) FROM visitor_feedback f JOIN cohort c ON c.id = f.conversation_id
                WHERE f.tenant_id = :tenant AND f.rating = 'dissatisfied') AS dissatisfied,
            (SELECT count(*) FROM visitor_sessions v JOIN cohort c ON c.id = v.conversation_id
                WHERE v.tenant_id = :tenant) AS visitors""")
    daily = {str(row["day"]): dict(row) for row in trends}
    trend = []
    day = start.date()
    while day < end.date() or (day == end.date() and end.time().isoformat() != "00:00:00"):
        key = str(day)
        bucket = daily.get(
            key,
            dict(
                conversations=0,
                ai=0,
                human=0,
                calls=0,
                input_tokens=0,
                output_tokens=0,
                unknown_usage_calls=0,
            ),
        )
        bucket["day"] = key
        trend.append(bucket)
        day += timedelta(days=1)
    satisfied, dissatisfied = feedback["satisfied"], feedback["dissatisfied"]
    return {
        "start": start,
        "end": end,
        "conversations": {
            "total": conv["total"],
            "pending": conv["pending"],
            "resolved": conv["resolved"],
            "avg_first_response_seconds": float(conv["first_response"])
            if conv["first_response"] is not None
            else None,
            "avg_resolution_seconds": float(conv["resolution"])
            if conv["resolution"] is not None
            else None,
            "handoff_rate": ratio(conv["handoffs"], conv["total"]),
            "overdue": conv["overdue"],
            "ai_resolved": conv["ai_resolved"],
            "ai_to_human": conv["handoffs"],
            "ai_unresolved": conv["ai_unresolved"],
        },
        "ai": {
            "retrieval_use_rate": ratio(call_stats["knowledge"], call_stats["retrieval_total"]),
            "valid_citation_rate": ratio(call_stats["cited"], call_stats["completed"]),
            "tool_success_rate": ratio(tool_stats["succeeded"], tool_stats["total"]),
        },
        "usage": {
            "calls": call_stats["total"],
            "failed": call_stats["failed"],
            "input_tokens": call_stats["input_tokens"],
            "output_tokens": call_stats["output_tokens"],
            "unknown_usage_calls": call_stats["unknown"],
            "known_cost": None,
            "unknown_cost_calls": call_stats["total"],
            "models": [dict(row) for row in model_rows],
        },
        "trend": trend,
        "categories": [dict(row) for row in categories],
        "unresolved": [dict(row) for row in unresolved],
        "feedback": {
            "satisfied": satisfied,
            "dissatisfied": dissatisfied,
            "unrated": feedback["visitors"] - satisfied - dissatisfied,
            "satisfaction_rate": ratio(satisfied, satisfied + dissatisfied),
        },
    }
