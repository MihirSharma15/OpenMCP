"""Vercel entrypoint for the account HTTP API; the signer runs separately.

Build inspection imports this module without opening a database connection.
Missing deployment configuration leaves readiness and account routes at 503.
No demo application, balances, or payment worker are started as a fallback.
"""

import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .app import create_app
from .config import ProductSettings
from .models import identifier

log = logging.getLogger(__name__)


def account_application():
    # Hosted configuration comes only from the project's environment variables.
    return create_app(ProductSettings(_env_file=None))


def create_hosted_app(factory=account_application):
    account = None
    failure = "backend_not_configured"

    @asynccontextmanager
    async def lifespan(host):
        nonlocal account, failure
        try:
            candidate = factory()
        except ValueError as exc:
            failure = "backend_not_configured"
            log.error("Account configuration unavailable error=%s", type(exc).__name__)
        except (psycopg.Error, OSError) as exc:
            failure = "backend_unavailable"
            # Exception messages can contain a DSN or private filesystem path.
            log.error("Account startup unavailable error=%s", type(exc).__name__)
        else:
            async with candidate.router.lifespan_context(candidate):
                account = candidate
                try:
                    yield
                finally:
                    account = None
            return
        yield

    host = FastAPI(
        title="OpenMCP account API",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @host.get("/")
    async def index():
        return JSONResponse(
            {
                "service": "openmcp-account-api",
                "status": "initialized" if account is not None else failure,
                "readiness_url": "/health/ready",
            },
            headers={"Cache-Control": "no-store"},
        )

    @host.get("/health/live")
    async def live():
        return JSONResponse(
            {"status": "ok", "service": "openmcp-account-api"},
            headers={"Cache-Control": "no-store"},
        )

    async def dispatch(scope, receive, send):
        if account is not None:
            await account(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1013})
            return
        request_id = identifier("req")
        response = JSONResponse(
            {
                "error": {
                    "code": failure,
                    "message": "The account backend is not ready. Contact the operator.",
                    "retryable": failure == "backend_unavailable",
                },
                "request_id": request_id,
            },
            status_code=503,
            headers={"Cache-Control": "no-store", "X-Request-ID": request_id},
        )
        await response(scope, receive, send)

    host.mount("/", dispatch)
    return host


app = create_hosted_app()
