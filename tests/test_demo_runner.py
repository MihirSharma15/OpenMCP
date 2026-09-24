import json

import httpx
import pytest

from demo_runner.app import START_COMMAND, create_app
from openmcp.models import ExecuteRequest, OpenMCPError

DEMO_HEADERS = {"X-OpenMCP-Demo": "1"}


@pytest.fixture
async def runner(system, tmp_path):
    observer_settings = system["settings"].model_copy(
        update={"wallets": tmp_path / "observer-without-wallet-files"}
    )
    app = create_app(observer_settings, transport=httpx.ASGITransport(app=system["app"]))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
        ) as client:
            yield {
                **system,
                "app": app,
                "gateway_app": system["app"],
                "client": client,
                "observer_settings": observer_settings,
            }


async def post(client: httpx.AsyncClient, path: str, body: dict | None = None):
    return await client.post(path, json={} if body is None else body, headers=DEMO_HEADERS)


def purchase(runner, endpoint: str, key: str, *, budget: int = 1500):
    price = runner["engine"].catalog[endpoint].price_cents
    return ExecuteRequest(
        session_id=runner["engine"].store.balance()["session_id"],
        endpoint_id=endpoint,
        payload={"company": "FreightFlow"},
        idempotency_key=key,
        max_price_cents=price,
        budget_cents=budget,
    )


def assert_no_blocked_keys(value):
    if isinstance(value, list):
        for item in value:
            assert_no_blocked_keys(item)
    elif isinstance(value, dict):
        blocked = {
            "api_token",
            "authorization",
            "challenge",
            "credential",
            "header",
            "incoming_credential",
            "openmcp_api_token",
            "openmcp_mpp_secret",
            "payment_authorization",
            "payment_secret",
            "private_key",
            "secret",
        }
        assert not (set(value) & blocked)
        for item in value.values():
            assert_no_blocked_keys(item)


async def test_state_is_dashboard_only_and_runner_needs_no_wallet(runner):
    wallet_dir = runner["observer_settings"].wallets
    assert not wallet_dir.exists()
    signatures = runner["chain"].signatures

    response = await runner["client"].get("/state")

    assert response.status_code == 200
    state = response.json()
    assert set(state) == {"dashboard"}
    assert "wallet_balance" not in state["dashboard"]["agent"]
    assert runner["chain"].signatures == signatures
    runtime = runner["app"].state.demo_runner
    assert not hasattr(runtime, "agent")
    assert not hasattr(runtime, "paid")
    assert not wallet_dir.exists()

    with_chain = await runner["client"].get("/state", params={"chain": 1})
    assert with_chain.status_code == 200
    assert "wallet_balance" in with_chain.json()["dashboard"]["agent"]
    assert runner["chain"].signatures == signatures
    assert_no_blocked_keys(with_chain.json())


@pytest.mark.parametrize("path", ["/run", "/pause", "/discover"])
async def test_payment_and_discovery_routes_are_removed(runner, path):
    response = await post(runner["client"], path)

    assert response.status_code == 404


async def test_reset_sets_positive_budget_and_defaults(runner):
    old_session = runner["engine"].store.balance()["session_id"]

    reduced = await post(runner["client"], "/reset", {"budget_cents": 500})
    assert reduced.status_code == 200
    assert reduced.json()["session_id"] != old_session
    assert reduced.json()["budget_cents"] == 500

    raised = await post(runner["client"], "/reset", {"budget_cents": 50_000})
    assert raised.status_code == 200
    assert raised.json()["budget_cents"] == 50_000

    await post(runner["client"], "/reset", {"budget_cents": 400})
    defaulted = await post(runner["client"], "/reset")
    assert defaulted.status_code == 200
    assert defaulted.json()["budget_cents"] == runner["settings"].budget_cents

    state = (await runner["client"].get("/state")).json()
    assert state["dashboard"]["agent"]["spent_cents"] == 0
    assert state["dashboard"]["transactions"] == []


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
async def test_reset_rejects_invalid_budgets(runner, body):
    session_id = runner["engine"].store.balance()["session_id"]

    response = await post(runner["client"], "/reset", body)

    assert response.status_code == 422
    assert runner["engine"].store.balance()["session_id"] == session_id


async def test_reduced_session_cap_overrides_execute_budget(runner):
    reset = await post(runner["client"], "/reset", {"budget_cents": 30})
    assert reset.status_code == 200
    assert reset.json()["budget_cents"] == 30

    with pytest.raises(OpenMCPError) as error:
        await runner["agent"].execute(
            purchase(runner, "legal-liabilities", "observer-cap-0001", budget=1500)
        )

    assert error.value.code == "insufficient_budget"
    assert runner["chain"].signatures == 0
    assert runner["chain"].broadcasts == 0
    assert runner["engine"].store.balance()["budget_cents"] == 30


async def test_custom_session_budget_decreases_remaining_without_shrinking_ceiling(runner):
    reset = await post(runner["client"], "/reset", {"budget_cents": 500})
    assert reset.status_code == 200
    assert reset.json()["budget_cents"] == 500

    await runner["agent"].execute(
        purchase(runner, "operational-health", "observer-spend-0001", budget=40)
    )

    balance = runner["engine"].store.balance()
    assert balance["budget_cents"] == 500
    assert balance["spent_cents"] == 40
    assert balance["remaining_cents"] == 460


async def test_mutations_require_local_host_demo_header_and_json(runner):
    client = runner["client"]

    foreign = await client.get("/state", headers={"Host": "evil.example"})
    assert foreign.status_code == 400
    assert foreign.json()["error"]["code"] == "invalid_host"

    missing_header = await client.post("/reset", json={"budget_cents": 500})
    assert missing_header.status_code == 403
    assert missing_header.json()["error"]["code"] == "demo_header_required"

    wrong_type = await client.post("/reset", content=b"{}", headers=DEMO_HEADERS)
    assert wrong_type.status_code == 415
    assert wrong_type.json()["error"]["code"] == "json_required"

    malformed = await client.post(
        "/reset",
        content=b"{",
        headers={**DEMO_HEADERS, "Content-Type": "application/json"},
    )
    assert malformed.status_code == 422


async def test_gateway_offline_returns_shaped_errors(runner):
    def offline(request):
        raise httpx.ConnectError("offline", request=request)

    runtime = runner["app"].state.demo_runner
    original_http = runtime.http
    unavailable = httpx.AsyncClient(
        base_url=runner["settings"].base_url,
        transport=httpx.MockTransport(offline),
    )
    runtime.http = unavailable
    try:
        state_response = await runner["client"].get("/state")
        reset_response = await post(runner["client"], "/reset", {"budget_cents": 500})
    finally:
        runtime.http = original_http
        await unavailable.aclose()

    for response in (state_response, reset_response):
        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "gateway_unavailable"
        assert START_COMMAND in error["message"]
        assert error["retryable"] is True


async def test_pending_gateway_execution_still_blocks_reset(runner):
    runner["providers"].fail_before_payment = True
    with pytest.raises(OpenMCPError) as error:
        await runner["agent"].execute(purchase(runner, "operational-health", "pending-reset-0001"))
    assert error.value.code == "provider_pending"

    response = await post(runner["client"], "/reset", {"budget_cents": 500})

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "pending_execution",
            "message": "Resolve pending MPP payments before resetting.",
            "retryable": False,
        }
    }


async def test_observer_responses_strip_tokens_secrets_and_receipt_headers(runner):
    await runner["agent"].execute(purchase(runner, "operational-health", "observer-public-0001"))
    signatures = runner["chain"].signatures

    response = await runner["client"].get("/state", params={"chain": 1})

    assert response.status_code == 200
    state = response.json()
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
    assert all(secret not in text for secret in secrets)
    assert_no_blocked_keys(state)
    transaction = state["dashboard"]["transactions"][0]
    assert transaction["agent_to_openmcp"]["reference"]
    assert transaction["agent_to_openmcp"]["explorer_url"]
    assert transaction["openmcp_to_provider"]["reference"]
    assert transaction["openmcp_to_provider"]["explorer_url"]
    assert runner["chain"].signatures == signatures
