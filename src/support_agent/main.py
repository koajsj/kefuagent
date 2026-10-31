import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from support_agent.api import (
    agents,
    audit,
    conversations,
    identity,
    knowledge,
    model_access,
    public_delivery,
    tenants,
    tools,
    workspace,
)
from support_agent.config import Settings
from support_agent.db import build_database, check_database
from support_agent.dependencies import Database
from support_agent.errors import AppError
from support_agent.observability import request_id as request_id_context
from support_agent.providers import OpenAICompatibleProvider
from support_agent.retrieval import PostgresFTSRetriever
from support_agent.schemas import ErrorOut
from support_agent.services.audit import record_failure
from support_agent.storage import LocalDocumentStorage
from support_agent.tool_runtime import ProcessToolRunner, default_registry

logger = logging.getLogger("support_agent")


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    engine, sessions = build_database(settings)

    @asynccontextmanager
    async def lifespan(app):
        # A missing or unsafe database is a startup failure, never silent SQLite fallback.
        try:
            await run_in_threadpool(check_database, engine)
        except (SQLAlchemyError, RuntimeError):
            engine.dispose()
            raise RuntimeError(
                "Database unavailable, unsafe role or pending migration; check local setup"
            ) from None
        try:
            yield
        finally:
            if app.state.stream_jobs:
                await asyncio.gather(*list(app.state.stream_jobs), return_exceptions=True)
            if app.state.ingress_jobs:
                await asyncio.gather(*list(app.state.ingress_jobs), return_exceptions=True)
            engine.dispose()

    app = FastAPI(
        title="通用多租户客服平台",
        version=version("support-agent-platform"),
        lifespan=lifespan,
        description="Tenant-scoped knowledge, verified-extract RAG and bounded, authorized read-only tool execution.",
        responses={
            code: {"model": ErrorOut} for code in [401, 403, 404, 409, 413, 422, 429, 500, 503]
        },
    )
    from support_agent.http_limits import IngressMiddleware

    app.state.ingress_jobs = set()
    app.state.stream_jobs = set()
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.storage = LocalDocumentStorage(settings.document_storage_root)
    app.state.provider = OpenAICompatibleProvider(
        settings.model_allowed_hosts, enabled=settings.allow_external_models
    )
    from support_agent.demo_provider import DemoProvider

    app.state.demo_provider = DemoProvider()
    app.state.retriever = PostgresFTSRetriever()
    app.state.tool_registry = default_registry()
    app.state.tool_runner = ProcessToolRunner()

    @app.middleware("http")
    async def trace(request: Request, call_next):
        started = time.monotonic()
        request.state.request_id = getattr(request.state, "request_id", None) or uuid4()
        request_id_context.set(str(request.state.request_id))
        upload_path = request.method == "POST" and re.fullmatch(
            r"/api/v1/knowledge-bases/[0-9a-fA-F-]{36}/documents", request.url.path
        )
        limit = 5 * 1024 * 1024 + 65536 if upload_path else 131072
        size = 0
        parts = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                return await error_response(
                    request, 413, "request_too_large", "Request body exceeds the route size limit"
                )
            parts.append(chunk)
        # Starlette's cached Request body is reused by call_next; no second read or logging.
        request._body = b"".join(parts)
        try:
            response = await call_next(request)
        except Exception:
            # This boundary prevents ASGI server traceback logging of arbitrary exception values.
            logger.error("unexpected error request_id=%s", request.state.request_id)
            response = await error_response(
                request, 500, "internal_error", "Unexpected server error"
            )
        response.headers["X-Request-ID"] = str(request.state.request_id)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path == "/" or request.url.path.startswith(("/chat/", "/assets/")):
            ancestors = "*" if request.url.path.startswith("/chat/") else "'none'"
            response.headers["Content-Security-Policy"] = (
                f"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors {ancestors}"
            )

        route = request.scope.get("route")
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": str(request.state.request_id),
                    "method": request.method,
                    "route": getattr(route, "path", "unmatched"),
                    "status": response.status_code,
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                }
            )
        )
        return response

    async def error_response(request, status, code, message):
        if not getattr(request.state, "audit_handled", False) and (
            request.method in {"POST", "PUT", "PATCH", "DELETE"} or status in {401, 403}
        ):

            def write_failure():
                try:
                    with sessions.begin() as db:
                        record_failure(db, request, code)
                except SQLAlchemyError:
                    logger.error("audit unavailable request_id=%s", request.state.request_id)

            await run_in_threadpool(write_failure)
        return JSONResponse(
            status_code=status,
            content={
                "error": {"code": code, "message": message},
                "request_id": str(request.state.request_id),
            },
            headers={
                "X-Request-ID": str(request.state.request_id),
                **({"WWW-Authenticate": "Bearer"} if status == 401 else {}),
            },
        )

    @app.exception_handler(AppError)
    async def domain_error(request, exc):
        return await error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # No Pydantic `input`, `ctx`, field names or values that may contain secrets.
        return await error_response(request, 422, "validation_error", "Request validation failed")

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return await error_response(
            request,
            409,
            "resource_conflict",
            "Resource conflicts with existing data or relationships",
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return await error_response(
            request, 503, "database_unavailable", "Database operation unavailable; retry later"
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return await error_response(
            request, exc.status_code, "http_error", "Request cannot be processed"
        )

    router = APIRouter(prefix="/api/v1")

    @router.get("/health", tags=["Health"])
    def health(db: Database):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    @router.get("/health/live", tags=["Health"])
    def live():
        return {"status": "alive"}

    @router.get("/health/ready", tags=["Health"])
    def ready():
        try:
            check_database(engine)
        except (SQLAlchemyError, RuntimeError):
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return {"status": "ready"}

    @router.get("/health/setup", tags=["Health"])
    def setup_health():
        from support_agent.preflight import inspect

        result = inspect(settings, engine)
        configured = result["ready"] and result["setup_complete"]
        return JSONResponse(
            {"status": "configured" if configured else "setup_required"},
            status_code=200 if configured else 503,
        )

    for module in [
        identity,
        tenants,
        agents,
        conversations,
        tools,
        audit,
        knowledge,
        model_access,
        workspace,
        public_delivery,
    ]:
        router.include_router(module.router)
    app.include_router(router)
    web = Path(__file__).parent / "web"
    app.mount("/assets", StaticFiles(directory=web), name="web-assets")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(web / "index.html")

    @app.get("/chat/{pid}", include_in_schema=False)
    def public_chat(pid: UUID):
        return FileResponse(web / "public.html")

    @app.get("/widget.js", include_in_schema=False)
    def widget():
        return FileResponse(web / "widget.js", media_type="text/javascript")

    app.add_middleware(
        IngressMiddleware, sessions=sessions, settings=settings, pending=app.state.ingress_jobs
    )
    return app
