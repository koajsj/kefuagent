"""Atomic monetary admission, with durable unknown reservations and frozen pricing."""

from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import func, or_, select, text

from support_agent.dependencies import locked_staff_context
from support_agent.errors import AppError
from support_agent.maintenance import confirmation
from support_agent.models import AgentConfig, BudgetPolicy, CostReservation
from support_agent.services.audit import record
from support_agent.services.resources import get_owned

UNIT = Decimal("0.000000000001")
UNRESOLVED = ("RESERVED", "UNKNOWN", "OVERRUN")


def gate(db, tid):
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "money-budget:" + str(tid)},
    )


def catalog(settings):
    return confirmation([p.model_dump(mode="json") for p in settings.model_prices])


def policy(db, tid):
    return db.scalar(
        select(BudgetPolicy)
        .where(BudgetPolicy.tenant_id == tid)
        .execution_options(populate_existing=True)
    )


def usage(db, tid, *, call_id=None, agent_id=None):
    now = datetime.now(UTC)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    base = [CostReservation.tenant_id == tid]
    if call_id:
        base.append(CostReservation.model_call_id == call_id)
    if agent_id:
        base.append(CostReservation.agent_config_id == agent_id)
    # Unresolved charges carry forward across ALL UTC windows until reconciliation.
    return dict(
        zip(
            ("daily", "monthly", "total"),
            db.execute(
                select(
                    *[
                        func.coalesce(
                            func.sum(CostReservation.charged).filter(
                                or_(
                                    CostReservation.created_at >= start,
                                    CostReservation.status.in_(UNRESOLVED),
                                )
                            ),
                            0,
                        )
                        if start
                        else func.coalesce(func.sum(CostReservation.charged), 0)
                        for start in (day, month, None)
                    ]
                ).where(*base)
            ).one(),
            strict=True,
        )
    )


def save(db, context, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    gate(db, context.tenant_id)
    row = policy(db, context.tenant_id)
    if data.expected_version != (row.version if row else 0):
        raise AppError(409, "budget_version_conflict", "Refresh the budget before changing it")
    values = data.model_dump(exclude={"expected_version", "agent_limits"})
    values["agent_limits"] = {str(k): str(v) for k, v in data.agent_limits.items()}
    for aid in data.agent_limits:
        get_owned(db, AgentConfig, context, aid)
    if (
        row
        and row.currency != data.currency
        and db.scalar(
            select(func.count())
            .select_from(CostReservation)
            .where(CostReservation.tenant_id == context.tenant_id)
        )
    ):
        raise AppError(
            409,
            "budget_currency_immutable",
            "Existing ledger currency cannot be converted implicitly",
        )
    if row is None:
        row = BudgetPolicy(
            tenant_id=context.tenant_id,
            version=1,
            **values,
            price_catalog_digest=catalog(request.app.state.settings),
        )
        db.add(row)
    else:
        for name, value in values.items():
            setattr(row, name, value)
        row.version += 1
        row.price_catalog_digest = catalog(request.app.state.settings)
    db.flush()
    record(
        db,
        request,
        "budget.update",
        "budget_policy",
        row.id,
        tenant_id=context.tenant_id,
        details={
            **values,
            "run_limit": str(data.run_limit),
            "daily_limit": str(data.daily_limit),
            "monthly_limit": str(data.monthly_limit),
            "total_limit": str(data.total_limit),
            "version": row.version,
            "price_catalog_digest": row.price_catalog_digest,
        },
    )
    return row


def reserve(db, context, call, step_index, pricing, runtime, request):
    gate(db, context.tenant_id)
    row = policy(db, context.tenant_id)
    if not row or not row.enabled:
        raise AppError(
            409,
            "money_budget_unconfigured",
            "An enabled monetary budget is required before paid calls",
        )
    if row.price_catalog_digest != catalog(request.app.state.settings):
        raise AppError(
            409,
            "budget_price_catalog_changed",
            "An administrator must review the current price catalog",
        )
    now = datetime.now(UTC)
    if (
        not pricing
        or not pricing.get("cost_bound_verified")
        or not pricing.get("context_window_tokens")
        or not pricing.get("valid_until")
        or datetime.fromisoformat(pricing["valid_until"]) <= now
        or pricing["currency"] != row.currency
    ):
        raise AppError(
            409,
            "model_price_unbounded",
            "A current verified same-currency token cost bound is required",
        )
    # The deployment attests this model has a hard context bound and no extra
    # per-request/hidden fees. This is an INTERNAL bound, never a provider invoice.
    bound = (
        (
            Decimal(pricing["context_window_tokens"]) * Decimal(pricing["input_per_million"])
            + Decimal(runtime["max_output_tokens"]) * Decimal(pricing["output_per_million"])
        )
        / Decimal(1000000)
    ).quantize(UNIT, rounding=ROUND_CEILING)
    if runtime["max_output_tokens"] > pricing["context_window_tokens"]:
        raise AppError(
            409, "model_price_unbounded", "Output cap exceeds the reviewed context bound"
        )
    used = usage(db, context.tenant_id)
    run = usage(db, context.tenant_id, call_id=call.id)["total"]
    limits = [
        ("run", run, row.run_limit),
        *[
            (name, used[name], getattr(row, name + "_limit"))
            for name in ("daily", "monthly", "total")
        ],
    ]
    if str(call.agent_config_id) in row.agent_limits:
        limits.append(
            (
                "agent",
                usage(db, context.tenant_id, agent_id=call.agent_config_id)["total"],
                Decimal(row.agent_limits[str(call.agent_config_id)]),
            )
        )
    if any(amount + bound > maximum for _, amount, maximum in limits):
        raise AppError(
            429,
            "money_budget_exceeded",
            "Monetary budget exhausted; no provider request was dispatched",
        )
    reservation = CostReservation(
        tenant_id=context.tenant_id,
        model_call_id=call.id,
        agent_config_id=call.agent_config_id,
        step_index=step_index,
        policy_version=row.version,
        currency=row.currency,
        reserved=bound,
        charged=bound,
        pricing=pricing,
        status="RESERVED",
    )
    db.add(reservation)
    db.flush()
    record(
        db,
        request,
        "budget.reserve",
        "cost_reservation",
        reservation.id,
        tenant_id=context.tenant_id,
        details={
            "amount": str(bound),
            "currency": row.currency,
            "policy_version": row.version,
            "call_id": str(call.id),
            "step_index": step_index,
        },
    )
    return reservation.id


def settle(db, context, reservation_id, step, request):
    gate(db, context.tenant_id)
    row = get_owned(db, CostReservation, context, reservation_id, lock=True)
    if row.status != "RESERVED":
        return
    if step["attempts"] == 0:
        row.charged, row.status = Decimal(0), "RELEASED"
    elif step["usage_complete"]:
        price = row.pricing
        amount = (
            (
                Decimal(step["input_tokens"]) * Decimal(price["input_per_million"])
                + Decimal(step["output_tokens"]) * Decimal(price["output_per_million"])
            )
            / Decimal(1000000)
        ).quantize(UNIT, rounding=ROUND_CEILING)
        if (
            amount > row.reserved
            or step["input_tokens"] > price["context_window_tokens"]
            or step["output_tokens"] > price["max_output_tokens"]
        ):
            row.charged, row.status = max(amount, row.reserved), "OVERRUN"
            policy(db, context.tenant_id).enabled = False
        else:
            row.charged, row.status = amount, "SETTLED"
    else:
        row.status = "UNKNOWN"
    row.settled_at = datetime.now(UTC)
    record(
        db,
        request,
        "budget.settle",
        "cost_reservation",
        row.id,
        tenant_id=context.tenant_id,
        details={"status": row.status, "charged": str(row.charged), "currency": row.currency},
    )
