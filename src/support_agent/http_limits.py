"""Opt-in PostgreSQL ingress counters and leased SSE slots, shared by all instances."""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from uuid import uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from starlette.responses import JSONResponse

from support_agent.errors import AppError
from support_agent.models import HttpBucket

logger = logging.getLogger("support_agent")


def acquire(sessions, secret, ip, category, limits, stream=False):
    token = uuid4().hex
    keys = [("all:" + ip, limits.http_requests_per_minute)]
    if category != "all":
        keys.append((category + ":" + ip, getattr(limits, "http_" + category + "_per_minute")))
    if stream:
        keys.append(("sse-global", 1000000000))
    keys = sorted(
        (
            hmac.new(secret.encode(), key.encode(), hashlib.sha256).hexdigest(),
            cap,
            limits.http_sse_global_connections
            if key == "sse-global"
            else limits.http_sse_ip_connections,
        )
        for key, cap in keys
    )
    leased = []
    with sessions.begin() as db:
        now = float(db.scalar(text("SELECT extract(epoch FROM clock_timestamp())")))
        for key, cap, slots in keys:
            db.execute(insert(HttpBucket).values(key=key, state={}).on_conflict_do_nothing())
            row = db.scalar(select(HttpBucket).where(HttpBucket.key == key).with_for_update())
            state = row.state
            window = state.get("window", now)
            count = state.get("count", 0) if now - window < 60 else 0
            active = {k: expiry for k, expiry in state.get("leases", {}).items() if expiry > now}
            if count >= cap or (stream and len(active) >= slots):
                raise AppError(429, "http_limit_exceeded", "Ingress limit reached; retry later")
            if stream:
                active[token] = now + 240
                leased.append(key)
            row.state = {
                "window": window if now - window < 60 else now,
                "count": count + 1,
                "leases": active,
            }
            row.updated_at = func.now()
        # Expired ingress state only; no customer or audit records are touched.
        stale = (
            select(HttpBucket.key)
            .where(HttpBucket.updated_at < func.now() - text("interval '30 minutes'"))
            .order_by(HttpBucket.key)
            .limit(50)
            .with_for_update(skip_locked=True)
        )
        db.execute(delete(HttpBucket).where(HttpBucket.key.in_(stale)))
    return token, leased


def release(sessions, token, keys):
    if not keys:
        return
    with sessions.begin() as db:
        for key in sorted(keys):
            row = db.scalar(select(HttpBucket).where(HttpBucket.key == key).with_for_update())
            if row:
                state = dict(row.state)
                state["leases"] = {k: v for k, v in state.get("leases", {}).items() if k != token}
                row.state = state


class IngressMiddleware:
    def __init__(self, app, sessions, settings, pending):
        self.app, self.sessions, self.settings, self.pending = app, sessions, settings, pending

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or not self.settings.http_limits_enabled
            or not path.startswith("/api/v1/")
            or path.startswith("/api/v1/health")
        ):
            return await self.app(scope, receive, send)
        state = scope.setdefault("state", {})
        state["request_id"] = uuid4()
        stream = path.endswith("/stream")
        category = (
            "sse"
            if stream
            else "login"
            if path in {"/api/v1/auth/login", "/api/v1/web-session"} and scope["method"] == "POST"
            else "upload"
            if scope["method"] == "POST"
            and (path.endswith("/documents") or path.endswith("/reprocess"))
            else "public"
            if path.startswith("/api/v1/public/")
            else "all"
        )
        secret = self.settings.http_rate_key or self.settings.public_rate_key
        try:
            if secret is None:
                raise AppError(503, "http_rate_key_unavailable", "Configure ingress rate key")
            admission = asyncio.create_task(
                asyncio.to_thread(
                    acquire,
                    self.sessions,
                    secret.get_secret_value(),
                    (scope.get("client") or ("unknown",))[0],
                    category,
                    self.settings,
                    stream,
                )
            )
            try:
                token, keys = await asyncio.shield(admission)
            except asyncio.CancelledError:

                async def reclaim():
                    try:
                        late_token, late_keys = await admission
                        await asyncio.to_thread(release, self.sessions, late_token, late_keys)
                    except Exception:
                        logger.warning(
                            json.dumps(
                                {
                                    "event": "ingress_release_unknown",
                                    "request_id": str(state["request_id"]),
                                }
                            )
                        )

                cleanup = asyncio.create_task(reclaim())
                self.pending.add(cleanup)
                cleanup.add_done_callback(self.pending.discard)
                raise
        except Exception as exc:
            code, status = (
                (exc.code, exc.status)
                if isinstance(exc, AppError)
                else ("ingress_unavailable", 503)
            )
            logger.warning(
                json.dumps(
                    {
                        "event": "ingress_denied",
                        "request_id": str(state["request_id"]),
                        "category": category,
                        "code": code,
                        "status": status,
                    }
                )
            )
            response = JSONResponse(
                {
                    "error": {
                        "code": code,
                        "message": "Request admission unavailable; retry later",
                    },
                    "request_id": str(state["request_id"]),
                },
                status_code=status,
                headers={
                    "X-Request-ID": str(state["request_id"]),
                    "Cache-Control": "no-store",
                    "Retry-After": "60",
                },
            )
            return await response(scope, receive, send)
        started = time.monotonic()
        try:
            if stream:
                # Shorter than the durable slot lease; disconnect cannot cancel the model worker.
                async with asyncio.timeout(150):
                    await self.app(scope, receive, send)
            else:
                await self.app(scope, receive, send)
        finally:
            try:
                await asyncio.shield(asyncio.to_thread(release, self.sessions, token, keys))
            except Exception:
                logger.warning(
                    json.dumps(
                        {"event": "ingress_release_unknown", "request_id": str(state["request_id"])}
                    )
                )
            if stream:
                logger.info(
                    json.dumps(
                        {
                            "event": "sse_closed",
                            "request_id": str(state["request_id"]),
                            "elapsed_ms": round((time.monotonic() - started) * 1000),
                        }
                    )
                )
