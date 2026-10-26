import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from nexus_api import (
    admin,
    assurance_api,
    auth,
    campaign_api,
    center_api,
    domain,
    evaluation_api,
    live,
    proof_api,
    resource_api,
    runtime_api,
    xray_api,
)
from nexus_api.access import AccessError
from nexus_api.config import Settings, get_settings
from nexus_api.database import SCHEMA_REVISION, make_engine
from nexus_api.database_security import DatabasePrivilegeError, validate_runtime
from nexus_api.logging import configure_logging
from nexus_api.schemas import ErrorDetail, ErrorResponse, HealthResponse, ReadyResponse

logger = logging.getLogger("nexus.api")


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(
            code=code, message=message, request_id=getattr(request.state, "request_id", "unknown")
        )
    )
    return JSONResponse(status_code=status, content=body.model_dump())


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = make_engine(settings)
        from nexus_api.execution import fail_interrupted

        if app.state.engine is not None:
            try:
                with app.state.engine.connect() as connection:
                    validate_runtime(connection)
            except Exception:
                app.state.engine.dispose()
                raise RuntimeError("DATABASE_RUNTIME_VALIDATION_FAILED") from None
        stop = asyncio.Event()

        async def reconcile():
            while not stop.is_set():
                try:
                    await asyncio.to_thread(fail_interrupted, app.state.engine)
                except Exception:
                    logger.warning("runtime_recovery_unavailable")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=2)
                except TimeoutError:
                    pass

        recovery_task = asyncio.create_task(reconcile())
        logger.info("application_started")
        try:
            yield
        finally:
            stop.set()
            await recovery_task
            if app.state.engine is not None:
                app.state.engine.dispose()
            logger.info("application_stopped")

    app = FastAPI(
        title="NEXUS Foundation API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 429, 500, 503)},
    )

    app.state.settings = settings
    app.include_router(auth.router)
    app.include_router(domain.router)
    app.include_router(admin.router)
    app.include_router(evaluation_api.router)
    app.include_router(live.router)
    app.include_router(runtime_api.router)
    app.include_router(campaign_api.router)
    app.include_router(xray_api.router)
    app.include_router(proof_api.router)
    app.include_router(assurance_api.router)
    app.include_router(resource_api.router)
    app.include_router(center_api.router)

    # WebSocket frames have no HTTP response; include their actual transport schema explicitly.
    from fastapi.openapi.utils import get_openapi
    from pydantic.json_schema import models_json_schema

    from nexus_api.live import LiveFrame

    def openapi():
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            _, definitions = models_json_schema(
                [(LiveFrame, "validation")], ref_template="#/components/schemas/{model}"
            )
            for name, definition in definitions["$defs"].items():
                schema["components"]["schemas"].setdefault(name, definition)
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi

    @app.exception_handler(AccessError)
    async def access_error(request: Request, exc: AccessError):
        return error_response(request, exc.status, exc.code, exc.message)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            # Do not log exceptions, URLs, headers, bodies or DB connection strings.
            logger.error(
                "unhandled_error",
                extra={
                    "exception_type": type(exc).__name__,
                    "request_id": request.state.request_id,
                },
            )
            response = error_response(request, 500, "internal_error", "An internal error occurred")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        logger.info(
            "request_completed",
            extra={
                "request_id": request.state.request_id,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            },
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(request, exc.status_code, "http_error", "Request could not be served")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(request, 422, "validation_error", "Request validation failed")

    @app.get("/health", response_model=HealthResponse, tags=["status"])
    def health() -> HealthResponse:
        # Liveness is deliberately independent from PostgreSQL readiness.
        return HealthResponse()

    @app.get(
        "/ready",
        response_model=ReadyResponse,
        responses={503: {"model": ReadyResponse}},
        tags=["status"],
    )
    def ready(request: Request):
        engine = request.app.state.engine
        if engine is None:
            body = ReadyResponse(status="not_ready", database="unconfigured")
        else:
            try:
                with engine.connect() as connection:
                    if settings.database_url is not None:
                        validate_runtime(connection)
                    connection.execute(text("SELECT 1"))
                    revision = connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one_or_none()
                    body = ReadyResponse(
                        status="ready" if revision == SCHEMA_REVISION else "not_ready",
                        database="connected"
                        if revision == SCHEMA_REVISION
                        else "migration_required",
                    )
            except DatabasePrivilegeError:
                body = ReadyResponse(status="not_ready", database="unsafe_privileges")
            except SQLAlchemyError as exc:
                missing_table = getattr(getattr(exc, "orig", None), "sqlstate", None) == "42P01"
                body = ReadyResponse(
                    status="not_ready",
                    database="migration_required" if missing_table else "unavailable",
                )
                logger.warning("database_not_ready", extra={"exception_type": type(exc).__name__})
        return JSONResponse(
            status_code=200 if body.status == "ready" else 503, content=body.model_dump()
        )

    # CORS must wrap the error-response middleware so HTTP 500 stays observable to browsers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Accept", "Content-Type", "X-CSRF-Token"],
        expose_headers=["X-Request-ID"],
        allow_credentials=True,
    )
    return app


app = create_app()
