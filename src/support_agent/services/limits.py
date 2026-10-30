"""Cross-process admission using existing tenant-scoped ModelCall reservations."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, text

from support_agent.errors import AppError
from support_agent.models import ModelCall


def scope_usage(db, context, call, field=None):
    now = datetime.now(UTC)
    filters = [
        ModelCall.tenant_id == context.tenant_id,
        ModelCall.id != call.id,
        or_(
            ModelCall.created_at
            >= min(
                now - timedelta(minutes=1),
                now.replace(hour=0, minute=0, second=0, microsecond=0),
            ),
            (ModelCall.status == "running") & (ModelCall.lease_expires_at > now),
        ),
    ]
    if field == "created_by":
        filters.append(ModelCall.visitor_session_id.is_(None))
    if field:
        filters.append(getattr(ModelCall, field) == getattr(call, field))
    row = db.execute(
        select(
            func.count().filter(ModelCall.created_at >= now - timedelta(minutes=1)),
            func.count().filter(
                (ModelCall.status == "running") & (ModelCall.lease_expires_at > now)
            ),
            func.coalesce(
                func.sum(ModelCall.reserved_tokens).filter(
                    ModelCall.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0)
                ),
                0,
            ),
        ).where(*filters)
    ).one()
    return dict(
        zip(("requests_last_minute", "active_calls", "tokens_reserved_today"), row, strict=True)
    )


def admit(db, context, call, request, runtime, *, offline=False):
    # This lock is shared across all HTTP workers, held only through the short reservation transaction.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "model-admission:" + str(context.tenant_id)},
    )
    logical_steps = 5 if call.kind == "agent" else 1
    call.reserved_tokens = (
        0
        if call.kind == "tool_execution" or offline
        else logical_steps * 4 * (runtime["max_input_tokens"] + runtime["max_output_tokens"])
    )
    if context.public_session_id is not None:
        from support_agent.models import VisitorSession

        visitor = db.get(VisitorSession, context.public_session_id, with_for_update=True)
        count = db.scalar(
            select(func.count())
            .select_from(ModelCall)
            .where(
                ModelCall.tenant_id == context.tenant_id,
                ModelCall.visitor_session_id == context.public_session_id,
                ModelCall.id != call.id,
                ModelCall.created_at >= datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        if visitor.turn_count >= 30 or count >= 6:
            raise AppError(429, "visitor_limit_exceeded", "Visitor conversation limit reached")
        visitor.turn_count += 1
    settings = request.app.state.settings
    for scope, field in [("tenant", None), ("user", "created_by"), ("agent", "agent_config_id")]:
        if scope == "user" and context.public_session_id is not None:
            continue
        usage = scope_usage(db, context, call, field)
        if usage["requests_last_minute"] >= getattr(settings, scope + "_requests_per_minute"):
            raise AppError(429, "request_limit_exceeded", "Request limit reached; retry later")
        if usage["active_calls"] >= getattr(settings, scope + "_concurrent_calls"):
            raise AppError(429, "concurrency_limit_exceeded", "Concurrent call limit reached")
        if usage["tokens_reserved_today"] + call.reserved_tokens > getattr(
            settings, scope + "_daily_token_budget"
        ):
            raise AppError(
                429, "token_budget_exceeded", "Conservative daily token budget exhausted"
            )


def settle(call):
    if call.status == "running":
        return
    if call.attempts == 0 and not call.steps:
        call.reserved_tokens = 0
    elif call.steps and all(step.get("usage_complete") for step in call.steps):
        call.reserved_tokens = sum(s["input_tokens"] + s["output_tokens"] for s in call.steps)
    # Unknown/ambiguous usage holds the reservation until the next UTC day; never treat null as zero.


def view(db, context, request):
    from types import SimpleNamespace
    from uuid import uuid4

    placeholder = SimpleNamespace(id=uuid4(), created_by=context.user_id, agent_config_id=None)
    fields = ("requests_per_minute", "concurrent_calls", "daily_token_budget")
    return {
        "day_timezone": "UTC",
        "limits": {
            scope: {
                name: getattr(request.app.state.settings, scope + "_" + name) for name in fields
            }
            for scope in ("tenant", "user", "agent")
        },
        "tenant_usage": scope_usage(db, context, placeholder),
        "current_user_usage": scope_usage(db, context, placeholder, "created_by"),
    }
