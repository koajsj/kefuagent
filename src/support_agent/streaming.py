"""SSE delivery of authorized committed answers; never raw model reasoning/tool arguments."""

import asyncio
import json
import logging
import time
from queue import Empty, Queue

from fastapi import Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from support_agent.dependencies import resume_context
from support_agent.errors import AppError
from support_agent.models import ModelCall
from support_agent.services import agent_turns, model_runtime, public_delivery
from support_agent.services.audit import record_failure
from support_agent.services.resources import get_owned


def frame(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def response(request, context, conversation_id, data, *, public=False):
    # This worker owns its Session. The request dependency closes before response I/O.
    queue = Queue(maxsize=64)
    scope = dict(request.scope)
    scope["state"] = dict(scope.get("state", {})) | {"stream_events": queue}
    work_request = Request(scope)

    def work():
        try:
            with request.app.state.sessions() as db:
                current = resume_context(db, context, work_request)
                result = (
                    public_delivery.turn(db, current, data, work_request)
                    if public
                    else agent_turns.turn(db, current, conversation_id, data, work_request)
                )
                db.commit()
                return {"call_id": result.call_id}
        except AppError as exc:
            try:
                with request.app.state.sessions.begin() as db:
                    record_failure(db, work_request, exc.code)
            except SQLAlchemyError:
                logging.getLogger("support_agent").error(
                    json.dumps(
                        {"event": "stream_audit_unavailable", "request_id": str(context.request_id)}
                    )
                )
            return {"error_category": exc.code, "result_unknown": False}
        except Exception:
            # Any interrupted durable reservation is reconciled by its existing lease mechanism.
            return {"error_category": "interrupted_result_unknown", "result_unknown": True}

    def snapshot(call_id):
        with request.app.state.sessions.begin() as db:
            current = resume_context(db, context, work_request)
            call = get_owned(db, ModelCall, current, call_id)
            if call.status != "failed" and (
                reason := model_runtime.delivery_error(db, current, call)
            ):
                raise AppError(409, reason, "Stream delivery is no longer authorized")
            return agent_turns.output(db, current, call, work_request).model_dump(mode="json")

    async def events():
        yield frame("stage", {"phase": "pending", "request_id": str(context.request_id)})
        # Shield lifetime from the streaming consumer: disconnect never cancels/restarts execution.
        jobs = request.app.state.stream_jobs
        if len(jobs) >= 32:
            yield frame(
                "failed", {"error_category": "stream_capacity_exceeded", "result_unknown": False}
            )
            return
        job = asyncio.create_task(asyncio.to_thread(work))
        jobs.add(job)
        job.add_done_callback(jobs.discard)
        started = time.monotonic()
        heartbeat = started
        while not job.done():
            try:
                while True:
                    event, value = queue.get_nowait()
                    # Stage names contain no payload; authorization is checked again before answer I/O.
                    yield frame(event, value)
            except Empty:
                pass
            now = time.monotonic()
            if now - started > 140:
                yield frame(
                    "timed_out", {"error_category": "delivery_timeout", "result_unknown": True}
                )
                return
            if now - heartbeat > 10:
                yield ": keepalive\n\n"
                heartbeat = now
            await asyncio.sleep(0.03)
        try:
            while True:
                event, value = queue.get_nowait()
                yield frame(event, value)
        except Empty:
            pass
        try:
            result = job.result()
        except Exception:
            yield frame(
                "failed", {"error_category": "interrupted_result_unknown", "result_unknown": True}
            )
            return
        if "error_category" in result:
            yield frame("failed", result)
            return
        try:
            final = await asyncio.to_thread(snapshot, result["call_id"])
            if final["status"] == "running":
                yield frame("pending", {"call_id": final["call_id"], "result_unknown": True})
                return
            if final["status"] == "failed":
                event = "timed_out" if "timeout" in (final["error_category"] or "") else "failed"
                yield frame(event, final)
                return
            answer = final["answer"]
            # Buffer before checking: release at most 2048 characters per fresh snapshot.
            # Backpressure can delay resumption; time is checked before any further payload.
            buffered = ""
            checked_at = time.monotonic()
            for offset in range(0, len(answer), 128):
                buffered += answer[offset : offset + 128]
                if len(buffered) < 2048 and time.monotonic() - checked_at < 0.25:
                    continue
                if await request.is_disconnected():
                    return
                current = await asyncio.to_thread(snapshot, result["call_id"])
                if current != final:
                    yield frame(
                        "failed", {"error_category": "delivery_changed", "discard_deltas": True}
                    )
                    return
                checked_at = time.monotonic()
                yield frame("delta", {"text": buffered, "call_id": final["call_id"]})
                buffered = ""
            # One final revocation/source check; no database transaction survives a yield.
            if await asyncio.to_thread(snapshot, result["call_id"]) != final:
                yield frame(
                    "failed", {"error_category": "delivery_changed", "discard_deltas": True}
                )
                return
            if buffered:
                yield frame("delta", {"text": buffered, "call_id": final["call_id"]})
                if await asyncio.to_thread(snapshot, result["call_id"]) != final:
                    yield frame(
                        "failed", {"error_category": "delivery_changed", "discard_deltas": True}
                    )
                    return
            yield frame("completed", final)
        except AppError as exc:
            yield frame("failed", {"error_category": exc.code, "discard_deltas": True})
        except SQLAlchemyError:
            yield frame(
                "failed",
                {
                    "error_category": "delivery_unavailable",
                    "result_unknown": True,
                    "discard_deltas": True,
                },
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )
