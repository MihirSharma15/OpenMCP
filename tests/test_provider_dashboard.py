import json

import httpx

from tests.test_demo_runner import assert_no_blocked_keys, post, runner, wait_for_idle

__all__ = ["runner"]


async def test_provider_history_survives_reset_and_does_not_repay(runner):
    client = runner["client"]
    empty = (await client.get("/providers")).json()
    assert empty["transactions"] == []
    assert len(empty["providers"]) == 3
    assert {service["provider_amount_cents"] for service in empty["providers"]} == {27, 36, 45}
    assert {service["endpoint_path"] for service in empty["providers"]} == {
        "/operational-health",
        "/legal-liabilities",
        "/competitor-market-share",
    }
    assert all("wallet_balance" not in service for service in empty["providers"])

    assert (await post(client, "/run", {"mode": "all"})).status_code == 202
    await wait_for_idle(client)
    old = (await client.get("/providers", params={"chain": 1})).json()
    assert len(old["transactions"]) == 3
    assert sum(row["provider_amount_cents"] for row in old["transactions"]) == 108
    assert all(row["paid_at"] >= row["created_at"] for row in old["transactions"])
    assert all(service["wallet_balance"] for service in old["providers"])
    assert all("data" not in row for row in old["transactions"])
    assert_no_blocked_keys(old)

    assert (await post(client, "/reset")).status_code == 200
    fresh = (await client.get("/providers")).json()
    assert fresh["transactions"] == old["transactions"]
    assert fresh["agent"]["remaining_cents"] == 1500
    assert sum(service["session_earned_cents"] for service in fresh["providers"]) == 0

    assert (await post(client, "/run", {"mode": "next"})).status_code == 202
    await wait_for_idle(client)
    after = (await client.get("/providers")).json()
    assert len(after["transactions"]) == 4
    assert len({row["execution_id"] for row in after["transactions"]}) == 4
    assert runner["chain"].broadcasts == 8
    # Repeated observation never signs or settles another payment.
    await client.get("/providers")
    assert runner["chain"].broadcasts == 8


async def test_provider_pending_is_not_a_received_payment(runner):
    runner["providers"].fail_before_payment = True
    await post(runner["client"], "/run", {"mode": "next"})
    await wait_for_idle(runner["client"])
    state = (await runner["client"].get("/providers")).json()
    row = state["transactions"][0]
    assert row["agent_to_openmcp"]["status"] == "success"
    assert row["status"] == "provider_pending"
    assert row["openmcp_to_provider"] is None
    assert row["paid_at"] is None
    assert sum(service["session_earned_cents"] for service in state["providers"]) == 0


async def test_verified_provider_payment_is_visible_before_fulfillment(runner):
    await post(runner["client"], "/run", {"mode": "next"})
    await wait_for_idle(runner["client"])
    store = runner["engine"].store
    row = store.transactions()[0]
    # Model a response failure after the independently verified provider receipt.
    store.update(row, "provider_pending", outgoing_receipt=None, data=None)
    state = (await runner["client"].get("/providers")).json()
    payment = state["transactions"][0]
    assert payment["status"] == "provider_pending"
    assert payment["openmcp_to_provider"]["reference"] == row["outgoing_receipt"]["reference"]
    assert payment["paid_at"] is not None
    assert (
        sum(service["session_earned_cents"] for service in state["providers"])
        == payment["provider_amount_cents"]
    )
    # A duplicate event must not turn one payment into two earnings entries.
    store.event(row, "provider_payment_confirmed", receipt=row["outgoing_receipt"])
    repeated = (await runner["client"].get("/providers")).json()["transactions"]
    assert len(repeated) == 1
    assert repeated[0]["paid_at"] == payment["paid_at"]


async def test_provider_feed_authentication_errors_and_secrets(runner, monkeypatch):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runner["app"]),
        base_url="http://localhost",
    ) as client:
        assert (await client.get("/providers/dashboard")).status_code == 401

    async def unavailable(_address):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(runner["chain"], "balance", unavailable)
    response = await runner["client"].get("/providers", params={"chain": 1})
    assert response.headers["cache-control"] == "no-store"
    state = response.json()
    assert all(service["wallet_balance"]["error"] for service in state["providers"])
    assert_no_blocked_keys(state)
    serialized = json.dumps(state)
    assert runner["settings"].api_token.get_secret_value() not in serialized
    assert runner["settings"].payment_secret.get_secret_value() not in serialized
    assert (await runner["client"].get("/providers", params={"chain": 2})).status_code == 422
    assert (
        await runner["client"].get("/providers", headers={"Host": "evil.example"})
    ).status_code == 400
