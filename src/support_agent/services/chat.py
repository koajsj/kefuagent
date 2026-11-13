"""One bounded RAG turn. Durable reservation, no DB transaction across HTTP, no tool loop."""

import hashlib
import json
import re
import time
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import func, null, select

from support_agent.db import set_tenant
from support_agent.dependencies import resume_context
from support_agent.errors import AppError
from support_agent.models import AgentConfig, Conversation, Message, ModelCall
from support_agent.prompting import (
    BASE,
    CONNECTION_PROMPT,
    EVIDENCE_OUTPUT,
    contextual_quote,
    input_size,
)
from support_agent.providers import ProviderFailure
from support_agent.rag_schemas import (
    AnswerClaim,
    ChatOut,
    Citation,
    ConnectionReply,
    EvidenceSelection,
)
from support_agent.retrieval import reference_is_safe
from support_agent.schemas import RuntimeConfig
from support_agent.services import (
    knowledge_provenance,
    limits,
    model_runtime,
    user_memory,
    workspace,
)
from support_agent.services.audit import record
from support_agent.services.model_configs import resolve_config
from support_agent.services.resources import get_owned

SYSTEM = (
    BASE
    + "Select evidence for the customer's latest question. No tools or external actions exist.\n"
    + EVIDENCE_OUTPUT
)
UNRESOLVED = "无法从现有资料确认。请补充具体问题，或联系人工核实。"


def expire_active_calls(db, context, conversation_id, request=None):
    rows = db.scalars(
        select(ModelCall)
        .where(
            ModelCall.tenant_id == context.tenant_id,
            ModelCall.conversation_id == conversation_id,
            ModelCall.status == "running",
        )
        .with_for_update()
    ).all()
    for row in rows:
        if row.lease_expires_at <= datetime.now(UTC):
            row.status = "failed"
            row.phase = "failed"
            row.error_category = "interrupted_result_unknown"
            row.attempts = 0 if row.kind == "tool_execution" else None
            if row.kind == "agent":
                row.input_tokens = row.output_tokens = None
            if request is not None:
                record(
                    db,
                    request,
                    "model_call.reconcile",
                    "model_call",
                    row.id,
                    tenant_id=context.tenant_id,
                    outcome="failure",
                    reason=row.error_category,
                )
                from support_agent.services.tool_execution import reconcile_executions

                reconcile_executions(db, context, request, call_id=row.id)
        else:
            raise AppError(
                409,
                "conversation_busy",
                "A model turn is active; retry later with the same idempotency key",
            )
    db.flush()


def output(call, request_id, answer="", citations=None, status=None, error=None):
    citations = citations or []
    return ChatOut(
        answer=answer,
        citations=citations,
        grounded=bool(citations),
        status=status or call.status,
        conversation_id=call.conversation_id,
        call_id=call.id,
        request_id=request_id,
        error_category=error or call.error_category,
    )


def replay(db, context, call, request):
    user_memory.ensure_delivery(db, context, call, lock=True)
    if call.status == "running":
        if call.lease_expires_at <= datetime.now(UTC):
            call.status = "failed"
            call.phase = "failed"
            call.error_category = "interrupted_result_unknown"
            call.attempts = None
        return output(call, request.state.request_id, error=call.error_category)
    if not call.result:
        return output(call, request.state.request_id)
    result = ChatOut.model_validate(
        {key: value for key, value in call.result.items() if key in ChatOut.model_fields}
    )
    if result.citations or call.kind == "chat":
        from support_agent.services import agent_turns

        if not agent_turns.current_citations(
            db, context, call, request, workspace.knowledge_ids(db, context, call.agent_config_id)
        ):
            return output(
                call,
                request.state.request_id,
                UNRESOLVED,
                status="unresolved",
                error="evidence_changed",
            )
    return result.model_copy(update={"request_id": request.state.request_id})


def history_messages(db, context, conversation_id, request, *, calls=None, knowledge_base_ids=None):
    calls = (
        calls
        if calls is not None
        else db.scalars(
            select(ModelCall)
            .where(
                ModelCall.tenant_id == context.tenant_id,
                ModelCall.conversation_id == conversation_id,
                ModelCall.kind == "chat",
                ModelCall.status.in_(["answered", "unresolved"]),
            )
            .order_by(ModelCall.created_at.desc(), ModelCall.id.desc())
            .limit(4)
        ).all()
    )
    items = []
    dependencies = set()
    for call in reversed(calls):
        pair = db.scalars(
            select(Message)
            .where(
                Message.tenant_id == context.tenant_id,
                Message.model_call_id == call.id,
                Message.source == "rag",
            )
            .order_by(Message.created_at, Message.id)
        ).all()
        if len(pair) == 2 and [m.role for m in pair] == ["user", "assistant"]:
            items.append({"role": "user", "content": pair[0].content})
            from support_agent.services.agent_turns import current_citations

            allowed = (
                knowledge_base_ids
                if knowledge_base_ids is not None
                else workspace.knowledge_ids(db, context, call.agent_config_id)
            )
            if not (call.result or {}).get("user_memory_dependencies") and current_citations(
                db, context, call, request, allowed, current_only=True
            ):
                dependencies |= knowledge_provenance.sources(call)
                items.append({"role": "assistant", "content": pair[1].content})
    return items, dependencies


def history_rounds(history):
    rounds = []
    for message in history:
        if message["role"] == "user":
            rounds.append([message])
        elif message["role"] == "assistant" and rounds and len(rounds[-1]) == 1:
            rounds[-1].append(message)
    return rounds


def prompt_messages(
    question,
    evidence,
    preferences,
    history,
    budget,
    *,
    retrieval_query=None,
    remembered=None,
    system=None,
    tools=None,
    staff_replies_after_question=None,
):
    # UTF-8 bytes conservatively bound byte-BPE tokens; not provider-reported usage.
    # JSON escaping and an explicit per-message framing reserve are included.
    payload = {
        "question": question,
        "company_preferences": preferences,
        "evidence": [{"chunk_id": str(hit.chunk_id), "content": hit.content} for hit in evidence],
    }
    if retrieval_query is not None and retrieval_query != question:
        payload["retrieval_query_context"] = retrieval_query
    if staff_replies_after_question:
        # Keep later staff replies out of earlier user/assistant history pairs.
        # Preserve complete messages under the same required-input budget.
        payload["staff_replies_after_question"] = staff_replies_after_question
    tail = {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
    messages = [
        {
            "role": "system",
            "content": system
            if system is not None
            else SYSTEM + synthesis_instructions(preferences),
        },
        tail,
    ]

    def size(items):
        return input_size(items, tools)

    while size(messages) > budget and payload["evidence"]:
        payload["evidence"].pop()
        tail["content"] = json.dumps(payload, ensure_ascii=False)
    if size(messages) > budget:
        raise AppError(
            422,
            "input_budget_exceeded",
            "Required question context and preferences exceed the configured input budget",
        )
    selected = []
    for pair in reversed(history_rounds(history)):
        proposed = [messages[0], *pair, *selected, tail]
        if size(proposed) > budget:
            break
        selected = pair + selected
    final = [messages[0], *selected, tail]
    if remembered:
        payload["user_memory"] = remembered
        tail["content"] = json.dumps(payload, ensure_ascii=False)
        if size(final) > budget:
            payload.pop("user_memory")
            tail["content"] = json.dumps(payload, ensure_ascii=False)
    return final, {item["chunk_id"] for item in payload["evidence"]}


_FOLLOWUP = re.compile(
    r"^(?:(?:那|那么)[，, ]*)?(?:它|这个|那个|上述|前者|后者|其)(?:的|呢|[，,？? ]|$)"
    r"|^(?:what about|how about|and\b|that\b|those\b|does it|is it|can it|its\b)",
    re.IGNORECASE,
)


def retrieval_question(question, history):
    """Bounded lexical follow-up expansion from the last user question, never assistant claims."""
    if len(question) >= 80 or not _FOLLOWUP.search(question.strip()):
        return question
    previous = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    # Do not silently truncate a condition in a large previous question.
    if not previous or len(previous) > 600:
        return question
    # query_groups is capped: the latest question must get its lexical groups first.
    return question + "\n" + previous


def evidence_answer(citations, reason=None):
    if not citations:
        return (
            "现有资料存在相互冲突的说明，无法确认哪一条适用，请联系人工核实。"
            if reason == "conflicting_evidence"
            else UNRESOLVED
        )
    return "根据当前资料，相关原文如下（请核实适用条件）：\n\n" + "\n\n".join(
        f"{item.quote} [{n}]" for n, item in enumerate(citations, 1)
    )


def synthesis_instructions(preferences):
    if preferences.get("answer_mode") != "evidence_synthesis":
        return ""
    return "\nOptional claims: at most 6 objects {statement:sentence of 1..600 characters in the requested language,kind:fact|inference|uncertain,chunk_ids:[1..3 distinct supplied UUIDs]}. Every claim needs evidence IDs selected in citations. Combine complementary sources, preserve exceptions and negation, explicitly label inference and uncertainty. Never invent policy or promises. These claims are unverified drafts; the server retains original extracts and does not mark their semantics grounded."


def compose_answer(completion, citations, reason, preferences):
    """Structural provenance only. Free-form semantics are explicitly unverified."""
    extract = evidence_answer(citations, reason)
    if not citations or preferences.get("answer_mode") != "evidence_synthesis" or not completion:
        return extract, "verified_extracts", []
    try:
        raw = json.loads(completion.content).get("claims", [])
        if not isinstance(raw, list) or not 1 <= len(raw) <= 6:
            return extract, "verified_extracts", []
        claims = [AnswerClaim.model_validate(item) for item in raw]
        sources = {item.chunk_id: n for n, item in enumerate(citations, 1)}
        from support_agent.services.memory import sensitive

        if any(
            not set(claim.chunk_ids).issubset(sources)
            or len(set(claim.chunk_ids)) != len(claim.chunk_ids)
            or sensitive(claim.statement)
            or not reference_is_safe(claim.statement)
            for claim in claims
        ):
            return extract, "verified_extracts", []
    except (ValidationError, ValueError, AttributeError, TypeError):
        return extract, "verified_extracts", []
    labels = {
        "fact": "资料综合（未做语义核验）",
        "inference": "推断（待核实）",
        "uncertain": "不确定",
    }
    lines = [
        f"{labels[claim.kind]}：{claim.statement} "
        + " ".join(f"[{sources[cid]}]" for cid in claim.chunk_ids)
        for claim in claims
    ]
    return (
        "以下为基于所列资料的综合草稿，事实与引用的语义关系尚未经核验，请结合原文确认：\n\n"
        + "\n\n".join(lines)
        + "\n\n"
        + extract,
        "evidence_synthesis_unverified",
        claims,
    )


def verify_selection(db, context, completion, evidence, request):
    if completion.refused or completion.tool_calls:
        return [], "invalid_grounding"
    try:
        raw = json.loads(completion.content)
        raw.pop("claims", None)
        selection = EvidenceSelection.model_validate(raw)
    except (ValidationError, ValueError, AttributeError, TypeError):
        return [], "invalid_grounding"
    if selection.conflict:
        return [], "conflicting_evidence"
    if not selection.answerable or not selection.citations:
        return [], "insufficient_evidence"
    by_id = {hit.chunk_id: hit for hit in evidence}
    current = request.app.state.retriever.current_chunks(
        db, context, [item.chunk_id for item in selection.citations], lock=True, current_only=True
    )
    citations = []
    seen = set()
    for selected in selection.citations:
        hit = by_id.get(selected.chunk_id)
        actual = current.get(selected.chunk_id)
        if (
            not hit
            or not actual
            or actual[0].generation != hit.generation
            or selected.quote not in actual[0].content
            or selected.quote not in hit.content
            or not reference_is_safe(actual[0].content)
        ):
            return [], "invalid_grounding"
        quote = contextual_quote(actual[0].content, selected.quote)
        if quote is None or quote not in hit.content:
            return [], "incomplete_quote_context"
        if (selected.chunk_id, quote) in seen:
            continue
        seen.add((selected.chunk_id, quote))
        citations.append(
            Citation(
                document_id=hit.document_id,
                document_name=actual[1].filename,
                chunk_id=hit.chunk_id,
                quote=quote,
                page=hit.page,
                section=hit.section,
            )
        )
    return citations, None


def conflicting_claims(evidence):
    # Conservative only: equal explicit labels with different values in different sources.
    # This is not general semantic contradiction detection.
    claims = {}
    for hit in evidence:
        for key, value in re.findall(
            r"([㐀-鿿A-Za-z][㐀-鿿A-Za-z _]{1,24})[：:]\s*([^\n。；;]{1,120})", hit.content
        ):
            key = key.strip().lower()
            value = value.strip().lower()
            previous = claims.get(key)
            if previous and previous[0] != hit.document_id and previous[1] != value:
                return True
            claims[key] = (hit.document_id, value)
    return False


def turn(db, context, conversation_id, data, request):
    conversation = get_owned(db, Conversation, context, conversation_id, lock=True)
    if conversation.channel == "public":
        raise AppError(
            409,
            "public_conversation_requires_visitor",
            "Use the visitor entry for public AI replies",
        )
    digest = hashlib.sha256(
        json.dumps(
            data.model_dump(
                mode="json", exclude={"idempotency_key", *(["task"] if data.task == "auto" else [])}
            ),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    existing = db.scalar(
        select(ModelCall).where(
            ModelCall.tenant_id == context.tenant_id,
            ModelCall.conversation_id == conversation_id,
            ModelCall.idempotency_key == data.idempotency_key,
        )
    )
    if existing:
        if existing.kind != "chat" or existing.input_digest != digest:
            raise AppError(
                409,
                "idempotency_conflict",
                "Idempotency key is already associated with different input",
            )
        return replay(db, context, existing, request)
    expire_active_calls(db, context, conversation_id, request)
    if conversation.status != "open":
        raise AppError(
            409, "conversation_closed", "Closed conversations cannot receive new messages"
        )
    if conversation.support_state != "ai":
        raise AppError(409, "human_handling_active", "AI replies are paused for human handling")
    config = get_owned(db, AgentConfig, context, data.agent_config_id, lock=True)
    if not set(data.knowledge_base_ids).issubset(workspace.knowledge_ids(db, context, config.id)):
        raise AppError(
            403, "knowledge_not_authorized", "Select knowledge bases authorized for this Agent"
        )
    provider_input = {"runtime": RuntimeConfig.model_validate(config.runtime).model_dump()}
    call = ModelCall(
        tenant_id=context.tenant_id,
        created_by=context.user_id,
        conversation_id=conversation_id,
        agent_config_id=config.id,
        config_version=config.version,
        model=config.model,
        kind="chat",
        idempotency_key=data.idempotency_key,
        input_digest=digest,
        request_id=request.state.request_id,
        status="running",
        attempts=null(),
        lease_expires_at=datetime.now(UTC)
        + timedelta(seconds=provider_input["runtime"]["timeout_seconds"] + 30),
    )
    db.add(call)
    knowledge_provenance.initialize(call)
    db.flush()
    call_id = call.id
    limits.admit(
        db, context, call, request, provider_input["runtime"], offline=config.provider == "demo"
    )
    call.phase = "retrieving"
    db.add(
        Message(
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            created_by=context.user_id,
            role="user",
            content=data.content,
            created_at=func.clock_timestamp(),
            source="rag",
            model_call_id=call_id,
            message_metadata={},
        )
    )
    record(db, request, "model_call.start", "model_call", call_id, tenant_id=context.tenant_id)
    db.commit()
    started = time.monotonic()
    deadline = started + provider_input["runtime"]["timeout_seconds"]
    try:
        context = resume_context(db, context, request)
        from support_agent.observability import phase_span

        with phase_span(db, context, request, call_id, "context"):
            history, inherited_sources = history_messages(
                db, context, conversation_id, request, knowledge_base_ids=data.knowledge_base_ids
            )
        retrieval_query = retrieval_question(data.content, history)
        with phase_span(db, context, request, call_id, "retrieval"):
            from support_agent.services.search import run as retrieve

            evidence = retrieve(
                db,
                context,
                data.knowledge_base_ids,
                retrieval_query,
                request,
                call_id=call_id,
                deadline=deadline,
            )["final"]
        with phase_span(db, context, request, call_id, "memory"):
            remembered, memory_dependencies = user_memory.load_payload(
                db, context, query=retrieval_query
            )
        messages, sent_ids = prompt_messages(
            data.content,
            evidence,
            config.behavior,
            history,
            provider_input["runtime"]["max_input_tokens"],
            retrieval_query=retrieval_query,
            remembered=remembered,
        )
        evidence = [hit for hit in evidence if str(hit.chunk_id) in sent_ids]
        call = get_owned(db, ModelCall, context, call_id)
        retained_memory = json.loads(messages[-1]["content"]).get("user_memory")
        call.result = (call.result or {}) | {
            "user_memory_dependencies": memory_dependencies if retained_memory else []
        }
        knowledge_provenance.bind(call, inherited_sources | {hit.chunk_id for hit in evidence})
        db.commit()
    except AppError as exc:
        db.rollback()
        set_tenant(db, context.tenant_id)
        call = get_owned(db, ModelCall, context, call_id, lock=True)
        call.status = call.phase = "failed"
        call.error_category = exc.code
        if not call.steps:
            call.attempts = 0
        from support_agent.observability import recover_phase_failure

        recover_phase_failure(db, context, request, call_id)
        limits.settle(call)
        record(
            db,
            request,
            "model_call.finish",
            "model_call",
            call_id,
            tenant_id=context.tenant_id,
            outcome="failure",
            reason=exc.code,
        )
        db.commit()
        raise
    conflict = conflicting_claims(evidence)
    completion = None
    failure = None
    if evidence and not conflict:
        try:
            completion = model_runtime.complete(
                db,
                context,
                call_id,
                request,
                messages=messages,
                task=data.task if data.task != "auto" else model_runtime.infer_task(data.content),
                purpose="rag_answer",
                prompt_id="rag.selection",
                timeout=int(deadline - time.monotonic()),
            )
        except ProviderFailure as exc:
            failure = exc
        except Exception:
            # Unknown provider exceptions cannot expose exception text, keys or raw responses.
            failure = ProviderFailure("provider_internal_error", attempts=None)
    elapsed = int((time.monotonic() - started) * 1000)
    context = resume_after_call(db, context, request, call_id, elapsed, completion, failure)
    conversation = get_owned(db, Conversation, context, conversation_id, lock=True)
    call = get_owned(db, ModelCall, context, call_id, lock=True)
    if call.status != "running":
        return replay(db, context, call, request)
    if completion and (reason := model_runtime.delivery_error(db, context, call, request)):
        completion, failure = None, ProviderFailure(reason, attempts=0)
    call.elapsed_ms = elapsed
    apply_usage(call, completion, failure)
    if failure:
        call.status = "failed"
        call.error_category = failure.category
        result = output(call, request.state.request_id, error=failure.category)
    else:
        citations, reason = (
            verify_selection(db, context, completion, evidence, request)
            if completion
            else ([], "conflicting_evidence" if conflict else "insufficient_evidence")
        )
        call.status = "answered" if citations else "unresolved"
        call.error_category = reason
        answer, mode, claims = compose_answer(completion, citations, reason, config.behavior)
        result = output(call, request.state.request_id, answer, citations).model_copy(
            update={
                "grounded": bool(citations) and mode == "verified_extracts",
                "grounding_mode": mode,
                "claims": claims,
            }
        )
        db.add(
            Message(
                tenant_id=context.tenant_id,
                conversation_id=conversation_id,
                created_by=context.user_id,
                role="assistant",
                content=answer,
                source="rag",
                model_call_id=call_id,
                message_metadata={
                    "status": call.status,
                    "grounded": result.grounded,
                    "grounding_mode": mode,
                    "citations": [item.model_dump(mode="json") for item in citations],
                },
            )
        )
    call.phase = "failed" if call.status == "failed" else "completed"
    limits.settle(call)
    call.result = (call.result or {}) | result.model_dump(mode="json")
    if call.status != "failed" and conversation.first_response_at is None:
        conversation.first_response_at = datetime.now(UTC)
    conversation.updated_at = datetime.now(UTC)
    record(
        db,
        request,
        "model_call.finish",
        "model_call",
        call_id,
        tenant_id=context.tenant_id,
        outcome="failure" if failure else "success",
        reason=call.error_category,
    )
    db.flush()
    return result


def test_connection(db, context, config_id, request):
    config = get_owned(db, AgentConfig, context, config_id)
    kwargs = resolve_config(db, context, config, request)
    kwargs["runtime"] = kwargs["runtime"] | {"max_output_tokens": 32}
    row = ModelCall(
        tenant_id=context.tenant_id,
        created_by=context.user_id,
        agent_config_id=config.id,
        config_version=config.version,
        model=config.model,
        kind="connection_test",
        request_id=request.state.request_id,
        status="running",
        attempts=null(),
        lease_expires_at=datetime.now(UTC)
        + timedelta(seconds=kwargs["runtime"]["timeout_seconds"] + 30),
    )
    db.add(row)
    db.flush()
    call_id = row.id
    limits.admit(db, context, row, request, kwargs["runtime"], offline=config.provider == "demo")
    record(
        db, request, "model_connection.start", "model_call", call_id, tenant_id=context.tenant_id
    )
    db.commit()
    started = time.monotonic()
    completion = None
    failure = None
    try:
        completion = model_runtime.complete(
            db,
            context,
            call_id,
            request,
            messages=[{"role": "user", "content": CONNECTION_PROMPT}],
            task="qa",
            timeout=kwargs["runtime"]["timeout_seconds"],
            max_output_tokens=32,
            purpose="connection_check",
            prompt_id="provider.connection",
        )
    except ProviderFailure as exc:
        failure = exc
    except Exception:
        failure = ProviderFailure("provider_internal_error", attempts=None)
    kwargs["api_key"] = ""
    elapsed = int((time.monotonic() - started) * 1000)
    resume_after_call(db, context, request, call_id, elapsed, completion, failure, admin=True)
    row = get_owned(db, ModelCall, context, call_id, lock=True)
    if row.status != "running":
        return row
    if completion and (reason := model_runtime.delivery_error(db, context, row, request)):
        completion, failure = None, ProviderFailure(reason, attempts=0)
    if completion and not failure:
        try:
            ConnectionReply.model_validate_json(completion.content)
        except ValidationError:
            failure = ProviderFailure("invalid_response", attempts=completion.attempts)
    row.status = "failed" if failure else "connected"
    row.error_category = failure.category if failure else None
    row.elapsed_ms = int((time.monotonic() - started) * 1000)
    apply_usage(row, completion, failure)
    row.phase = "failed" if failure else "completed"
    limits.settle(row)
    record(
        db,
        request,
        "model_connection.finish",
        "model_call",
        call_id,
        tenant_id=context.tenant_id,
        outcome="failure" if failure else "success",
        reason=row.error_category,
    )
    db.flush()
    return row


def apply_usage(row, completion, failure):
    if row.steps:
        return
    if completion:
        row.input_tokens = completion.input_tokens
        row.output_tokens = completion.output_tokens
        row.attempts = completion.attempts
    elif failure:
        row.input_tokens = failure.input_tokens
        row.output_tokens = failure.output_tokens
        row.attempts = failure.attempts
    else:
        row.attempts = 0  # No evidence: no transport was invoked.


def resume_after_call(db, context, request, call_id, elapsed, completion, failure, *, admin=False):
    try:
        return resume_context(db, context, request, admin=admin)
    except AppError:
        # The engine may finish accounting for its own reservation after the caller loses access.
        # It must not persist an assistant message or return a model response to that caller.
        db.rollback()
        set_tenant(db, context.tenant_id)
        row = get_owned(db, ModelCall, context, call_id, lock=True)
        row.status = "failed"
        row.phase = "failed"
        row.error_category = "access_revoked"
        row.elapsed_ms = elapsed
        apply_usage(row, completion, failure)
        record(
            db,
            request,
            "model_call.finish",
            "model_call",
            call_id,
            tenant_id=context.tenant_id,
            outcome="failure",
            reason="access_revoked",
        )
        db.commit()
        raise


def reconcile_expired(db, context, rows, request):
    for old in rows:
        if old.status == "running" and old.lease_expires_at <= datetime.now(UTC):
            row = get_owned(db, ModelCall, context, old.id, lock=True)
            if row.status != "running" or row.lease_expires_at > datetime.now(UTC):
                continue
            row.status = "failed"
            row.phase = "failed"
            row.error_category = "interrupted_result_unknown"
            row.attempts = 0 if row.kind == "tool_execution" else None
            if row.kind == "agent":
                row.input_tokens = row.output_tokens = None
            from support_agent.services.tool_execution import reconcile_executions

            reconcile_executions(db, context, request, call_id=row.id)
            record(
                db,
                request,
                "model_call.reconcile",
                "model_call",
                row.id,
                tenant_id=context.tenant_id,
                outcome="failure",
                reason=row.error_category,
            )
    db.flush()
    return rows
