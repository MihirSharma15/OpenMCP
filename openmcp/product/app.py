"""FastAPI account API. This app does not mount any demo credit mutation routes."""

import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator
from starlette.exceptions import HTTPException

from openmcp.database import DatabaseManager

from .auth import ClerkVerifier
from .config import ProductSettings
from .models import (
    AgentInput,
    DiscoverInput,
    ExecuteInput,
    Principal,
    ProductError,
    TopUpInput,
    fingerprint,
    identifier,
)
from .store import Store
from .stripe import StripeGateway

log = logging.getLogger(__name__)


def _catalog_match(words, *parts):
    if not words:
        return True
    corpus = " ".join(parts).lower()
    return any(word in corpus for word in words)


def discover_providers(rows, words, ceiling, active):
    groups = {}
    for row in rows:
        group = groups.get(row["provider_id"])
        if group is None:
            group = {
                "provider_id": row["provider_id"],
                "name": row["provider_name"],
                "description": row["provider_description"],
                "provider_match": _catalog_match(
                    words, row["provider_name"], row["provider_description"]
                ),
                "services": [],
            }
            groups[row["provider_id"]] = group
        group["services"].append(row["service"])
    providers = []
    for group in groups.values():
        included = [
            service
            for service in group["services"]
            if group["provider_match"] or _catalog_match(words, service.name, service.description)
        ]
        if not included:
            continue
        included.sort(key=lambda service: (service.price_cents, service.endpoint_id))
        providers.append(
            {
                "provider_id": group["provider_id"],
                "name": group["name"],
                "description": group["description"],
                "queries": [
                    service.public() | {"affordable": active and service.price_cents <= ceiling}
                    for service in included
                ],
            }
        )
    providers.sort(
        key=lambda provider: (provider["queries"][0]["price_cents"], provider["provider_id"])
    )
    return providers


def create_app(settings=None, *, store=None, verifier=None, stripe=None):
    settings = settings or ProductSettings()
    owns_store = store is None
    # Dependency injection is only for tests. Normal startup is always validated.
    if store is None:
        settings.validate_startup()
        store = Store(DatabaseManager.from_settings(settings))
        try:
            store.database.check_schema_version()
            store.bind_runtime(settings)
            store.sync_catalog(settings.catalog())
        except Exception:
            store.close()
            raise
    else:
        store.sync_catalog(settings.catalog())
    verifier = verifier or ClerkVerifier(settings)
    stripe = stripe or StripeGateway(settings, store)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            try:
                await verifier.close()
                await stripe.close()
            finally:
                if owns_store:
                    store.close()

    app = FastAPI(title="OpenMCP account API", version="1", lifespan=lifespan)
    app.state.store, app.state.stripe = store, stripe
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url.rstrip("/")],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    def error_response(request, exc):
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {"code": exc.code, "message": exc.message, "retryable": exc.retryable},
                "request_id": getattr(request.state, "request_id", identifier("req")),
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.middleware("http")
    async def private_responses(request, call_next):
        request.state.request_id = identifier("req")
        maximum = 1_000_000 if request.url.path == "/v1/webhooks/stripe" else 131_072
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > maximum:
                return error_response(
                    request, ProductError("request_too_large", "Request exceeds size limit.", 413)
                )
            chunks.append(chunk)
        request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ProductError)
    async def product_error(request, exc):
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error_response(
            request, ProductError("invalid_request", "Request fields are missing or invalid.", 422)
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(
            request,
            ProductError(
                "not_found" if exc.status_code == 404 else "invalid_request",
                "Resource not found." if exc.status_code == 404 else "Request is not supported.",
                exc.status_code,
            ),
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        log.error(
            "Account API error request_id=%s type=%s", request.state.request_id, type(exc).__name__
        )
        return error_response(
            request,
            ProductError("service_unavailable", "Service is temporarily unavailable.", 503, True),
        )

    def bearer(request: Request, authorization: str | None = Header(default=None)):
        store.rate_limit("auth:" + (request.client.host if request.client else "unknown"), 300)
        if (
            not authorization
            or not authorization.startswith("Bearer ")
            or len(authorization) > 16_384
        ):
            raise ProductError("unauthenticated", "A bearer credential is required.", 401)
        token = authorization[7:]
        if not token or any(char.isspace() for char in token):
            raise ProductError("unauthenticated", "A bearer credential is required.", 401)
        return token

    async def human_subject(token=Depends(bearer)):
        if token.startswith("omcp_"):
            raise ProductError("forbidden", "A human account session is required.", 403)
        subject = await verifier.subject(token)
        # Bind identities to issuer as well as sub, including when an operator
        # moves configuration between Clerk applications.
        return fingerprint({"issuer": settings.clerk_issuer.rstrip("/"), "subject": subject})

    async def human(subject=Depends(human_subject)):
        return Principal(store.account_for_subject(subject)["account_id"])

    async def agent(token=Depends(bearer)):
        if not token.startswith("omcp_"):
            raise ProductError("forbidden", "Use a capped agent credential for purchases.", 403)
        return store.authenticate_agent(token)

    async def either(token=Depends(bearer)):
        if token.startswith("omcp_"):
            return store.authenticate_agent(token)
        subject = await human_subject(token)
        return Principal(store.account_for_subject(subject)["account_id"])

    def idempotency(key: str | None = Header(default=None, alias="Idempotency-Key")):
        if not key or not 1 <= len(key) <= 200 or any(not 33 <= ord(char) <= 126 for char in key):
            raise ProductError(
                "invalid_idempotency_key",
                "Supply an Idempotency-Key of 1–200 visible ASCII characters.",
                422,
            )
        return key

    def me_response(account):
        return {
            "account_id": account["account_id"],
            "status": account["status"],
            "currency": "usd_credits",
            "top_up_presets_cents": settings.top_up_presets_cents,
            "mode": settings.mode,
        }

    @app.get("/health/live")
    def live():
        return {"status": "ok", "mode": settings.mode}

    @app.get("/health/ready")
    def ready():
        try:
            health = store.health()
            good = health["database"] and health["worker"]
        except Exception:
            good = False
        return JSONResponse(
            {"status": "ready" if good else "unavailable", "mode": settings.mode},
            status_code=200 if good else 503,
        )

    @app.post("/v1/me/bootstrap")
    async def bootstrap(subject=Depends(human_subject)):
        return me_response(store.bootstrap(subject))

    @app.get("/v1/me")
    async def me(principal=Depends(human)):
        return me_response(store.account(principal.account_id))

    @app.get("/v1/wallet")
    async def wallet(principal=Depends(either)):
        return store.wallet(principal)

    @app.post("/v1/wallet/top-ups")
    async def top_up(body: TopUpInput, principal=Depends(human), key=Depends(idempotency)):
        if body.amount_cents not in settings.top_up_presets_cents:
            raise ProductError("invalid_amount", "Choose one of the available top-up amounts.", 422)
        store.rate_limit("top-up:" + principal.account_id, 10)
        top = store.create_top_up(principal.account_id, key, body.amount_cents)
        return store.top_up_public(await stripe.create(top))

    @app.get("/v1/wallet/top-ups/{top_id}")
    async def get_top_up(top_id: str, principal=Depends(human)):
        top = store.top_up(principal.account_id, top_id)
        if top["checkout_id"] and top["status"] not in {"credited", "expired", "failed"}:
            top = await stripe.reconcile(top["checkout_id"])
        return store.top_up_public(top)

    @app.post("/v1/webhooks/stripe", status_code=202)
    async def webhook(
        request: Request, signature: str = Header(default="", alias="Stripe-Signature")
    ):
        event = stripe.verify_webhook(await request.body(), signature)
        store.accept_event(event)
        return {"accepted": True}

    @app.get("/v1/transactions")
    async def transactions(
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = None,
        type: Literal["deposit", "purchase", "refund", "reversal"] | None = None,
        status: Literal["pending", "completed", "failed", "refunded", "needs_review"] | None = None,
        principal=Depends(human),
    ):
        return store.transactions(principal.account_id, limit, cursor, type, status)

    @app.get("/v1/transactions/{transaction_id}")
    async def transaction(transaction_id: str, principal=Depends(human)):
        return store.transaction(principal.account_id, transaction_id)

    @app.get("/v1/agents")
    async def agents(
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = None,
        principal=Depends(human),
    ):
        return store.agents(principal.account_id, limit, cursor)

    @app.post("/v1/agents")
    async def create_agent(body: AgentInput, principal=Depends(human)):
        store.rate_limit("grant:" + principal.account_id, 10)
        return store.create_agent(
            principal.account_id, body.name, body.spend_limit_cents, body.expires_at
        )

    @app.post("/v1/agents/{agent_id}/credentials")
    async def issue(agent_id: str, principal=Depends(human)):
        store.rate_limit("credential:" + principal.account_id, 30)
        return store.issue(principal.account_id, agent_id)

    @app.post("/v1/agents/{agent_id}/credentials/{credential_id}/revoke")
    async def revoke(agent_id: str, credential_id: str, principal=Depends(human)):
        return store.revoke(principal.account_id, agent_id, credential_id)

    @app.post("/v1/discover")
    async def discover(body: DiscoverInput, principal=Depends(agent)):
        store.rate_limit("discover:" + principal.agent_id, 60)
        wallet = store.wallet(principal)
        allowance = wallet["agent"]["remaining_cents"]
        affordable = min(wallet["available_cents"], allowance)
        if body.budget_cents is not None:
            affordable = min(affordable, body.budget_cents)
        disabled = store.disabled_endpoints()
        rows = [
            row
            for row in store.enabled_queries(settings.mode)
            if row["service"].endpoint_id not in disabled
        ]
        return {
            "providers": discover_providers(
                rows, body.query.lower().split(), affordable, wallet["status"] == "active"
            ),
            "available_cents": wallet["available_cents"],
            "remaining_allowance_cents": allowance,
            "discovery_is_free": True,
        }

    @app.post("/v1/execute")
    async def execute(body: ExecuteInput, principal=Depends(agent), key=Depends(idempotency)):
        store.rate_limit("execute:" + principal.agent_id, 30)
        payload = body.model_dump()
        old = store.execution_for_key(principal.agent_id, key, payload)
        if old:
            row = old
        else:
            service = store.service(body.endpoint_id, settings.mode)
            if not service:
                raise ProductError("not_found", "Enabled service not found.", 404)
            if next(Draft202012Validator(service.input_schema).iter_errors(body.payload), None):
                raise ProductError(
                    "invalid_payload", "Service input does not match its advertised schema.", 422
                )
            if not store.health()["worker"]:
                raise ProductError(
                    "worker_unavailable",
                    "Payment worker is unavailable; no credits reserved.",
                    503,
                    True,
                )
            row = store.reserve(principal, key, payload, service)
        from fastapi.encoders import jsonable_encoder

        return JSONResponse(
            jsonable_encoder(store.execution_public(row)),
            status_code=200 if row["status"] in {"completed", "refunded", "failed"} else 202,
        )

    @app.get("/v1/executions/{execution_id}")
    async def execution(execution_id: str, principal=Depends(either)):
        return store.execution_public(store.execution(principal, execution_id))

    return app
