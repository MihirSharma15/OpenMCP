import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mpp import Challenge
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .adapters.memory import MemoryAccounts, MemoryLedger
from .api.v1.accounts import router as accounts_router
from .api.v1.errors import credit_validation_response
from .api.v1.router import router as v1_router
from .config import CHAIN_ID, Settings
from .engine import Engine
from .models import DiscoverRequest, ExecuteRequest, OpenMCPError, ResetRequest
from .ports.accounts import AccountStore
from .ports.ledger import CreditLedger

_PUBLIC_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/docs/oauth2-redirect"})
_DEMO_UNAUTHORIZED = {
    "error": {
        "code": "unauthorized",
        "message": "OpenMCP connection token required.",
        "retryable": False,
    }
}


class BearerAuth:
    """Split the demo connection token from per-account credentials.

    Demo routes, including ``/execute`` and ``/demo/reset``, accept only
    ``OPENMCP_API_TOKEN``. ``POST /v1/accounts`` uses that same token because
    the account credential does not exist yet. Every other ``/v1`` route is
    left for account-credential checks inside the router. An account
    credential therefore cannot call the demo routes.
    """

    def __init__(self, app, token):
        self.app, self.expected = app, f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] == "OPTIONS"
            or scope["path"] in _PUBLIC_PATHS
        ):
            await self.app(scope, receive, send)
            return
        if _uses_account_credential(scope["method"], scope["path"]):
            await self.app(scope, receive, send)
            return
        authorization = dict(scope["headers"]).get(b"authorization", b"")
        if not hmac.compare_digest(authorization, self.expected):
            await JSONResponse(_DEMO_UNAUTHORIZED, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _uses_account_credential(method: str, path: str) -> bool:
    """True when the route authenticates an account credential, not the demo token."""

    if not path.startswith("/v1/"):
        return False
    return not (method == "POST" and path == "/v1/accounts")


def _product_stores(
    settings: Settings,
    ledger: CreditLedger | None,
    accounts: AccountStore | None,
) -> tuple[CreditLedger, AccountStore]:
    """Use injected stores, Postgres when configured, or memory when the URL is empty.

    An injected ledger or account store skips Postgres for both, so tests can
    run on memory. An empty product database URL never opens a connection.
    """

    if ledger is not None or accounts is not None:
        return (
            ledger if ledger is not None else MemoryLedger(),
            accounts if accounts is not None else MemoryAccounts(),
        )
    url = settings.product_database_url.strip()
    if not url:
        return MemoryLedger(), MemoryAccounts()
    # Import only when a URL is set so an empty configuration never opens Postgres.
    from .adapters.postgres.accounts import PostgresAccounts
    from .adapters.postgres.accounts import migrate as migrate_accounts
    from .adapters.postgres.ledger import PostgresLedger
    from .adapters.postgres.ledger import migrate as migrate_ledger

    migrate_ledger(url)
    migrate_accounts(url)
    return PostgresLedger(url), PostgresAccounts(url)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    *,
    ledger: CreditLedger | None = None,
    accounts: AccountStore | None = None,
):
    settings = settings or Settings()
    if (
        min(
            len(settings.api_token.get_secret_value()),
            len(settings.payment_secret.get_secret_value()),
        )
        < 16
    ):
        raise ValueError("Run `uv run openmcp init` to generate local connection and MPP secrets")
    engine = engine or Engine(settings)
    ledger, accounts = _product_stores(settings, ledger, accounts)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await engine.close()

    app = FastAPI(title="OpenMCP — MPP on Tempo testnet", version="0.2.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.ledger = ledger
    app.state.accounts = accounts
    app.state.settings = settings
    app.add_middleware(BearerAuth, token=settings.api_token.get_secret_value())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Authorization",
            "Payment-Authorization",
            "Content-Type",
            "Idempotency-Key",
        ],
        expose_headers=["WWW-Authenticate", "Payment-Receipt"],
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.exception_handler(OpenMCPError)
    async def domain_error(request: Request, exc: OpenMCPError):
        receipt = getattr(exc, "receipt", None)
        return JSONResponse(
            {"error": exc.as_dict()},
            status_code=exc.status,
            headers={"Payment-Receipt": receipt["header"]} if receipt else None,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/v1/"):
            return credit_validation_response(exc)
        return await request_validation_exception_handler(request, exc)

    @app.get("/health")
    async def health():
        return {"status": "ok", "payment_mode": "mpp_tempo_testnet", "chain_id": CHAIN_ID}

    @app.get("/balance")
    async def balance():
        return {**engine.store.balance(), "address": engine.addresses["agent"]}

    @app.post("/discover")
    async def discover(body: DiscoverRequest):
        return engine.discover(body)

    @app.get("/endpoints/{endpoint_id}")
    async def endpoint_terms(endpoint_id: str):
        return engine.endpoint_terms(endpoint_id)

    @app.post("/execute")
    async def execute(body: ExecuteRequest, request: Request):
        result = await engine.execute(body, request.headers.get("Payment-Authorization"))
        if isinstance(result, Challenge):
            return JSONResponse(
                {
                    "payment_required": True,
                    "protocol": "MPP",
                    "method": "tempo",
                    "chain_id": CHAIN_ID,
                },
                status_code=402,
                headers={
                    "WWW-Authenticate": result.to_www_authenticate(engine.receiver.realm),
                    "Cache-Control": "no-store",
                },
            )
        return JSONResponse(
            result, headers={"Payment-Receipt": result["agent_to_openmcp"]["header"]}
        )

    @app.get("/dashboard")
    async def dashboard(include_chain: bool = True):
        return await engine.dashboard(include_chain)

    @app.get("/transactions")
    async def transactions():
        return {"transactions": [engine.receipt(row) for row in engine.store.transactions()]}

    @app.get("/providers/dashboard")
    async def provider_dashboard(include_chain: bool = True):
        return await engine.provider_dashboard(include_chain)

    @app.get("/events")
    async def events(after: int = Query(default=0, ge=0)):
        rows = engine.store.events(after)
        return {"events": rows, "next_cursor": rows[-1]["id"] if rows else after}

    @app.post("/demo/reset")
    async def reset(body: ResetRequest | None = None):
        async with engine.lock:
            requested = (
                body.budget_cents
                if body is not None and body.budget_cents is not None
                else settings.budget_cents
            )
            return engine.store.reset(requested)

    app.include_router(accounts_router)
    app.include_router(v1_router)

    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
        }
        schema["security"] = [{"BearerAuth": []}]
        return schema

    app.openapi = openapi
    return app
