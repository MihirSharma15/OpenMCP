import asyncio
import hashlib

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mpp import Challenge

from openmcp.agent import Agent
from openmcp.app import create_app
from openmcp.engine import Engine
from openmcp.mcp_server import create_mcp
from openmcp.models import ExecuteRequest, OpenMCPError
from openmcp.payments import PaidClient, canonical, memo_for


def purchase(system, endpoint="operational-health", key="purchase-0001", budget=1500):
    engine = system["engine"]
    return ExecuteRequest(
        session_id=engine.store.balance()["session_id"],
        endpoint_id=endpoint,
        payload={"company": "FreightFlow"},
        idempotency_key=key,
        max_price_cents=engine.catalog[endpoint].price_cents,
        budget_cents=budget,
    )


async def test_two_real_mpp_exchanges_per_purchase(system):
    agent, chain, engine = system["agent"], system["chain"], system["engine"]
    discovery = await agent.discover("FreightFlow due diligence", 1500)
    assert discovery["total_price_cents"] == 120
    for item in discovery["endpoints"]:
        result = await agent.execute(
            purchase(system, item["endpoint_id"], key=f"buy-{item['endpoint_id']}")
        )
        assert result["agent_to_openmcp"]["reference"] != result["openmcp_to_provider"]["reference"]
        assert result["agent_to_openmcp"]["method"] == "tempo"
        assert result["openmcp_to_provider"]["method"] == "tempo"
    assert chain.broadcasts == chain.signatures == 6
    assert engine.store.balance()["remaining_cents"] == 1380
    dashboard = await engine.dashboard()
    assert dashboard["platform"]["session_gross_fee_cents"] == 12
    assert [p["session_earned_cents"] for p in dashboard["providers"]] == [36, 45, 27]
    assert chain.balances[engine.addresses["openmcp"].lower()] == 20_120_000
    events = [e["type"] for e in engine.store.events()]
    assert events.count("provider_challenge_received") == 3
    assert events.count("agent_challenge_created") == 3


async def test_unpaid_execute_returns_standard_challenge_and_no_data(system):
    request = purchase(system)
    response = await system["agent"].http.post("/execute", json=request.model_dump())
    assert response.status_code == 402
    challenge = Challenge.from_www_authenticate(response.headers["WWW-Authenticate"])
    assert challenge.request["amount"] == "400000"
    assert challenge.header == "Payment-Authorization"
    assert challenge.request["methodDetails"]["chainId"] == 42431
    assert "data" not in response.json()
    assert system["chain"].broadcasts == 0
    assert system["engine"].store.balance()["reserved_cents"] == 0


async def test_concurrent_retries_do_not_create_another_payment(system):
    request = purchase(system)
    results = await asyncio.gather(*(system["agent"].execute(request) for _ in range(4)))
    assert len({r["execution_id"] for r in results}) == 1
    assert system["chain"].broadcasts == system["chain"].signatures == 2
    assert system["providers"].calls == 1


async def test_execute_budget_does_not_shrink_session_ceiling(system):
    await system["agent"].execute(purchase(system, "legal-liabilities", budget=50))
    balance = system["engine"].store.balance()
    assert balance["budget_cents"] == 1500
    assert balance["spent_cents"] == 50
    assert balance["remaining_cents"] == 1450

    result = await system["agent"].execute(purchase(system, key="purchase-0002", budget=1500))
    assert result["status"] == "completed"
    assert system["engine"].store.balance()["budget_cents"] == 1500
    assert system["engine"].store.balance()["remaining_cents"] == 1410
    assert system["chain"].broadcasts == 4


async def test_session_budget_from_reset_caps_purchases_as_remaining_falls(system):
    Agent.result(await system["agent"].http.post("/demo/reset", json={"budget_cents": 70}))

    await system["agent"].execute(purchase(system, "legal-liabilities", budget=50))
    balance = system["engine"].store.balance()
    assert balance["budget_cents"] == 70
    assert balance["spent_cents"] == 50
    assert balance["remaining_cents"] == 20

    with pytest.raises(OpenMCPError, match="budget"):
        await system["agent"].execute(purchase(system, key="purchase-0002", budget=1500))
    assert system["engine"].store.balance()["budget_cents"] == 70
    assert system["chain"].broadcasts == 2


async def test_gateway_reset_sets_positive_budget_and_defaults(system):
    original_session = system["engine"].store.balance()["session_id"]

    reduced = Agent.result(
        await system["agent"].http.post("/demo/reset", json={"budget_cents": 500})
    )
    assert reduced["session_id"] != original_session
    assert reduced["budget_cents"] == 500

    raised = Agent.result(
        await system["agent"].http.post("/demo/reset", json={"budget_cents": 50_000})
    )
    assert raised["budget_cents"] == 50_000

    Agent.result(await system["agent"].http.post("/demo/reset", json={"budget_cents": 400}))
    defaulted = Agent.result(await system["agent"].http.post("/demo/reset"))
    assert defaulted["budget_cents"] == system["settings"].budget_cents

    Agent.result(await system["agent"].http.post("/demo/reset", json={"budget_cents": 350}))
    explicit_null = Agent.result(
        await system["agent"].http.post("/demo/reset", json={"budget_cents": None})
    )
    assert explicit_null["budget_cents"] == system["settings"].budget_cents


@pytest.mark.parametrize(
    "body",
    [
        {"budget_cents": -1},
        {"budget_cents": 0},
        {"budget_cents": 1.5},
        {"budget_cents": "100"},
        {"budget_cents": True},
        {"budget_cents": 100, "unexpected": True},
    ],
)
async def test_gateway_reset_rejects_invalid_budget(system, body):
    session_id = system["engine"].store.balance()["session_id"]

    response = await system["agent"].http.post("/demo/reset", json=body)

    assert response.status_code == 422
    assert system["engine"].store.balance()["session_id"] == session_id


async def test_provider_failure_keeps_incoming_receipt_and_retries_without_repaying(system):
    system["providers"].fail_before_payment = True
    request = purchase(system)
    with pytest.raises(OpenMCPError) as error:
        await system["agent"].execute(request)
    assert error.value.retryable
    assert system["chain"].broadcasts == 1
    assert system["engine"].store.balance()["spent_cents"] == 40
    with pytest.raises(OpenMCPError, match="pending"):
        system["engine"].store.reset(1500)
    system["providers"].fail_before_payment = False
    result = await system["agent"].execute(request)
    assert result["status"] == "completed"
    assert system["chain"].broadcasts == 2


async def test_lost_provider_response_replays_saved_credential(system):
    system["providers"].lose_response_once = True
    request = purchase(system)
    with pytest.raises(OpenMCPError):
        await system["agent"].execute(request)
    assert system["chain"].broadcasts == 2
    result = await system["agent"].execute(request)
    assert result["status"] == "completed"
    assert system["chain"].broadcasts == system["chain"].signatures == 2


async def test_restart_recovers_pending_payment_without_signing_again(system):
    settings, chain = system["settings"], system["chain"]
    system["providers"].lose_response_once = True
    request = purchase(system)
    with pytest.raises(OpenMCPError):
        await system["agent"].execute(request)
    await system["agent"].close()
    await system["engine"].close()
    outgoing = PaidClient(
        settings,
        "openmcp",
        transport=httpx.ASGITransport(app=system["providers"].app),
        method=chain.method(settings.addresses()["openmcp"]),
        chain=chain,
    )
    engine = Engine(settings, incoming_intent=chain.intent(), outgoing=outgoing, chain=chain)
    transport = httpx.ASGITransport(app=create_app(settings, engine))
    paid = PaidClient(
        settings,
        "agent",
        transport=transport,
        method=chain.method(settings.addresses()["agent"]),
        chain=chain,
    )
    agent = Agent(settings, paid=paid, transport=transport)
    try:
        result = await agent.execute(request)
        assert result["status"] == "completed"
        assert chain.broadcasts == chain.signatures == 2
        assert engine.store.balance()["spent_cents"] == 40
        assert system["providers"].calls == 1
    finally:
        await agent.close()
        await engine.close()


async def test_provider_cached_data_requires_original_paid_credential(system):
    result = await system["agent"].execute(purchase(system))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system["providers"].app), base_url="http://provider"
    ) as client:
        response = await client.post(
            "/operational-health",
            json={"company": "FreightFlow"},
            headers={
                "Idempotency-Key": result["execution_id"],
                "X-OpenMCP-Execution-ID": result["execution_id"],
            },
        )
    assert response.status_code == 403
    assert "content" not in response.json()
    assert system["chain"].broadcasts == 2


async def test_wrong_provider_price_never_signs_outgoing_payment(system):
    system["providers"].wrong_price = True
    with pytest.raises(OpenMCPError) as error:
        await system["agent"].execute(purchase(system))
    assert error.value.code == "unapproved_challenge"
    assert system["chain"].broadcasts == system["chain"].signatures == 1


@pytest.mark.parametrize(
    "field,value",
    [("amount", "4000000"), ("recipient", "0x" + "0" * 40), ("currency", "0x" + "1" * 40)],
)
async def test_client_rejects_mutated_payment_terms(system, field, value):
    req = purchase(system)
    body = req.model_dump()
    fingerprint = hashlib.sha256(canonical(body)).hexdigest()
    challenge = await system["engine"].execute(req)
    challenge.request[field] = value
    with pytest.raises(OpenMCPError, match="does not match"):
        PaidClient.check_challenge(
            challenge,
            canonical(body),
            system["engine"].addresses["openmcp"],
            40,
            memo_for(fingerprint),
        )
    assert system["chain"].signatures == 0


async def test_reuse_key_with_different_request_is_rejected(system):
    request = purchase(system)
    await system["agent"].execute(request)
    with pytest.raises(OpenMCPError, match="another payment"):
        await system["agent"].execute(request.model_copy(update={"payload": {"company": "Other"}}))
    assert system["chain"].broadcasts == 2


async def test_mcp_tools_actually_use_agent_wallet(system):
    async with create_connected_server_and_client_session(
        create_mcp(agent=system["agent"])
    ) as session:
        assert {t.name for t in (await session.list_tools()).tools} == {
            "discover",
            "balance",
            "execute",
        }
        result = await session.call_tool("execute", purchase(system).model_dump())
        assert not result.isError
        assert result.structuredContent["price_cents"] == 40
        assert result.structuredContent["openmcp_to_provider"]["reference"]
    assert system["chain"].broadcasts == 2


async def test_auth_and_reset(system):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=system["app"]), base_url="http://localhost"
    ) as client:
        assert (await client.get("/health")).json()["payment_mode"] == "mpp_tempo_testnet"
        assert (
            await client.post("/execute", json=purchase(system).model_dump())
        ).status_code == 401
    old = purchase(system)
    await system["agent"].execute(old)
    system["engine"].store.reset(1500)
    await system["agent"].execute(purchase(system))
    assert system["chain"].broadcasts == 4
