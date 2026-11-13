"""Cross-process admission using existing tenant-scoped ModelCall reservations."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, text

from support_agent.errors import AppError
from support_agent.models import ModelCall


def scope_usage(db, context, call, field=None):
    now = datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    unsettled = (ModelCall.status == "running") | (
        (ModelCall.reserved_tokens > 0)
        & (
            ModelCall.attempts.is_(None)
            | ModelCall.input_tokens.is_(None)
            | ModelCall.output_tokens.is_(None)
        )
    )
    filters = [
        ModelCall.tenant_id == context.tenant_id,
        ModelCall.id != call.id,
        or_(
            ModelCall.created_at
            >= min(
                now - timedelta(minutes=1),
                now.replace(hour=0, minute=0, second=0, microsecond=0),
            ),
            unsettled,
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
                    (ModelCall.created_at >= today) | unsettled
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
    # Each paid dispatch reserves its own reviewed bound at the gateway, including
    # embedding/reranking/fallback. A guessed fixed number of steps is insufficient.
    call.reserved_tokens = 0
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


def reserve_step(db, context, call, request, pricing, runtime):
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "model-admission:" + str(context.tenant_id)},
    )
    # Keep one call in its admission day; running/unknown reservations carry
    # forward until accounted, so crossing midnight cannot reset an in-flight run.
    if call.created_at.date() != datetime.now(UTC).date():
        raise AppError(
            409, "token_reservation_day_changed", "Start a fresh request for the new UTC day"
        )
    bound = pricing["context_window_tokens"] + runtime["max_output_tokens"]
    for scope, field in (("tenant", None), ("user", "created_by"), ("agent", "agent_config_id")):
        if scope == "user" and context.public_session_id is not None:
            continue
        used = scope_usage(db, context, call, field)["tokens_reserved_today"]
        if used + call.reserved_tokens + bound > getattr(
            request.app.state.settings, scope + "_daily_token_budget"
        ):
            raise AppError(
                429, "token_budget_exceeded", "Conservative daily token budget exhausted"
            )
    call.reserved_tokens += bound
    return bound


def settle(call):
    if call.steps and all(
        "token_reservation" in step or step.get("attempts") == 0 for step in call.steps
    ):
        call.reserved_tokens = sum(
            0
            if step.get("attempts") == 0
            else step["input_tokens"] + step["output_tokens"]
            if step.get("usage_complete")
            else step.get("token_reservation", 0)
            for step in call.steps
        )
        return
    if call.status == "running":
        return
    if call.attempts == 0 and not call.steps:
        call.reserved_tokens = 0
    elif call.steps and all(step.get("usage_complete") for step in call.steps):
        call.reserved_tokens = sum(s["input_tokens"] + s["output_tokens"] for s in call.steps)
    # Legacy ambiguous usage retains its reservation; never treat null as zero.


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
