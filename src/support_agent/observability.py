"""Safe query timing; never log SQL, parameters, credentials or customer text."""

import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from sqlalchemy import event

request_id = ContextVar("request_id", default=None)
logger = logging.getLogger("support_agent.database")


@contextmanager
def phase_span(db, context, request, call_id, phase):
    """Record only server phase/timing in the existing transaction, never input data."""
    from support_agent.services.audit import record

    if phase not in {"context", "retrieval", "memory"}:
        raise ValueError("Unknown observation phase")
    started_at = datetime.now(UTC)
    started = time.monotonic()
    outcome = "success"
    phase_status = "SUCCEEDED"
    error_category = None
    try:
        yield
    except TimeoutError:
        outcome = "failure"
        phase_status = "TIMED_OUT"
        error_category = "timeout"
        raise
    except Exception as exc:
        outcome = "failure"
        code = getattr(exc, "code", None) or getattr(exc, "category", None)
        error_category = (
            code
            if code
            in {
                "timeout",
                "forbidden",
                "unauthorized",
                "credential_changed",
                "credential_unavailable",
                "user_memory_changed",
                "execution_interrupted",
                "interrupted_result_unknown",
                "knowledge_changed",
                "agent_changed",
            }
            else "phase_failed"
        )
        phase_status = (
            "TIMED_OUT"
            if code == "timeout"
            else "INTERRUPTED"
            if code in {"execution_interrupted", "interrupted_result_unknown"}
            else "FAILED"
        )
        raise
    except BaseException:
        # Cancellation/termination which unwinds Python is not a successful span.
        # An abrupt process kill cannot persist anything and remains UNKNOWN.
        outcome = "failure"
        phase_status = "INTERRUPTED"
        error_category = "execution_interrupted"
        raise
    finally:
        details = {
            "phase": phase,
            "phase_status": phase_status,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "error_category": error_category,
        }
        if outcome != "success":
            # Preserve only content-free metadata for the existing rollback/finish
            # path. No independent transaction, commit or exception text is added.
            request.state.failed_phase = (call_id, details, outcome)
        record(
            db,
            request,
            "model_call.phase",
            "model_call",
            call_id,
            tenant_id=context.tenant_id,
            outcome=outcome,
            reason=error_category,
            details=details,
        )


def recover_phase_failure(db, context, request, call_id):
    """Called only in the failure accounting transaction after an explicit rollback."""
    from support_agent.services.audit import record

    failure = getattr(request.state, "failed_phase", None)
    if failure and failure[0] == call_id:
        record(
            db,
            request,
            "model_call.phase",
            "model_call",
            call_id,
            tenant_id=context.tenant_id,
            outcome=failure[2],
            reason=failure[1].get("error_category"),
            details=failure[1],
        )
        request.state.failed_phase = None


def instrument(engine):
    @event.listens_for(engine, "before_cursor_execute")
    def before(connection, cursor, statement, parameters, context, many):
        if logger.isEnabledFor(logging.DEBUG):
            context.support_started = time.monotonic()

    def emit(context, outcome):
        if context is not None and hasattr(context, "support_started"):
            logger.debug(
                json.dumps(
                    {
                        "event": "database_operation",
                        "request_id": request_id.get(),
                        "outcome": outcome,
                        "elapsed_ms": round((time.monotonic() - context.support_started) * 1000, 3),
                    }
                )
            )

    @event.listens_for(engine, "after_cursor_execute")
    def after(connection, cursor, statement, parameters, context, many):
        emit(context, "ok")

    @event.listens_for(engine, "handle_error")
    def failed(context):
        emit(context.execution_context, "failed")
