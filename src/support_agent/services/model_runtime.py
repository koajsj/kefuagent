"""Configured task routing, durable attempt accounting and conservative fallback."""

import hashlib
import time
from datetime import UTC, datetime

from sqlalchemy import select

from support_agent.autonomy import MAX_MODEL_STEPS
from support_agent.db import set_tenant
from support_agent.dependencies import locked_staff_context, resume_context
from support_agent.errors import AppError
from support_agent.models import AgentConfig, ModelCall, ModelCredential
from support_agent.prompting import input_size, metadata
from support_agent.providers import ProviderFailure
from support_agent.schemas import ModelTarget, RuntimeConfig
from support_agent.services import budgets, costs, knowledge_provenance, limits, user_memory
from support_agent.services.model_configs import resolve_config
from support_agent.services.resources import get_owned
from support_agent.stream_events import notify


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
        for candidate in (runtime.routing.reasoning, runtime.routing.fallback):
            if candidate and candidate.supports_tools:
                return candidate, "capability:tools", runtime
    return selected, "task:" + task, runtime


def infer_task(content, *, tools=False):
    # A lightweight text heuristic, not semantic classification; tool availability
    # is checked separately by select_target. Keep tools for caller compatibility.
    if len(content) > 800 or any(word in content for word in ("比较", "分析", "结合", "多步")):
        return "reasoning"
    if any(word in content for word in ("提取", "识别", "列出")):
        return "extraction"
    return "qa"


def aggregate(call):
    for field in ("input_tokens", "output_tokens", "attempts"):
        values = [step.get(field) for step in call.steps]
        complete = field == "attempts" or all(
            step.get("usage_complete", False) for step in call.steps
        )
        setattr(
            call, field, sum(values) if complete and all(v is not None for v in values) else None
        )


def delivery_error(db, context, call, request):
    try:
        user_memory.ensure_delivery(db, context, call, lock=True)
    except AppError as exc:
        return exc.code
    config = get_owned(db, AgentConfig, context, call.agent_config_id, lock=True)
    if not config.enabled or config.version != call.config_version:
        return "credential_or_configuration_changed"
    if call.kind in {"chat", "agent", "draft"} or (call.result or {}).get("knowledge_dependencies"):
        from support_agent.services import agent_turns, workspace

        if not agent_turns.current_citations(
            db,
            context,
            call,
            request,
            allowed=workspace.knowledge_ids(db, context, call.agent_config_id),
        ):
            return "evidence_changed"
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
    prompt_id,
    tools=None,
    task="qa",
    timeout=None,
    max_output_tokens=None,
    purpose="answer",
    embedding_input=None,
    embedding_model=None,
    knowledge_sources=(),
):
    if timeout is not None and timeout < 1:
        raise ProviderFailure("timeout", attempts=0)
    deadline = time.monotonic() + (120 if timeout is None else timeout)
    first_failure = None
    for index in range(1 if embedding_input is not None else 2):
        try:
            context = (
                resume_context(db, context, request)
                if context.public_session_id is not None
                else locked_staff_context(db, context, request)
            )
            call = get_owned(db, ModelCall, context, call_id, lock=True)
            # Bind newly supplied sources in the dispatch transaction. Denied
            # preflights roll back these dependencies along with reservations.
            if knowledge_sources:
                knowledge_provenance.bind(call, knowledge_sources)
            user_memory.ensure_delivery(db, context, call, lock=True)
            if reason := delivery_error(db, context, call, request):
                raise AppError(409, reason, "Model inputs are no longer authorized")
            if call.kind == "agent":
                from support_agent.services import agent_turns, tool_execution

                # Each dispatch, including fallback, must recheck tool grants and
                # snapshots after the outer loop's transaction has committed.
                tool_execution.ensure_delivery(
                    db, context, call, agent_turns.executions(db, context, call.id), request
                )
            config = get_owned(db, AgentConfig, context, call.agent_config_id, refresh=True)
            if call.kind == "embedding":
                from support_agent.services import vector_index

                lease_until = vector_index.ensure_dispatch(
                    db, context, call, request, config, embedding_model
                )
                # Reservation/commit waits consume the index lease too. Keep the
                # same monotonic deadline through the final pre-Provider check.
                deadline = min(
                    deadline, time.monotonic() + (lease_until - datetime.now(UTC)).total_seconds()
                )
            if (
                call.status != "running"
                or call.lease_expires_at <= datetime.now(UTC)
                or not config.enabled
                or config.version != call.config_version
            ):
                raise AppError(409, "agent_configuration_changed", "Agent changed during the call")
            # One agent budget includes summary, retrieval models and fallback dispatches.
            # Denied preflights made no request; running/unknown attempts keep their slot.
            if call.kind == "agent":
                # Optional context models leave one dispatch for the actual answer.
                ceiling = MAX_MODEL_STEPS - int(
                    purpose in {"summary", "query_embedding", "retrieval_rerank"}
                )
                if sum(step.get("status") != "denied" for step in call.steps) >= ceiling:
                    raise ProviderFailure("reasoning_limit_exceeded", attempts=0)
            target, reason, runtime = select_target(config, task, bool(tools))
            if embedding_input is not None:
                if config.provider == "demo" or not embedding_model:
                    raise ProviderFailure("embedding_configuration_unavailable", attempts=0)
                target = ModelTarget(model=embedding_model)
                reason = "embedding:configured_index"
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
            if embedding_input is not None:
                kwargs["embedding_input"] = embedding_input
                kwargs["runtime"]["max_output_tokens"] = 0
            size = (
                len(embedding_input.encode()) + 128
                if embedding_input is not None
                else input_size(messages, tools)
            )
            if size > runtime.max_input_tokens:
                raise ProviderFailure("input_budget_exceeded", attempts=0)
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
                "purpose": purpose,
                "task": task,
                **(metadata(prompt_id, messages) if embedding_input is None else {}),
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
            step["pricing"] = costs.snapshot(
                request.app.state.settings,
                config.provider,
                target.model,
                kwargs["base_url"],
                datetime.fromisoformat(step["started_at"]),
            )
            reservation_id = None
            if config.provider != "demo":
                if step["pricing"]:
                    step["pricing"]["max_output_tokens"] = kwargs["runtime"]["max_output_tokens"]
                reservation_id = budgets.reserve(
                    db, context, call, len(call.steps), step["pricing"], kwargs["runtime"], request
                )
                step["cost_reservation_id"] = str(reservation_id)
                step["token_reservation"] = limits.reserve_step(
                    db, context, call, request, step["pricing"], kwargs["runtime"]
                )
            else:
                step["token_reservation"] = 0
            call.steps = [*call.steps, step]
            step_index = len(call.steps) - 1
            memory_entries = user_memory.dispatched_entries(db, context, call, messages)
            db.commit()
            notify(request, "model_running")
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
                    "purpose": purpose,
                    "task": task,
                    **(metadata(prompt_id, messages) if embedding_input is None else {}),
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
        submitted_at = datetime.now(UTC)
        try:
            provider = (
                request.app.state.demo_provider
                if config.provider == "demo"
                else request.app.state.provider
            )
            remaining = min(
                deadline - time.monotonic(),
                (call.lease_expires_at - datetime.now(UTC)).total_seconds(),
            )
            if remaining < 1:
                raise ProviderFailure("timeout", attempts=0)
            kwargs["runtime"]["timeout_seconds"] = min(
                kwargs["runtime"]["timeout_seconds"], int(remaining)
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
        if memory_entries and (completion is not None or (item.attempts or 0) > 0):
            step["user_memory_used"] = memory_entries
            step["memory_submitted_at"] = submitted_at.isoformat()
            user_memory.record_use(db, context, memory_entries, submitted_at)
        # Explicitly zero attempts proves no external usage; missing usage after
        # an unknown or actual attempt must remain unknown.
        step.update(
            status="failed" if failure else "succeeded",
            finished_at=datetime.now(UTC).isoformat(),
            input_tokens=0 if item.attempts == 0 else item.input_tokens,
            output_tokens=0 if item.attempts == 0 else item.output_tokens,
            attempts=item.attempts,
            error_category=failure.category if failure else None,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            usage_complete=item.attempts == 0
            or (
                item.attempts == 1
                and item.input_tokens is not None
                and item.output_tokens is not None
            ),
        )
        if reservation_id is not None:
            budgets.settle(db, context, reservation_id, step, request)
        entries = list(call.steps)
        entries[step_index] = step
        call.steps = entries
        aggregate(call)
        limits.settle(call)
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
