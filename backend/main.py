"""FastAPI application factory: middleware, routers, lifespan."""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import admin_routes
import auth_routes
import comments_routes
import feed_routes
import media_routes
import meta_routes
import notifications_routes
import posts_routes
import reports_routes
import search_routes
import social_routes
import users_routes
from cache import close_redis, get_redis, init_redis
from config import settings
from database import engine
from deps import CSRF_HEADER, rate_limit
from errors import register_error_handlers
from http_client import close_http_client
from storage import close_s3

logger = logging.getLogger("toxic_express")

MAX_BODY_BYTES = 256 * 1024  # media never passes through the API, so JSON bodies stay small


request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Stamps every log record with the current request id (or "-" outside requests)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


def configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
    )
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RequestIdFilter) for f in handler.filters):
            handler.addFilter(RequestIdFilter())


class BodySizeLimitMiddleware:
    """Rejects request bodies over MAX_BODY_BYTES, including chunked bodies without a length."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit() and int(value) > MAX_BODY_BYTES:
                await self._reject(send)
                return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    raise _BodyTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLargeError:
            await self._reject(send)

    @staticmethod
    async def _reject(send: Send) -> None:
        response = JSONResponse(
            {
                "error": {
                    "code": "payload_too_large",
                    "message": "Request body too large",
                    "details": None,
                }
            },
            413,
        )
        await send({"type": "http.response.start", "status": 413, "headers": response.raw_headers})
        await send({"type": "http.response.body", "body": response.body})


class _BodyTooLargeError(Exception):
    pass


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_redis()
    if settings.env != "prod":
        from storage import ensure_buckets

        try:
            await ensure_buckets()
        except Exception:
            logger.warning("could not ensure dev buckets", exc_info=True)
    yield
    await close_http_client()
    await close_s3()
    await close_redis()
    await engine.dispose()


def create_app() -> FastAPI:
    configure_logging()
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.env,
            traces_sample_rate=0.05,
            send_default_pii=False,
        )

    app = FastAPI(
        title="Toxic-Express API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if settings.env == "prod" else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.env == "prod" else "/api/openapi.json",
    )
    register_error_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = (request.headers.get("x-request-id") or uuid.uuid4().hex)[:64]
        token = request_id_ctx.set(request_id)
        try:
            start = time.perf_counter()
            response = await call_next(request)
            elapsed_ms = (time.perf_counter() - start) * 1000
            response.headers["X-Request-ID"] = request_id
            path = request.url.path
            if not path.startswith("/api/docs"):
                for name, value in SECURITY_HEADERS.items():
                    response.headers.setdefault(name, value)
            if path.startswith(("/api/v1/auth/", "/api/v1/me/")) or path == "/api/v1/me":
                response.headers["Cache-Control"] = "no-store"
            logger.info(
                "%s %s -> %s (%.1fms)", request.method, path, response.status_code, elapsed_ms
            )
            return response
        finally:
            request_id_ctx.reset(token)

    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", CSRF_HEADER, "X-Request-ID"],
        max_age=600,
    )

    # Global per-IP ceiling; individual routes add tighter, purpose-specific limits.
    api = APIRouter(prefix="/api/v1", dependencies=[Depends(rate_limit("global", 600, 60))])
    for module in (
        auth_routes,
        users_routes,
        social_routes,
        posts_routes,
        comments_routes,
        feed_routes,
        media_routes,
        notifications_routes,
        search_routes,
        reports_routes,
        admin_routes,
        meta_routes,
    ):
        api.include_router(module.router)
    app.include_router(api)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    async def ready() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "error"
        try:
            await get_redis().ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "error"
        healthy = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ok" if healthy else "degraded", **checks}, 200 if healthy else 503
        )

    return app


app = create_app()
