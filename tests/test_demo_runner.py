import asyncio
import json

import httpx
import pytest

from demo_runner.app import START_COMMAND, create_app
from openmcp.agent import Agent

DEMO_HEADERS = {"X-OpenMCP-Demo": "1"}


@pytest.fixture
async def runner(system):
    app = create_app(system["settings"], system["agent"])
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
        ) as client:
            yield {"app": app, "client": client, **system}


async def post(client: httpx.AsyncClient, path: str, body: dict | None = None):
    return await client.post(path, json=body or {}, headers=DEMO_HEADERS)


async def wait_for_idle(client: httpx.AsyncClient) -> dict:
    for _ in range(500):
        response = await client.get("/state", params={"chain": 0})
        assert response.status_code == 200
        state = response.json()
        if state["job"]["status"] == "idle":
            return state
        await asyncio.sleep(0.01)
    pytest.fail("demo runner job did not become idle")


def assert_no_blocked_keys(value):
    if isinstance(value, list):
        for item in value:
            assert_no_blocked_keys(item)
    elif isinstance(value, dict):
        blocked = {
            "authorization",
            "challenge",
            "credential",
            "header",
            "incoming_credential",
            "payment_authorization",
            "private_key",
            "secret",
        }
        assert not (set(value) & blocked)
        for item in value.values():
            assert_no_blocked_keys(item)


async def test_discovery_returns_live_gateway_catalog(runner):
    response = await post(runner["client"], "/discover")

    assert response.status_code == 200
    discovery = response.json()
    assert len(discovery["endpoints"]) == 3
    assert discovery["total_price_cents"] == 120
    assert {endpoint["price_cents"] for endpoint in discovery["endpoints"]} == {30, 40, 50}
    assert discovery["discovery_is_free"] is True

    state = (await runner["client"].get("/state")).json()
    assert state["discovery"] == discovery
    assert_no_blocked_keys(state)


async def test_run_all_makes_six_payments_and_replay_does_not_duplicate(runner):
    first = await post(runner["client"], "/run", {"mode": "all"})
    assert first.status_code == 202

    state = await wait_for_idle(runner["client"])
    transactions = state["dashboard"]["transactions"]
    assert len(transactions) == 3
    assert all(transaction["status"] == "completed" for transaction in transactions)
    assert runner["chain"].broadcasts == 6
    assert runner["providers"].calls == 3
    assert state["dashboard"]["agent"]["spent_cents"] == 120
    assert state["dashboard"]["agent"]["remaining_cents"] == 1380
    assert len(state["events"]) >= 21
    for transaction in transactions:
        assert transaction["agent_to_openmcp"]["reference"]
        assert transaction["openmcp_to_provider"]["reference"]
        assert "header" not in transaction["agent_to_openmcp"]
        assert "header" not in transaction["openmcp_to_provider"]

    second = await post(runner["client"], "/run", {"mode": "all"})
    assert second.status_code == 202
    replayed = await wait_for_idle(runner["client"])
    assert runner["chain"].broadcasts == 6
    assert runner["providers"].calls == 3
    assert len(replayed["dashboard"]["transactions"]) == 3


async def test_next_buys_exactly_one_service(runner):
    response = await post(runner["client"], "/run", {"mode": "next"})
    assert response.status_code == 202

    state = await wait_for_idle(runner["client"])
    completed = [
        transaction
        for transaction in state["dashboard"]["transactions"]
        if transaction["status"] == "completed"
    ]
    assert len(completed) == 1, state["job"]
    assert runner["chain"].broadcasts == 2
    assert runner["providers"].calls == 1


async def test_pause_stops_after_the_in_flight_purchase(runner, monkeypatch):
    original_execute = runner["agent"].execute
    purchase_completed = asyncio.Event()
    release_result = asyncio.Event()
    calls = 0

    async def held_execute(request):
        nonlocal calls
        calls += 1
        result = await original_execute(request)
        purchase_completed.set()
        await release_result.wait()
        return result

    monkeypatch.setattr(runner["agent"], "execute", held_execute)
    assert (await post(runner["client"], "/run", {"mode": "all"})).status_code == 202
    await asyncio.wait_for(purchase_completed.wait(), timeout=2)

    paused = await post(runner["client"], "/pause")
    assert paused.status_code == 200
    assert paused.json()["job"]["status"] == "pausing"
    release_result.set()

    state = await wait_for_idle(runner["client"])
    assert calls == 1
    assert runner["chain"].broadcasts == 2
    assert len(state["dashboard"]["transactions"]) == 1


async def test_reset_is_blocked_while_running_then_starts_new_session(runner, monkeypatch):
    original_execute = runner["agent"].execute
    purchase_completed = asyncio.Event()
    release_result = asyncio.Event()

    async def held_execute(request):
        result = await original_execute(request)
        purchase_completed.set()
        await release_result.wait()
        return result

    monkeypatch.setattr(runner["agent"], "execute", held_execute)
    old_session = runner["engine"].store.balance()["session_id"]
    assert (await post(runner["client"], "/run", {"mode": "all"})).status_code == 202
    await asyncio.wait_for(purchase_completed.wait(), timeout=2)

    conflict = await post(runner["client"], "/reset")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "job_running"

    release_result.set()
    await wait_for_idle(runner["client"])
    reset = await post(runner["client"], "/reset")
    assert reset.status_code == 200
    assert reset.json()["session_id"] != old_session
    state = (await runner["client"].get("/state")).json()
    assert state["discovery"] is None
    assert state["dashboard"]["agent"]["spent_cents"] == 0


async def test_mutations_require_local_host_demo_header_and_json(runner):
    client = runner["client"]

    foreign = await client.get("/state", headers={"Host": "evil.example"})
    assert foreign.status_code == 400
    assert foreign.json()["error"]["code"] == "invalid_host"

    missing_header = await client.post("/discover", json={})
    assert missing_header.status_code == 403
    assert missing_header.json()["error"]["code"] == "demo_header_required"

    wrong_type = await client.post("/discover", content=b"{}", headers=DEMO_HEADERS)
    assert wrong_type.status_code == 415
    assert wrong_type.json()["error"]["code"] == "json_required"

    malformed = await client.post(
        "/discover",
        content=b"{",
        headers={**DEMO_HEADERS, "Content-Type": "application/json"},
    )
    assert malformed.status_code == 422


async def test_concurrent_runs_create_only_one_job(runner, monkeypatch):
    original_discover = runner["agent"].discover
    release_discovery = asyncio.Event()

    async def held_discover(query, budget_cents):
        await release_discovery.wait()
        return await original_discover(query, budget_cents)

    monkeypatch.setattr(runner["agent"], "discover", held_discover)
    first, second = await asyncio.gather(
        post(runner["client"], "/run", {"mode": "next"}),
        post(runner["client"], "/run", {"mode": "next"}),
    )
    assert sorted([first.status_code, second.status_code]) == [202, 409]
    conflict = first if first.status_code == 409 else second
    assert conflict.json()["error"]["code"] == "job_running"

    release_discovery.set()
    await wait_for_idle(runner["client"])
    assert runner["chain"].broadcasts == 2


async def test_external_session_change_clears_cached_discovery(runner):
    discovery = (await post(runner["client"], "/discover")).json()
    old_session = discovery["session_id"]

    gateway_reset = Agent.result(await runner["agent"].http.post("/demo/reset"))
    assert gateway_reset["session_id"] != old_session

    state = (await runner["client"].get("/state")).json()
    assert state["dashboard"]["agent"]["session_id"] == gateway_reset["session_id"]
    assert state["discovery"] is None

    assert (await post(runner["client"], "/run", {"mode": "next"})).status_code == 202
    refreshed = await wait_for_idle(runner["client"])
    assert refreshed["discovery"]["session_id"] == gateway_reset["session_id"]
    assert len(refreshed["dashboard"]["transactions"]) == 1, refreshed["job"]


async def test_gateway_offline_returns_actionable_503(runner):
    original_http = runner["agent"].http

    def offline(request):
        raise httpx.ConnectError("offline", request=request)

    unavailable = httpx.AsyncClient(
        base_url=runner["settings"].base_url,
        transport=httpx.MockTransport(offline),
    )
    runner["agent"].http = unavailable
    try:
        response = await runner["client"].get("/state")
    finally:
        runner["agent"].http = original_http
        await unavailable.aclose()

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "gateway_unavailable"
    assert START_COMMAND in error["message"]
    assert error["retryable"] is True


async def test_gateway_domain_error_shape_passes_through(runner):
    runner["providers"].fail_before_payment = True
    assert (await post(runner["client"], "/run", {"mode": "next"})).status_code == 202

    state = await wait_for_idle(runner["client"])
    assert state["job"]["last_error"]["code"] == "provider_pending"
    assert state["job"]["last_error"]["retryable"] is True

    reset = await post(runner["client"], "/reset")
    assert reset.status_code == 409
    assert reset.json() == {
        "error": {
            "code": "pending_execution",
            "message": "Resolve pending MPP payments before resetting.",
            "retryable": False,
        }
    }


async def test_responses_never_expose_tokens_credentials_or_receipt_headers(runner):
    assert (await post(runner["client"], "/run", {"mode": "all"})).status_code == 202
    state = await wait_for_idle(runner["client"])
    text = json.dumps(state, sort_keys=True)

    secrets = [
        runner["settings"].api_token.get_secret_value(),
        runner["settings"].payment_secret.get_secret_value(),
    ]
    for row in runner["engine"].store.transactions():
        secrets.extend(
            receipt["header"]
            for receipt in (row["incoming_receipt"], row["outgoing_receipt"])
            if receipt
        )
    with runner["agent"].paid.journal.connection() as database:
        for row in database.execute("SELECT doc FROM payments"):
            saved = json.loads(row["doc"])
            secrets.extend([saved["authorization"], saved["challenge"]])

    assert all(secret not in text for secret in secrets)
    assert_no_blocked_keys(state)
