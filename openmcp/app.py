import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mpp import Challenge
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import CHAIN_ID, Settings
from .engine import Engine
from .models import DiscoverRequest, ExecuteRequest, OpenMCPError


class BearerAuth:
    def __init__(self, app, token):
        self.app, self.expected = app, f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] == "http"
            and scope["method"] != "OPTIONS"
            and scope["path"] not in ("/health", "/docs", "/openapi.json", "/docs/oauth2-redirect")
        ):
            if not hmac.compare_digest(
                dict(scope["headers"]).get(b"authorization", b""), self.expected
            ):
                await JSONResponse(
                    {
                        "error": {
                            "code": "unauthorized",
                            "message": "OpenMCP connection token required.",
                            "retryable": False,
                        }
                    },
                    status_code=401,
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(settings: Settings | None = None, engine: Engine | None = None):
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

    @asynccontextmanager
    async def lifespan(app):
        yield
        await engine.close()

    app = FastAPI(title="OpenMCP — MPP on Tempo testnet", version="0.2.0", lifespan=lifespan)
    app.state.engine = engine
    app.add_middleware(BearerAuth, token=settings.api_token.get_secret_value())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Payment-Authorization", "Content-Type", "Idempotency-Key"],
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

    @app.get("/health")
    async def health():
        return {"status": "ok", "payment_mode": "mpp_tempo_testnet", "chain_id": CHAIN_ID}

    @app.get("/balance")
    async def balance():
        return {**engine.store.balance(), "address": engine.addresses["agent"]}

    @app.post("/discover")
    async def discover(body: DiscoverRequest):
        return engine.discover(body)

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
    async def reset():
        async with engine.lock:
            return engine.store.reset(settings.budget_cents)

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
