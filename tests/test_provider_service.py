"""Offline integration tests for the persistent MPP provider service."""

import asyncio
import json
import stat
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from mpp import Challenge
from starlette.responses import JSONResponse

from openmcp.agent import Agent
from openmcp.app import create_app
from openmcp.config import CHAIN_ID, TOKEN, load_catalog
from openmcp.engine import Engine
from openmcp.models import ExecuteRequest
from openmcp.payments import PaidClient
from openmcp.payments import canonical as gateway_canonical
from openmcp.payments import memo_for as gateway_memo_for
from openmcp_provider import canonical, create_provider_app, memo_for
from providers import courtlens, marketscope, supplysignal
from providers.app import PROVIDERS
from tests.conftest import TestChain as SettlementChain
from traditional_apis import courtlens as courtlens_api
from traditional_apis import marketscope as marketscope_api
from traditional_apis import supplysignal as supplysignal_api

EXPECTED_CONTENT = {
    "operational-health": (
        "Fleet utilization for FreightFlow is at 88%. Warehouse turnover is "
        "4.2 days (industry avg 5.1). No major supply chain disruptions "
        "detected in the last 90 days."
    ),
    "legal-liabilities": (
        "WARNING: 2 pending class-action lawsuits found in the Southern District "
        "of New York for FreightFlow regarding independent contractor "
        "misclassification. Estimated liability exposure: $4.2M - $7M."
    ),
    "competitor-market-share": (
        "2025 Estimated Revenue for FreightFlow: $142M (Up 12% YoY). EBITDA "
        "margin: 14%. Current market share in Midwest logistics corridor: 8.4% "
        "(Ranked #4 behind XPO, JB Hunt, and CH Robinson)."
    ),
}
PROVIDER_CENTS = {
    "operational-health": 36,
    "legal-liabilities": 45,
    "competitor-market-share": 27,
}
WALLETS = {
    "operational-health": "operations",
    "legal-liabilities": "legal",
    "competitor-market-share": "market",
}


class CountingASGIApp:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.requests = 0

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] == "http":
            self.requests += 1
        await self.app(scope, receive, send)


class GateASGIApp(CountingASGIApp):
    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] == "http":
            self.requests += 1
            self.entered.set()
            await self.release.wait()
        await self.app(scope, receive, send)


class FailOnceASGIApp(CountingASGIApp):
    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] == "http":
            self.requests += 1
            if self.requests == 1:
                await JSONResponse({"error": "planned outage"}, status_code=503)(
                    scope,
                    receive,
                    send,
                )
                return
        await self.app(scope, receive, send)


def configure_upstreams(monkeypatch: pytest.MonkeyPatch) -> dict[str, CountingASGIApp]:
    upstreams = {
        "operational-health": CountingASGIApp(supplysignal_api.app),
        "legal-liabilities": CountingASGIApp(courtlens_api.app),
        "competitor-market-share": CountingASGIApp(marketscope_api.app),
    }
    monkeypatch.setattr(
        supplysignal,
        "_UPSTREAM_TRANSPORT",
        httpx.ASGITransport(app=upstreams["operational-health"]),
    )
    monkeypatch.setattr(
        courtlens,
        "_UPSTREAM_TRANSPORT",
        httpx.ASGITransport(app=upstreams["legal-liabilities"]),
    )
    monkeypatch.setattr(
        marketscope,
        "_UPSTREAM_TRANSPORT",
        httpx.ASGITransport(app=upstreams["competitor-market-share"]),
    )
    return upstreams


@pytest.fixture
async def provider_service(settings, monkeypatch):
    upstreams = configure_upstreams(monkeypatch)
    chain = SettlementChain()
    app = create_provider_app(PROVIDERS, settings=settings, intent_factory=chain.intent)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://provider",
        ) as client:
            yield {
                "app": app,
                "chain": chain,
                "client": client,
                "settings": settings,
                "upstreams": upstreams,
            }


def purchase(system: dict[str, Any], endpoint: str, key: str) -> ExecuteRequest:
    engine = system["engine"]
    return ExecuteRequest(
        session_id=engine.store.balance()["session_id"],
        endpoint_id=endpoint,
        payload={"company": "FreightFlow"},
        idempotency_key=key,
        max_price_cents=engine.catalog[endpoint].price_cents,
        budget_cents=1500,
    )


async def test_full_gateway_purchase_uses_actual_reports_and_six_payments(provider_service):
    settings = provider_service["settings"]
    provider_app = provider_service["app"]
    chain = provider_service["chain"]
    addresses = settings.addresses()
    before = {
        wallet: chain.balances[addresses[wallet].lower()]
        for wallet in ("operations", "legal", "market")
    }
    outgoing = PaidClient(
        settings,
        "openmcp",
        transport=httpx.ASGITransport(app=provider_app),
        method=chain.method(addresses["openmcp"]),
        chain=chain,
    )
    engine = Engine(settings, incoming_intent=chain.intent(), outgoing=outgoing, chain=chain)
    gateway_app = create_app(settings, engine)
    transport = httpx.ASGITransport(app=gateway_app)
    paid = PaidClient(
        settings,
        "agent",
        transport=transport,
        method=chain.method(addresses["agent"]),
        chain=chain,
    )
    agent = Agent(settings, paid=paid, transport=transport)
    system = {"engine": engine}
    try:
        discovery = await agent.discover("FreightFlow due diligence", 1500)
        results = {}
        for endpoint in discovery["endpoints"]:
            endpoint_id = endpoint["endpoint_id"]
            results[endpoint_id] = await agent.execute(
                purchase(system, endpoint_id, f"actual-{endpoint_id}")
            )

        assert chain.broadcasts == chain.signatures == 6
        assert {
            wallet: chain.balances[addresses[wallet].lower()] - before[wallet] for wallet in before
        } == {"operations": 360_000, "legal": 450_000, "market": 270_000}
        for endpoint_id, result in results.items():
            data = result["data"]
            assert data["content"] == EXPECTED_CONTENT[endpoint_id]
            assert data["is_demo_data"] is True
            assert data["sources"]
            assert all(source["fictional"] is True for source in data["sources"])
            assert result["agent_to_openmcp"]["reference"]
            assert result["openmcp_to_provider"]["reference"]
        assert {
            endpoint: upstream.requests
            for endpoint, upstream in provider_service["upstreams"].items()
        } == dict.fromkeys(EXPECTED_CONTENT, 1)
    finally:
        await agent.close()
        await engine.close()


@pytest.mark.parametrize("endpoint_id", tuple(EXPECTED_CONTENT))
async def test_unpaid_challenges_match_gateway_policy_and_call_no_upstream(
    provider_service,
    endpoint_id,
):
    key = f"unpaid-{endpoint_id}"
    body = {"company": "FreightFlow"}
    response = await provider_service["client"].post(
        f"/{endpoint_id}",
        json=body,
        headers={"Idempotency-Key": key, "X-OpenMCP-Execution-ID": key},
    )
    assert response.status_code == 402
    assert response.json() == {"payment_required": True}
    assert response.headers["Cache-Control"] == "no-store"
    assert "Payment-Receipt" not in response.headers
    challenge = Challenge.from_www_authenticate(response.headers["WWW-Authenticate"])
    PaidClient.check_challenge(
        challenge,
        canonical(body),
        provider_service["settings"].addresses()[WALLETS[endpoint_id]],
        PROVIDER_CENTS[endpoint_id],
        memo_for(key),
    )
    assert challenge.header is None
    assert not challenge.request["methodDetails"].get("splits")
    assert not challenge.request["methodDetails"].get("feePayer")
    assert provider_service["upstreams"][endpoint_id].requests == 0
    assert provider_service["chain"].broadcasts == 0


async def test_validation_and_execution_headers_precede_payment(provider_service):
    client = provider_service["client"]
    headers = {
        "Idempotency-Key": "validation-0001",
        "X-OpenMCP-Execution-ID": "different-0001",
    }
    empty = await client.post("/operational-health", json={"company": ""}, headers=headers)
    extra = await client.post(
        "/operational-health",
        json={"company": "FreightFlow", "extra": True},
        headers=headers,
    )
    mismatch = await client.post(
        "/operational-health",
        json={"company": "FreightFlow"},
        headers=headers,
    )
    assert empty.status_code == extra.status_code == 422
    assert mismatch.status_code == 400
    assert "WWW-Authenticate" not in mismatch.headers
    assert provider_service["upstreams"]["operational-health"].requests == 0
    assert provider_service["chain"].signatures == provider_service["chain"].broadcasts == 0


async def test_cached_replay_requires_credential_and_changed_body_conflicts(provider_service):
    settings = provider_service["settings"]
    chain = provider_service["chain"]
    key = "cached-replay-0001"
    scope = "provider-cache-test"
    recipient = settings.addresses()["operations"]
    paid = PaidClient(
        settings,
        "openmcp",
        transport=httpx.ASGITransport(app=provider_service["app"]),
        method=chain.method(settings.addresses()["openmcp"]),
        chain=chain,
    )
    try:
        first = await paid.post(
            "http://provider/operational-health",
            {"company": "FreightFlow"},
            key=key,
            recipient=recipient,
            cents=36,
            scope=scope,
            budget=36,
            memo=memo_for(key),
            headers={"X-OpenMCP-Execution-ID": key},
        )
        saved = paid.journal.get(f"{scope}:{key}")
        authorization = saved["authorization"]
        common_headers = {
            "Idempotency-Key": key,
            "X-OpenMCP-Execution-ID": key,
            "Authorization": authorization,
        }
        changed = await provider_service["client"].post(
            "/operational-health",
            json={"company": "Other"},
            headers=common_headers,
        )
        missing = await provider_service["client"].post(
            "/operational-health",
            json={"company": "FreightFlow"},
            headers={
                "Idempotency-Key": key,
                "X-OpenMCP-Execution-ID": key,
            },
        )
        replay = await provider_service["client"].post(
            "/operational-health",
            json={"company": "FreightFlow"},
            headers=common_headers,
        )
        assert first.status_code == replay.status_code == 200
        assert changed.status_code == 409
        assert missing.status_code == 403
        assert replay.content == first.content
        assert replay.headers["Payment-Receipt"] == first.headers["Payment-Receipt"]
        assert provider_service["upstreams"]["operational-health"].requests == 1
        assert chain.broadcasts == chain.signatures == 1
    finally:
        await paid.close()


async def test_same_key_concurrent_paid_retries_settle_and_fulfill_once(
    provider_service,
    monkeypatch,
):
    gate = GateASGIApp(supplysignal_api.app)
    monkeypatch.setattr(
        supplysignal,
        "_UPSTREAM_TRANSPORT",
        httpx.ASGITransport(app=gate),
    )
    key = "concurrent-provider-0001"
    body = {"company": "FreightFlow"}
    base_headers = {"Idempotency-Key": key, "X-OpenMCP-Execution-ID": key}
    unpaid = await provider_service["client"].post(
        "/operational-health",
        json=body,
        headers=base_headers,
    )
    challenge = Challenge.from_www_authenticate(unpaid.headers["WWW-Authenticate"])
    credential = (
        await provider_service["chain"]
        .method(provider_service["settings"].addresses()["openmcp"])
        .create_credential(challenge)
    )
    headers = {**base_headers, "Authorization": credential.to_authorization()}

    first_task = asyncio.create_task(
        provider_service["client"].post("/operational-health", json=body, headers=headers)
    )
    await asyncio.wait_for(gate.entered.wait(), timeout=1)
    second_task = asyncio.create_task(
        provider_service["client"].post("/operational-health", json=body, headers=headers)
    )
    await asyncio.sleep(0)
    gate.release.set()
    first, second = await asyncio.gather(first_task, second_task)

    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert first.headers["Payment-Receipt"] == second.headers["Payment-Receipt"]
    assert gate.requests == 1
    assert provider_service["chain"].broadcasts == provider_service["chain"].signatures == 1


async def test_paid_upstream_failure_recovers_after_restart_without_repayment(
    settings,
    monkeypatch,
):
    configure_upstreams(monkeypatch)
    failing = FailOnceASGIApp(courtlens_api.app)
    monkeypatch.setattr(
        courtlens,
        "_UPSTREAM_TRANSPORT",
        httpx.ASGITransport(app=failing),
    )
    chain = SettlementChain()
    key = "restart-recovery-0001"
    scope = "restart-recovery"
    kwargs = {
        "url": "http://provider/legal-liabilities",
        "payload": {"company": "FreightFlow"},
        "key": key,
        "recipient": settings.addresses()["legal"],
        "cents": 45,
        "scope": scope,
        "budget": 45,
        "memo": memo_for(key),
        "headers": {"X-OpenMCP-Execution-ID": key},
    }

    app = create_provider_app(PROVIDERS, settings=settings, intent_factory=chain.intent)
    async with app.router.lifespan_context(app):
        paid = PaidClient(
            settings,
            "openmcp",
            transport=httpx.ASGITransport(app=app),
            method=chain.method(settings.addresses()["openmcp"]),
            chain=chain,
        )
        try:
            failed = await paid.post(**kwargs)
            authorization = paid.journal.get(f"{scope}:{key}")["authorization"]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://provider",
            ) as client:
                missing = await client.post(
                    "/legal-liabilities",
                    json={"company": "FreightFlow"},
                    headers={
                        "Idempotency-Key": key,
                        "X-OpenMCP-Execution-ID": key,
                    },
                )
            assert failed.status_code == 503
            assert failed.headers["Payment-Receipt"]
            assert missing.status_code == 403
            assert failing.requests == 1
            assert chain.broadcasts == chain.signatures == 1
        finally:
            await paid.close()

    healthy = CountingASGIApp(courtlens_api.app)
    monkeypatch.setattr(
        courtlens,
        "_UPSTREAM_TRANSPORT",
        httpx.ASGITransport(app=healthy),
    )
    restarted = create_provider_app(PROVIDERS, settings=settings, intent_factory=chain.intent)
    async with restarted.router.lifespan_context(restarted):
        paid = PaidClient(
            settings,
            "openmcp",
            transport=httpx.ASGITransport(app=restarted),
            method=chain.method(settings.addresses()["openmcp"]),
            chain=chain,
        )
        try:
            recovered = await paid.post(**kwargs)
            assert recovered.status_code == 200
            assert recovered.json()["content"] == EXPECTED_CONTENT["legal-liabilities"]
            assert healthy.requests == 1
            assert chain.broadcasts == chain.signatures == 1
        finally:
            await paid.close()

    no_replay_call = CountingASGIApp(courtlens_api.app)
    monkeypatch.setattr(
        courtlens,
        "_UPSTREAM_TRANSPORT",
        httpx.ASGITransport(app=no_replay_call),
    )
    replayed = create_provider_app(PROVIDERS, settings=settings, intent_factory=chain.intent)
    async with replayed.router.lifespan_context(replayed):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=replayed),
            base_url="http://provider",
        ) as client:
            replay = await client.post(
                "/legal-liabilities",
                json={"company": "FreightFlow"},
                headers={
                    "Idempotency-Key": key,
                    "X-OpenMCP-Execution-ID": key,
                    "Authorization": authorization,
                },
            )
    assert replay.status_code == 200
    assert no_replay_call.requests == 0
    assert chain.broadcasts == chain.signatures == 1


async def test_temporary_payment_failure_is_503_and_never_calls_upstream(
    settings,
    monkeypatch,
):
    upstreams = configure_upstreams(monkeypatch)
    chain = SettlementChain()

    class BrokenIntent:
        name = "charge"

        async def verify(self, credential, request):
            raise RuntimeError("planned settlement failure")

        async def aclose(self):
            pass

    app = create_provider_app(PROVIDERS, settings=settings, intent_factory=BrokenIntent)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://provider",
        ) as client:
            key = "payment-failure-0001"
            headers = {"Idempotency-Key": key, "X-OpenMCP-Execution-ID": key}
            unpaid = await client.post(
                "/competitor-market-share",
                json={"company": "FreightFlow"},
                headers=headers,
            )
            challenge = Challenge.from_www_authenticate(unpaid.headers["WWW-Authenticate"])
            credential = await chain.method(settings.addresses()["openmcp"]).create_credential(
                challenge
            )
            failed = await client.post(
                "/competitor-market-share",
                json={"company": "FreightFlow"},
                headers={**headers, "Authorization": credential.to_authorization()},
            )
    assert failed.status_code == 503
    assert "Payment-Receipt" not in failed.headers
    assert upstreams["competitor-market-share"].requests == 0
    assert chain.broadcasts == 0


async def test_startup_rejects_missing_wallets_wrong_fee_and_wrong_price(
    settings,
    tmp_path: Path,
):
    missing_wallets = settings.model_copy(update={"wallets": tmp_path / "missing-wallets"})
    missing_app = create_provider_app(PROVIDERS, settings=missing_wallets)
    with pytest.raises(ValueError, match="openmcp init"):
        async with missing_app.router.lifespan_context(missing_app):
            pass

    wrong_fee = settings.model_copy(update={"fee_bps": 500})
    fee_app = create_provider_app(PROVIDERS, settings=wrong_fee)
    with pytest.raises(ValueError, match="Provider price"):
        async with fee_app.router.lifespan_context(fee_app):
            pass

    catalog_data = json.loads(settings.catalog.read_text(encoding="utf-8"))
    catalog_data[0]["price_cents"] = 41
    wrong_catalog = tmp_path / "wrong-price.json"
    wrong_catalog.write_text(json.dumps(catalog_data), encoding="utf-8")
    wrong_price = settings.model_copy(update={"catalog": wrong_catalog})
    price_app = create_provider_app(PROVIDERS, settings=wrong_price)
    with pytest.raises(ValueError, match="Provider price"):
        async with price_app.router.lifespan_context(price_app):
            pass


async def test_declarations_helpers_and_private_state_match_contract(provider_service):
    settings = provider_service["settings"]
    catalog = load_catalog(settings.catalog)
    declared = {tool.route_id: tool for provider in PROVIDERS for tool in provider.tools}
    assert set(declared) == set(catalog)
    assert {endpoint: tool.input_schema for endpoint, tool in declared.items()} == {
        endpoint: item.input_schema for endpoint, item in catalog.items()
    }
    assert {endpoint: tool.price_cents for endpoint, tool in declared.items()} == PROVIDER_CENTS
    assert canonical({"b": 1, "a": "✓"}) == gateway_canonical({"b": 1, "a": "✓"})
    assert memo_for("execution-123") == gateway_memo_for("execution-123")
    assert CHAIN_ID == 42431
    assert TOKEN == "0x20c0000000000000000000000000000000000000"

    state = settings.database.parent / "provider"
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    for name in ("secrets.json", "mpp-replay.sqlite3", "fulfillment.sqlite3"):
        assert stat.S_IMODE((state / name).stat().st_mode) == 0o600
