"""Configured task routing, durable attempt accounting and conservative fallback."""

import hashlib
import time
from datetime import UTC, datetime

from sqlalchemy import select

from support_agent.db import set_tenant
from support_agent.dependencies import resume_context
from support_agent.errors import AppError
from support_agent.models import AgentConfig, ModelCall, ModelCredential
from support_agent.providers import ProviderFailure
from support_agent.schemas import ModelTarget, RuntimeConfig
from support_agent.services.model_configs import resolve_config
from support_agent.services.resources import get_owned


def select_target(config, task, require_tools):
    runtime = RuntimeConfig.model_validate(config.runtime)
    primary = ModelTarget(
        model=config.model,
        supports_tools=runtime.supports_tools,
        token_parameter=runtime.token_parameter,
        send_temperature=runtime.send_temperature,
    )
    selected = getattr(runtime.routing, task, None) or primary
    if require_tools and not selected.supports_tools:
        candidate = runtime.routing.reasoning or runtime.routing.fallback
        if candidate and candidate.supports_tools:
            return candidate, "capability:tools", runtime
    return selected, "task:" + task, runtime


def infer_task(content, *, tools=False):
    if (
        tools
        or len(content) > 800
        or any(word in content for word in ("比较", "分析", "结合", "多步"))
    ):
        return "reasoning"
    if any(word in content for word in ("提取", "识别", "列出")):
        return "extraction"
    return "qa"


def aggregate(call):
    for field in ("input_tokens", "output_tokens", "attempts"):
        values = [step.get(field) for step in call.steps]
        complete = field == "attempts" or all(step.get("attempts") != 2 for step in call.steps)
        setattr(
            call, field, sum(values) if complete and all(v is not None for v in values) else None
        )


def delivery_error(db, context, call):
    config = get_owned(db, AgentConfig, context, call.agent_config_id, lock=True)
    if not config.enabled or config.version != call.config_version:
        return "credential_or_configuration_changed"
    for step in call.steps:
        if "credential_id" not in step:
            continue
        ciphertext = db.scalar(
            select(ModelCredential.encrypted_secret)
            .where(
                ModelCredential.tenant_id == context.tenant_id,
                ModelCredential.id == step["credential_id"],
                ModelCredential.enabled.is_(True),
            )
            .with_for_update(read=True)
        )
        if (
            not ciphertext
            or hashlib.sha256(ciphertext.encode()).hexdigest() != step["credential_stamp"]
        ):
            return "credential_or_configuration_changed"
    return None


def complete(
    db,
    context,
    call_id,
    request,
    *,
    messages,
    tools=None,
    task="qa",
    timeout=None,
    max_output_tokens=None,
):
    deadline = time.monotonic() + (timeout or 120)
    first_failure = None
    for index in range(2):
        try:
            context = resume_context(db, context, request)
            call = get_owned(db, ModelCall, context, call_id, lock=True)
            config = get_owned(db, AgentConfig, context, call.agent_config_id, refresh=True)
            if (
                call.status != "running"
                or not config.enabled
                or config.version != call.config_version
            ):
                raise AppError(409, "agent_configuration_changed", "Agent changed during the call")
            target, reason, runtime = select_target(config, task, bool(tools))
            if index:
                target = runtime.routing.fallback
                if target is None:
                    raise first_failure
                reason = "fallback:" + first_failure.category
            if tools and not target.supports_tools:
                raise ProviderFailure("tools_not_supported", attempts=0)
            kwargs, stamp = resolve_config(db, context, config, request, snapshot=True)
            kwargs["model"] = target.model
            if max_output_tokens is not None:
                kwargs["runtime"]["max_output_tokens"] = min(
                    runtime.max_output_tokens, max_output_tokens
                )
            kwargs["runtime"].update(
                token_parameter=target.token_parameter, send_temperature=target.send_temperature
            )
            remaining = int(deadline - time.monotonic())
            if remaining < 1:
                raise ProviderFailure("timeout", attempts=0)
            kwargs["runtime"]["timeout_seconds"] = min(remaining, runtime.timeout_seconds)
            call.phase = "model_running"
            call.model = target.model
            step = {
                "model": target.model,
                "provider": config.provider,
                "selection_reason": reason,
                "status": "running",
                "input_tokens": None,
                "output_tokens": None,
                "attempts": None,
                "usage_complete": False,
                "error_category": None,
                "started_at": datetime.now(UTC).isoformat(),
                **(
                    {
                        "credential_id": str(stamp[0]),
                        "credential_stamp": hashlib.sha256(stamp[1].encode()).hexdigest(),
                    }
                    if stamp
                    else {}
                ),
            }
            call.steps = [*call.steps, step]
            step_index = len(call.steps) - 1
            db.commit()
        except (AppError, ProviderFailure) as exc:
            category = exc.code if isinstance(exc, AppError) else exc.category
            db.rollback()
            set_tenant(db, context.tenant_id)
            call = get_owned(db, ModelCall, context, call_id, lock=True)
            call.steps = [
                *call.steps,
                {
                    "model": call.model,
                    "selection_reason": "preflight",
                    "status": "denied",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "attempts": 0,
                    "usage_complete": True,
                    "error_category": category,
                    "elapsed_ms": 0,
                },
            ]
            aggregate(call)
            db.commit()
            raise ProviderFailure(category, attempts=0) from None
        completion = failure = None
        started = time.monotonic()
        try:
            provider = (
                request.app.state.demo_provider
                if config.provider == "demo"
                else request.app.state.provider
            )
            completion = provider.complete(messages=messages, tools=tools, **kwargs)
        except ProviderFailure as exc:
            failure = exc
        except Exception:
            failure = ProviderFailure("provider_internal_error", attempts=None)
        finally:
            kwargs["api_key"] = ""
        # Internal accounting for this server-owned reservation remains possible after revocation.
        set_tenant(db, context.tenant_id)
        call = get_owned(db, ModelCall, context, call_id, lock=True)
        item = completion or failure
        step.update(
            status="failed" if failure else "succeeded",
            input_tokens=item.input_tokens,
            output_tokens=item.output_tokens,
            attempts=item.attempts,
            error_category=failure.category if failure else None,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            usage_complete=(
                item.attempts == 1 or (config.provider == "demo" and item.attempts == 0)
            )
            and item.input_tokens is not None
            and item.output_tokens is not None,
        )
        entries = list(call.steps)
        entries[step_index] = step
        call.steps = entries
        aggregate(call)
        credential = None
        if stamp:
            credential = db.scalar(
                select(ModelCredential.encrypted_secret).where(
                    ModelCredential.tenant_id == context.tenant_id,
                    ModelCredential.id == stamp[0],
                    ModelCredential.enabled.is_(True),
                )
            )
        current = get_owned(db, AgentConfig, context, call.agent_config_id, refresh=True)
        revoked = (
            (stamp is not None and credential != stamp[1])
            or not current.enabled
            or current.version != call.config_version
        )
        db.commit()
        if revoked:
            raise ProviderFailure("credential_or_configuration_changed", attempts=0)
        if not failure:
            return completion
        fallback = runtime.routing.fallback
        if (
            index
            or failure.category not in {"model_unavailable", "tools_not_supported"}
            or not fallback
            or fallback.model == target.model
        ):
            raise failure
        first_failure = failure
    raise first_failure
