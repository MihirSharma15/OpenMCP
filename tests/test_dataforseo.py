"""Bounded vendor requests, fractional costs, and the account purchase lifecycle."""

import base64
import gzip
import json
import zlib
from unittest.mock import Mock

import httpx
import pytest

from openmcp.integrations.dataforseo.catalog import OVERVIEW, RELATED, SEARCH, provider
from openmcp.integrations.dataforseo.cli import write_catalog
from openmcp.integrations.dataforseo.protocol import Rejected, cost_microusd, parse, prepare
from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings, Provider
from openmcp.product.settlement import TerminalFailure
from openmcp.product.worker import Worker
from tests import test_product_api_call as api_tests
from tests.test_product_api_call import Closable, credit, grant

# Reuse the account tests' PostgreSQL fixture and its isolated per-test schema.
postgres_url = api_tests.postgres_url
store = api_tests.store

SECRET = base64.b64encode(b"test@example.com:private-test-password").decode()
PAYLOADS = {
    SEARCH: {"keyword": "C++ programming"},
    OVERVIEW: {"keywords": ["keyword research"]},
    RELATED: {"keyword": "keyword research", "limit": 3},
}


def service_for(endpoint_id, mode="test"):
    return next(
        q for q in Provider.model_validate(provider(mode)).queries if q.endpoint_id == endpoint_id
    )


def envelope(endpoint_id=SEARCH, *, cost=0.002, status=20000):
    keyword = {
        "keyword": "keyword research",
        "keyword_info": {"search_volume": 1200, "cpc": 1.25, "last_updated_time": "2026-10-01"},
        "keyword_properties": {"keyword_difficulty": 32},
        "search_intent_info": {"main_intent": "informational"},
    }
    items = {
        SEARCH: [
            {"type": "paid", "title": "Ad"},
            {"type": "organic", "title": "Result", "url": "https://example.com", "rank_group": 1},
        ],
        OVERVIEW: [keyword],
        RELATED: [{"keyword_data": keyword}],
    }[endpoint_id]
    return {
        "status_code": 20000,
        "cost": cost,
        "tasks": [
            {
                "id": "vendor-task-1",
                "status_code": status,
                "cost": cost,
                "result": [{"items": items}],
            }
        ],
    }


@pytest.mark.parametrize("endpoint_id", PAYLOADS)
def test_protocol_has_basic_auth_one_task_and_fixed_paid_limits(endpoint_id):
    service = service_for(endpoint_id)
    body, auth = prepare(endpoint_id, service.url, service.mode, PAYLOADS[endpoint_id], SECRET)
    assert auth == "Basic " + SECRET
    assert len(body) == 1 and body[0]["location_code"] == 2840
    assert body[0]["language_code"] == "en"
    if endpoint_id == SEARCH:
        assert body[0]["keyword"] == "C%2B%2B programming"
        assert body[0]["depth"] == 10 and body[0]["max_crawl_pages"] == 1
    else:
        assert body[0]["include_clickstream_data"] is False
        assert body[0]["include_serp_info"] is False
    if endpoint_id == RELATED:
        assert body[0]["depth"] == 3 and body[0]["include_seed_keyword"] is False


@pytest.mark.parametrize(
    "endpoint_id,payload",
    [
        (SEARCH, {"keyword": "site:example.com"}),
        (SEARCH, {"keyword": "site%3Aexample.com"}),
        (SEARCH, {"keyword": "  "}),
        (SEARCH, {"keyword": "test", "depth": 100}),
        (SEARCH, {"keyword": "test", "url": "https://evil.example"}),
        (RELATED, {"keyword": "test", "limit": 101}),
        (RELATED, {"keyword": "test", "include_clickstream_data": True}),
        (OVERVIEW, {"keywords": [str(i) for i in range(101)]}),
        (OVERVIEW, {"keywords": [" "]}),
        (OVERVIEW, {"keywords": ["word " * 11]}),
    ],
)
def test_invalid_or_more_expensive_requests_fail_before_sending(endpoint_id, payload):
    service = service_for(endpoint_id)
    with pytest.raises(ValueError, match="limits"):
        prepare(endpoint_id, service.url, service.mode, payload, SECRET)


def test_catalog_prevents_sandbox_live_confusion_and_arbitrary_destinations():
    for url in [
        "https://evil.example/v3/serp/google/organic/live/advanced",
        service_for(SEARCH, "live").url,
    ]:
        config = provider()
        config["queries"][0]["url"] = url
        with pytest.raises(ValueError, match="approved route"):
            Provider.model_validate(config)


@pytest.mark.parametrize("endpoint_id", PAYLOADS)
def test_normalized_results_and_exact_fractional_cost(endpoint_id):
    data, receipt, cost = parse(
        endpoint_id, "live", PAYLOADS[endpoint_id], envelope(endpoint_id, cost=0.01212)
    )
    assert cost == 12120 and receipt["cost_usd"] == "0.01212"
    assert data["is_demo_data"] is False and len(data["items"]) == 1
    if endpoint_id == SEARCH:
        assert data["items"][0]["title"] == "Result"
    else:
        assert data["items"][0]["search_volume"] == 1200
        assert data["items"][0]["keyword_difficulty"] == 32
        assert data["items"][0]["search_intent"] == "informational"
    demo, receipt, cost = parse(
        endpoint_id, "test", PAYLOADS[endpoint_id], envelope(endpoint_id, cost=0.01212)
    )
    assert demo["is_demo_data"] is True and cost == 0
    assert receipt["reported_cost_usd"] == "0.01212" and receipt["cost_usd"] == "0"


@pytest.mark.parametrize("value", [None, True, -1, "NaN", "Infinity", "0.0000001", {}, "bad"])
def test_unusable_cost_is_never_guessed(value):
    with pytest.raises(ValueError):
        cost_microusd(value)


def test_http_200_is_not_proof_of_completed_task_or_zero_cost():
    with pytest.raises(Rejected):
        parse(SEARCH, "live", PAYLOADS[SEARCH], envelope(status=40501, cost=0))
    for response in [
        envelope(status=40501),
        envelope(status=20100),
        {"status_code": 20000, "cost": 0, "tasks": []},
    ]:
        with pytest.raises(ValueError) as raised:
            parse(SEARCH, "live", PAYLOADS[SEARCH], response)
        assert not isinstance(raised.value, Rejected)
    inconsistent = envelope()
    inconsistent.update(status_code=40104, cost=0)
    with pytest.raises(ValueError) as raised:
        parse(SEARCH, "live", PAYLOADS[SEARCH], inconsistent)
    assert not isinstance(raised.value, Rejected)


def test_catalog_command_preserves_other_providers(tmp_path):
    from tests.test_product_api_call import api_service, provider_for

    path = tmp_path / "catalog.json"
    other = provider_for(api_service()).model_dump()
    path.write_text(json.dumps([other]))
    write_catalog(path, "test")
    write_catalog(path, "test")
    catalog = json.loads(path.read_text())
    assert len(catalog) == 2 and catalog[0] == other
    assert len(catalog[1]["queries"]) == 3


@pytest.mark.parametrize("encoding", ["identity", "gzip", "deflate"])
async def test_discover_execute_replay_and_saved_receipt_in_postgres(store, monkeypatch, encoding):
    monkeypatch.setenv("DATAFORSEO_AUTH", SECRET)
    settings = ProductSettings(_env_file=None)
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("dataforseo-test")["account_id"]
    credit(store, owner)
    principal, credential = grant(store, owner)
    calls = []

    def handler(request):
        calls.append(request)
        endpoint = next(
            q.endpoint_id
            for q in Provider.model_validate(provider()).queries
            if q.url == str(request.url)
        )
        assert request.headers["authorization"] == "Basic " + SECRET
        assert isinstance(json.loads(request.content), list)
        body = json.dumps(envelope(endpoint)).encode()
        if encoding == "gzip":
            body = gzip.compress(body)
        elif encoding == "deflate":
            body = zlib.compress(body)
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "Content-Encoding": encoding,
                "Content-Length": str(len(body)),
            },
            stream=httpx.ByteStream(body),
        )

    caller = ApiKeyCaller(settings, store, transport=httpx.MockTransport(handler))
    worker = Worker(settings, store, Mock(), api_caller=caller)
    app = create_app(settings, store=store, verifier=Closable(), stripe=Closable())
    machine = {"Authorization": "Bearer " + credential["secret"]}
    try:
        await worker.tick()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api.example"
        ) as client:
            response = await client.post(
                "/v1/discover", headers=machine, json={"query": "Google keyword research"}
            )
            assert response.status_code == 200
            discovered = response.json()["providers"]
            assert len(discovered) == 1 and discovered[0]["provider_id"] == "dataforseo"
            assert {q["endpoint_id"] for q in discovered[0]["queries"]} == set(PAYLOADS)
            assert SECRET not in response.text and "secret_ref" not in response.text
            assert "provider_price_cents" not in response.text
            for endpoint_id, payload in PAYLOADS.items():
                service = service_for(endpoint_id)
                purchase = {
                    "endpoint_id": endpoint_id,
                    "payload": payload,
                    "max_price_cents": service.price_cents,
                }
                headers = machine | {"Idempotency-Key": endpoint_id}
                first = await client.post("/v1/execute", headers=headers, json=purchase)
                assert first.status_code == 202
                await worker.tick()
                replay = await client.post("/v1/execute", headers=headers, json=purchase)
                assert replay.status_code == 200 and replay.json()["status"] == "completed"
                assert replay.json()["data"]["is_demo_data"] is True
                row = store.execution_internal(first.json()["execution_id"])
                assert row["provider_cost_microusd"] == 0
                assert (
                    row["data"]["items"] and row["provider_receipt"]["task_id"] == "vendor-task-1"
                )
                assert SECRET not in json.dumps(row, default=str)
            await worker.tick()
            assert len(calls) == 3
            assert store.account(principal.account_id)["spent_cents"] == 12
    finally:
        await caller.close()


async def test_compressed_response_limit_applies_to_decoded_body():
    body = gzip.compress(b"x" * 1_000_001)

    def handler(request):
        return httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(body)
        )

    caller = ApiKeyCaller(
        ProductSettings(_env_file=None), Mock(), transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(TerminalFailure, match="exceeded the maximum size"):
            await caller._post(service_for(SEARCH), "[]", {})
    finally:
        await caller.close()


@pytest.mark.parametrize(
    "response,status,expected",
    [
        (envelope(cost=0, status=40501), 200, "refunded"),
        ({"status_code": 40104, "cost": 0, "tasks": None}, 403, "refunded"),
        (envelope(status=40501), 200, "needs_review"),
        (envelope(status=20100), 200, "needs_review"),
    ],
)
async def test_rejection_refunds_only_proven_zero_cost_and_never_retries(
    store, monkeypatch, response, status, expected
):
    monkeypatch.setenv("DATAFORSEO_AUTH", SECRET)
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("failure-test")["account_id"]
    credit(store, owner)
    principal, _ = grant(store, owner)
    service = service_for(SEARCH)
    row = store.reserve(
        principal,
        "buy",
        {"endpoint_id": SEARCH, "payload": PAYLOADS[SEARCH], "max_price_cents": 2},
        service,
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=response)

    caller = ApiKeyCaller(
        ProductSettings(_env_file=None), store, transport=httpx.MockTransport(handler)
    )
    worker = Worker(ProductSettings(_env_file=None), store, Mock(), api_caller=caller)
    try:
        await worker.tick()
        outcome = store.execution_internal(row["execution_id"])
        assert outcome["status"] == expected
        await worker.execution(outcome, None)
        assert len(calls) == 1
        account = store.account(owner)
        assert account["spent_cents"] == 0
        assert account["reserved_cents"] == (2 if expected == "needs_review" else 0)
    finally:
        await caller.close()


async def test_crash_after_receipt_recovers_saved_result_without_resubmission(store):
    store.sync_catalog([Provider.model_validate(provider("live"))])
    service = service_for(OVERVIEW, "live")
    owner = store.bootstrap("recovery-test")["account_id"]
    credit(store, owner)
    principal, _ = grant(store, owner)
    row = store.reserve(
        principal,
        "buy",
        {"endpoint_id": OVERVIEW, "payload": PAYLOADS[OVERVIEW], "max_price_cents": 5},
        service,
    )
    data, receipt, cost = parse(
        OVERVIEW, "live", PAYLOADS[OVERVIEW], envelope(OVERVIEW, cost=0.01212)
    )
    store.mark_sent(row["execution_id"])
    store.mark_paid(row["execution_id"], receipt, data=data, cost_microusd=cost)
    caller = Mock()
    worker = Worker(ProductSettings(_env_file=None), store, Mock(), api_caller=caller)
    await worker.execution(store.execution_internal(row["execution_id"]), None)
    done = store.execution_internal(row["execution_id"])
    assert done["status"] == "completed" and done["data"] == data
    assert done["provider_cost_microusd"] == 12120
    assert done["provider_cost_cents"] == 2
    assert done["charged_cents"] == 5
    caller.purchase.assert_not_called()


def test_additive_migration_preserves_old_contract_and_detects_missing_columns(store):
    with store.connection() as connection:
        assert connection.execute("SELECT version FROM schema_version").fetchone()["version"] == 1
    store.database.check_schema_version()
    with store.connection() as connection:
        connection.execute("ALTER TABLE queries DROP COLUMN adapter")
    with pytest.raises(RuntimeError, match="run account migrate"):
        store.database.check_schema_version()
