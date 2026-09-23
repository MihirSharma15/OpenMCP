"""Claude's client-side wallet and HTTP calls. Never imported by the server engine."""

import hashlib

import httpx

from .config import Settings, load_catalog
from .models import ExecuteRequest, OpenMCPError
from .payments import PaidClient, canonical, memo_for


class Agent:
    def __init__(self, settings: Settings, *, paid=None, transport=None):
        self.settings = settings
        self.catalog = load_catalog(settings.catalog)
        self.headers = {"Authorization": f"Bearer {settings.api_token.get_secret_value()}"}
        self.http = httpx.AsyncClient(
            base_url=settings.base_url, headers=self.headers, timeout=150, transport=transport
        )
        self.paid = paid or PaidClient(settings, "agent", transport=transport)

    async def close(self):
        await self.http.aclose()
        await self.paid.close()

    @staticmethod
    def result(response):
        if response.is_error:
            try:
                error = response.json()["error"]
            except (ValueError, KeyError):
                raise OpenMCPError(
                    "http_error",
                    f"OpenMCP returned HTTP {response.status_code}",
                    response.status_code,
                )
            raise OpenMCPError(
                error["code"], error["message"], response.status_code, error.get("retryable", False)
            )
        return response.json()

    async def balance(self):
        return self.result(await self.http.get("/balance"))

    async def discover(self, query, budget_cents):
        return self.result(
            await self.http.post("/discover", json={"query": query, "budget_cents": budget_cents})
        )

    async def execute(self, request: ExecuteRequest):
        provider = self.catalog.get(request.endpoint_id)
        if not provider or provider.price_cents > request.max_price_cents:
            raise OpenMCPError(
                "unapproved_price", "Unknown endpoint or price exceeds approval.", 409
            )
        body = request.model_dump()
        fingerprint = hashlib.sha256(canonical(body)).hexdigest()
        response = await self.paid.post(
            f"{self.settings.base_url.rstrip('/')}/execute",
            body,
            key=request.idempotency_key,
            scope=request.session_id,
            recipient=self.settings.addresses()["openmcp"],
            cents=provider.price_cents,
            budget=min(request.budget_cents, self.settings.budget_cents),
            memo=memo_for(fingerprint),
            headers=self.headers,
        )
        return self.result(response)
