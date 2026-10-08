"""Nansen tests mock all vendor requests, including full PostgreSQL billing flows."""

import json
from unittest.mock import Mock

import httpx
import pytest

from openmcp.integrations.nansen.catalog import (
    BALANCES,
    ORIGIN,
    SCREENER,
    SERVICES,
    TRANSACTIONS,
    provider,
)
from openmcp.integrations.nansen.cli import write_catalog
from openmcp.integrations.nansen.protocol import Rejected, credit_rate, parse, prepare
from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings, Provider
from openmcp.product.settlement import TerminalFailure
from openmcp.product.worker import Worker
from tests import test_product_api_call as api_tests

postgres_url = api_tests.postgres_url
store = api_tests.store
SECRET = "nansen-mocked-secret"
ADDRESS = "0x" + "ab" * 20
HEADERS = {
    "x-request-id": "vendor-request-123",
    "x-nansen-credits-used": "1",
    "x-nansen-credits-cost": "1",
}


def service(identifier):
    return next(
        q for q in Provider.model_validate(provider()).queries if q.endpoint_id == identifier
    )


def sample(identifier):
    if identifier == SCREENER:
        payload = {"chains": ["ethereum"], "timeframe": "24h", "limit": 1}
        row = {
            "chain": "ethereum",
            "token_address": ADDRESS,
            "token_symbol": "ETH",
            "liquidity": 1234,
            "price_usd": 2000,
        }
    else:
        payload = {"chain": "ethereum", "address": ADDRESS, "limit": 1}
        if identifier == BALANCES:
            row = {
                "chain": "ethereum",
                "address": ADDRESS,
                "token_address": ADDRESS,
                "token_symbol": "ETH",
                "token_amount": 2,
                "value_usd": 4000,
            }
        else:
            payload["date"] = {"from": "2026-10-01", "to": "2026-10-07"}
            row = {
                "chain": "ethereum",
                "transaction_hash": "0x123",
                "block_timestamp": "2026-10-01T00:00:00Z",
                "method": "received",
                "source_type": "transfer",
                "tokens_received": [
                    {
                        "token_symbol": "ETH",
                        "token_amount": 1,
                        "token_address": ADDRESS,
                        "chain": "ethereum",
                        "from_address": ADDRESS,
                        "to_address": ADDRESS,
                        "from_address_label": "DO NOT EXPOSE",
                    }
                ],
            }
    return payload, {"data": [row], "pagination": {"page": 1, "per_page": 1, "is_last_page": False}}


@pytest.mark.parametrize("identifier", SERVICES)
def test_protocol_and_private_catalog(identifier):
    payload, body = sample(identifier)
    request, key = prepare(identifier, service(identifier).url, "live", payload, SECRET)
    assert key == SECRET and SECRET not in json.dumps(request)
    assert request["pagination"] == {"page": 1, "per_page": 1}
    if identifier == SCREENER:
        assert request["filters"]["trader_type"] == "all"
    else:
        assert request["hide_spam_token"] is True
    data, receipt, cost = parse(identifier, payload, body, HEADERS)
    assert cost == 1000 and receipt["credits_used"] == 1
    assert data["pagination"]["next_page"] == 2 and "Nansen" in data["attribution"]["name"]
    assert "DO NOT EXPOSE" not in json.dumps(data)
    public = service(identifier).public()
    assert ORIGIN not in json.dumps(public) and "provider_price_cents" not in public
    assert "secret_ref" not in public


@pytest.mark.parametrize(
    "payload",
    [
        {"chain": "ethereum", "address": "0x1"},
        {"chain": "ethereum", "address": ADDRESS + "\n"},
        {"chain": "solana", "address": ADDRESS},
        {"chain": "all", "address": ADDRESS},
        {"chain": "ethereum", "address": ADDRESS, "url": "https://evil.example"},
        {"chain": "ethereum", "address": ADDRESS, "premium_labels": True},
        {"chain": "ethereum", "address": ADDRESS, "limit": 101},
        {"chain": "ethereum", "address": ADDRESS, "limit": True},
        {"chain": "ethereum", "address": ADDRESS, "page": 0},
        {"chain": "solana", "address": "1" * 33},
    ],
)
def test_invalid_wallet_inputs(payload):
    with pytest.raises(ValueError):
        prepare(BALANCES, service(BALANCES).url, "test", payload, SECRET)


@pytest.mark.parametrize(
    "address", ["So11111111111111111111111111111111111111112", "11111111111111111111111111111111"]
)
def test_solana_public_key(address):
    request, _ = prepare(
        BALANCES, service(BALANCES).url, "live", {"chain": "solana", "address": address}, SECRET
    )
    assert request["address"] == address


@pytest.mark.parametrize(
    "dates",
    [
        {"from": "2026-10-02", "to": "2026-10-01"},
        {"from": "2026-01-01", "to": "2026-10-01"},
        {"from": "2026-02-30", "to": "2026-03-01"},
        {"from": "2026-10-01T00:00:00Z", "to": "2026-10-02"},
        {"from": "2026-10-01\n", "to": "2026-10-02"},
    ],
)
def test_date_bounds(dates):
    payload, _ = sample(TRANSACTIONS)
    payload["date"] = dates
    with pytest.raises(ValueError):
        prepare(TRANSACTIONS, service(TRANSACTIONS).url, "test", payload, SECRET)


@pytest.mark.parametrize(
    "updates",
    [
        {"chains": ["ethereum"] * 2},
        {"chains": ["all"]},
        {"chains": ["ethereum"] * 6},
        {"timeframe": "1y"},
        {"date": {"from": "2026-01-01"}},
        {"filters": {"only_smart_money": True}},
        {"filters": {"premium_labels": True}},
        {"filters": {"liquidity": {"min": 10, "max": 1}}},
        {"filters": {"liquidity": {"min": float("inf")}}},
        {"sort_by": "invalid"},
    ],
)
def test_screener_limits(updates):
    payload, _ = sample(SCREENER)
    with pytest.raises(ValueError):
        prepare(SCREENER, service(SCREENER).url, "test", payload | updates, SECRET)


@pytest.mark.parametrize("value", ["-1", "20001", "1.5", "nan", " 1000", "1000\n"])
def test_invalid_cost_configuration(value):
    with pytest.raises(ValueError):
        credit_rate(value)


@pytest.mark.parametrize("identifier", SERVICES)
def test_empty_page_and_estimated_cost(identifier):
    payload, body = sample(identifier)
    body["data"] = []
    body["pagination"]["is_last_page"] = True
    data, receipt, cost = parse(identifier, payload, body, {"x-request-id": "ref"})
    assert data["data"] == [] and data["pagination"]["next_page"] is None
    assert cost == 1000 and receipt["credit_basis"] == "documented_tariff_estimate"


@pytest.mark.parametrize("identifier", SERVICES)
@pytest.mark.parametrize(
    "issue", ["error", "missing", "row", "chain", "page", "limit", "boolean", "overflow"]
)
def test_bad_results(identifier, issue):
    payload, body = sample(identifier)
    if issue == "error":
        body["error"] = "bad"
    elif issue == "missing":
        del body["data"]
    elif issue == "row":
        body["data"][0] = {}
    elif issue == "chain":
        body["data"][0]["chain"] = "base"
    elif issue == "page":
        body["pagination"]["page"] = 2
    elif issue == "limit":
        body["pagination"]["per_page"] = 101
    elif issue == "boolean":
        body["pagination"]["is_last_page"] = 1
    else:
        body["data"] *= 2
    with pytest.raises(ValueError):
        parse(identifier, payload, body, HEADERS)


@pytest.mark.parametrize(
    "headers",
    [
        HEADERS | {"x-nansen-credits-used": "10"},
        HEADERS | {"x-nansen-credits-cost": "2"},
        HEADERS | {"x-nansen-credits-used": "-1"},
        HEADERS | {"x-nansen-credits-used": "1.0"},
        HEADERS | {"x-request-id": ""},
    ],
)
def test_bad_credit_or_reference_headers(headers):
    payload, body = sample(BALANCES)
    with pytest.raises(ValueError):
        parse(BALANCES, payload, body, headers)


def test_mismatched_wallet_and_nonfinite_values():
    payload, body = sample(BALANCES)
    body["data"][0]["address"] = "0x" + "cd" * 20
    with pytest.raises(ValueError):
        parse(BALANCES, payload, body, HEADERS)
    body["data"][0]["address"] = ADDRESS
    body["data"][0]["value_usd"] = float("nan")
    with pytest.raises(ValueError):
        parse(BALANCES, payload, body, HEADERS)


def test_zero_cost_error_requires_explicit_evidence():
    payload, _ = sample(BALANCES)
    body = {"error": "Invalid input", "code": "missing_field", "status": 422}
    with pytest.raises(Rejected):
        parse(BALANCES, payload, body, {"x-nansen-credits-used": "0"}, 422)
    for headers, status in [
        ({}, 422),
        ({"x-nansen-credits-used": "1"}, 422),
        ({"x-nansen-credits-used": "0"}, 500),
        ({"x-nansen-credits-used": "0"}, 200),
    ]:
        with pytest.raises(ValueError) as exc:
            parse(BALANCES, payload, body, headers, status)
        assert not isinstance(exc.value, Rejected)


def test_catalog_merge_and_target_bounds(tmp_path):
    from openmcp.integrations.builtwith.catalog import provider as builtwith

    path = tmp_path / "catalog.json"
    path.write_text(json.dumps([builtwith()]))
    write_catalog(path, "live")
    assert [p["provider_id"] for p in json.loads(path.read_text())] == ["builtwith", "nansen"]
    for field, value in [
        ("url", ORIGIN + "/api/v1/smart-money/holdings"),
        ("url", ORIGIN + "/api/v1/token-screener?apikey=bad"),
        ("settlement", "mpp"),
    ]:
        bad = provider()
        bad["queries"][0][field] = value
        with pytest.raises(ValueError):
            Provider.model_validate(bad)


@pytest.mark.parametrize("identifier", SERVICES)
async def test_account_workflow_and_recovery(store, monkeypatch, identifier):
    monkeypatch.setenv("NANSEN_API_KEY", SECRET)
    monkeypatch.setenv("NANSEN_CREDIT_COST_MICROUSD", "1000")
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("nansen-owner")["account_id"]
    api_tests.credit(store, owner)
    principal, credential = api_tests.grant(store, owner)
    payload, body = sample(identifier)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "POST" and request.url == service(identifier).url
        assert request.headers["apikey"] == SECRET and "Authorization" not in request.headers
        assert SECRET not in request.content.decode() and SECRET not in str(request.url)
        expected, _ = prepare(identifier, service(identifier).url, "test", payload, SECRET)
        assert json.loads(request.content) == expected
        return httpx.Response(200, json=body, headers=HEADERS)

    settings = ProductSettings(_env_file=None)
    caller = ApiKeyCaller(settings, store, transport=httpx.MockTransport(handler))
    worker = Worker(settings, store, Mock(), api_caller=caller)
    app = create_app(
        settings, store=store, verifier=api_tests.Closable(), stripe=api_tests.Closable()
    )
    auth = {"Authorization": "Bearer " + credential["secret"]}
    request = {"endpoint_id": identifier, "payload": payload, "max_price_cents": 2}
    try:
        await worker.tick()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api.test"
        ) as client:
            found = await client.post("/v1/discover", headers=auth, json={"query": "Nansen"})
            assert (
                found.status_code == 200
                and identifier in found.text
                and SECRET not in found.text
                and ORIGIN not in found.text
            )
            invalid = await client.post(
                "/v1/execute",
                headers=auth | {"Idempotency-Key": "invalid"},
                json=request | {"payload": payload | {"apikey": "hacker"}},
            )
            assert invalid.status_code == 422 and len(calls) == 0
            headers = auth | {"Idempotency-Key": "once"}
            first = await client.post("/v1/execute", headers=headers, json=request)
            assert first.status_code == 202 and store.account(owner)["reserved_cents"] == 2
            await worker.tick()
            replay = await client.post("/v1/execute", headers=headers, json=request)
            assert (
                replay.json()["status"] == "completed"
                and replay.json()["execution_id"] == first.json()["execution_id"]
            )
            row = store.execution_internal(first.json()["execution_id"])
            assert row["provider_cost_microusd"] == 1000 and SECRET not in json.dumps(
                row, default=str
            )
            assert (
                store.account(owner)["spent_cents"] == 2
                and store.account(owner)["reserved_cents"] == 0
            )
            saved = store.reserve(principal, "crash", request, service(identifier))
            data, receipt, cost = parse(identifier, payload, body, HEADERS)
            store.mark_sent(saved["execution_id"])
            store.mark_paid(saved["execution_id"], receipt, data=data, cost_microusd=cost)
            await worker.tick()
            assert (
                store.execution_internal(saved["execution_id"])["status"] == "completed"
                and len(calls) == 1
            )
        store.migrate()
        assert store.account(owner)["spent_cents"] == 4
    finally:
        await caller.close()


@pytest.mark.parametrize(
    "status,used,outcome",
    [
        (422, "0", "refunded"),
        (422, "1", "needs_review"),
        (500, "0", "needs_review"),
        (429, None, "needs_review"),
        (200, "10", "needs_review"),
    ],
)
async def test_failure_billing_policy(store, monkeypatch, status, used, outcome):
    monkeypatch.setenv("NANSEN_API_KEY", SECRET)
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("nansen-failure")["account_id"]
    api_tests.credit(store, owner)
    principal, _ = api_tests.grant(store, owner)
    payload, body = sample(BALANCES)
    request = {"endpoint_id": BALANCES, "payload": payload, "max_price_cents": 2}
    calls = []

    def handler(request):
        calls.append(request)
        headers = {"x-request-id": "ref"}
        if used is not None:
            headers["x-nansen-credits-used"] = used
        return httpx.Response(
            status,
            json=body
            if status == 200
            else {"error": "failed", "code": "invalid_field_value", "status": status},
            headers=headers,
        )

    settings = ProductSettings(_env_file=None)
    caller = ApiKeyCaller(settings, store, transport=httpx.MockTransport(handler))
    worker = Worker(settings, store, Mock(), api_caller=caller)
    try:
        first = store.reserve(principal, "once", request, service(BALANCES))
        await worker.tick()
        await worker.tick()
        row = store.execution_internal(first["execution_id"])
        assert (
            row["status"] == outcome
            and len(calls) == 1
            and store.account(owner)["spent_cents"] == 0
        )
        assert store.account(owner)["reserved_cents"] == (0 if outcome == "refunded" else 2)
        assert (
            store.service_disabled(BALANCES) is False
        )  # Existing API-key sent-state policy holds without disabling.
    finally:
        await caller.close()


async def test_invalid_key_prevents_transport(monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", "bad\nkey")
    fake = Mock()
    fake.provider_secret_ref.return_value = "NANSEN_API_KEY"
    caller = ApiKeyCaller(
        ProductSettings(_env_file=None),
        fake,
        transport=httpx.MockTransport(lambda request: pytest.fail("must not send")),
    )
    try:
        with pytest.raises(TerminalFailure):
            await caller.purchase(
                {
                    "execution_id": "bad",
                    "payment_status": "unsigned",
                    "service": service(BALANCES).model_dump(),
                    "payload": sample(BALANCES)[0],
                }
            )
        fake.mark_sent.assert_not_called()
    finally:
        await caller.close()
