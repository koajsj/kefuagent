"""Safe query timing; never log SQL, parameters, credentials or customer text."""

import json
import logging
import time
from contextvars import ContextVar

from sqlalchemy import event

request_id = ContextVar("request_id", default=None)
logger = logging.getLogger("support_agent.database")


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
