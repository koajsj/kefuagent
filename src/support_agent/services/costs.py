"""Deployment-priced usage estimates, never a provider invoice or a token reservation."""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator

from support_agent.schemas import Input


class ModelPrice(Input):
    provider: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=120)
    endpoint: str = Field(min_length=1, max_length=500)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    input_per_million: Decimal = Field(ge=0, max_digits=18, decimal_places=9)
    output_per_million: Decimal = Field(ge=0, max_digits=18, decimal_places=9)
    context_window_tokens: int | None = Field(default=None, ge=1, le=100000000)
    cost_bound_verified: bool = False
    valid_until: datetime | None = None
    source: str = Field(min_length=1, max_length=500)
    effective_at: datetime

    @field_validator("effective_at", "valid_until")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Price effective_at needs an explicit timezone")
        return value

    @field_validator("endpoint")
    @classmethod
    def safe_endpoint(cls, value):
        from urllib.parse import urlsplit

        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("Price endpoint must be an exact HTTPS URL without credentials")
        return value.rstrip("/")


def snapshot(settings, provider, model, endpoint, started_at):
    candidates = [
        price
        for price in settings.model_prices
        if price.provider == provider
        and price.model == model
        and price.endpoint == endpoint.rstrip("/")
        and price.effective_at <= started_at
    ]
    if not candidates:
        return None
    price = max(candidates, key=lambda p: p.effective_at)
    return price.model_dump(mode="json", exclude={"endpoint"})


def estimate(steps):
    """Unknown steps never contribute an invented zero; retain known subtotals separately."""
    subtotals = defaultdict(Decimal)
    rows = []
    unknown = 0
    for index, step in enumerate(steps):
        row = {
            key: step.get(key)
            for key in (
                "model",
                "provider",
                "purpose",
                "input_tokens",
                "output_tokens",
                "usage_complete",
                "selection_reason",
                "status",
            )
        }
        row.update(index=index, amount=None, currency=None, price_source=None)
        if step.get("attempts") == 0 and step.get("input_tokens") == step.get("output_tokens") == 0:
            row.update(amount="0", status="no_external_usage")
        elif step.get("usage_complete") and (price := step.get("pricing")) is not None:
            inputs, outputs = step.get("input_tokens"), step.get("output_tokens")
            if inputs is not None and outputs is not None:
                amount = (
                    Decimal(inputs) * Decimal(price["input_per_million"])
                    + Decimal(outputs) * Decimal(price["output_per_million"])
                ) / Decimal(1000000)
                row.update(
                    amount=str(amount),
                    currency=price["currency"],
                    price_source=price["source"],
                    price_effective_at=price["effective_at"],
                    status="estimated",
                )
                subtotals[price["currency"]] += amount
        if row["amount"] is None:
            unknown += 1
            row["status"] = "unknown_price" if step.get("usage_complete") else "unknown_usage"
        rows.append(row)
    complete = bool(steps) and unknown == 0
    return {
        "basis": "deployment_price_estimate_not_invoice",
        "complete": complete,
        "unknown_steps": unknown,
        "known_subtotals": {currency: str(amount) for currency, amount in subtotals.items()},
        "total": str(next(iter(subtotals.values()))) if complete and len(subtotals) == 1 else None,
        "currency": next(iter(subtotals)) if complete and len(subtotals) == 1 else None,
        "steps": rows,
    }
