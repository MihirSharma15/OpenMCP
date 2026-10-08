"""No real Tavily calls: bounded protocol and durable account lifecycle."""

import json
from unittest.mock import Mock

import httpx
import pytest

from openmcp.integrations.tavily.catalog import (
    ADVANCED,
    EXTRACT,
    EXTRACT_ADVANCED,
    MAP,
    SEARCH,
    SERVICES,
    URL,
    provider,
)
from openmcp.integrations.tavily.cli import write_catalog
from openmcp.integrations.tavily.protocol import credit_rate, parse, prepare
from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings, Provider
from openmcp.product.settlement import TerminalFailure
from openmcp.product.worker import Worker
from tests import test_product_api_call as api_tests

postgres_url = api_tests.postgres_url
store = api_tests.store
SECRET = "tvly-private-test-key"
PAYLOAD = {"query": "renewable energy", "max_results": 1}


def envelope():
    return {
        "request_id": "vendor-search-1",
        "usage": {"credits": 1},
        "results": [{"title": "Energy", "url": "https://example.com", "content": "Source excerpt"}],
    }


def service(endpoint_id=SEARCH):
    return next(
        q for q in Provider.model_validate(provider()).queries if q.endpoint_id == endpoint_id
    )


def test_fixed_basic_request_and_secret_free_public_catalog():
    body, auth = prepare(SEARCH, URL, "test", PAYLOAD, SECRET)
    assert auth == "Bearer " + SECRET
    assert body["search_depth"] == "basic" and body["auto_parameters"] is False
    assert body["include_usage"] is True and body["include_raw_content"] is False
    assert body["include_answer"] is False and body["max_results"] == 1
    public = service().public()
    assert public["price_cents"] == 2 and "platform_fee_cents" not in public
    assert "url" not in public and SECRET not in json.dumps(public)


@pytest.mark.parametrize(
    "payload",
    [
        {"query": " "},
        {"query": "x" * 401},
        {"query": "x", "max_results": 21},
        {"query": "x", "max_results": True},
        {"query": "x", "search_depth": "advanced"},
        {"query": "x", "auto_parameters": True},
        {"query": "x", "url": "https://evil.example"},
    ],
)
def test_paid_options_and_invalid_inputs_rejected(payload):
    with pytest.raises(ValueError):
        prepare(SEARCH, URL, "live", payload, SECRET)


def test_target_and_settlement_locked():
    for updates in [
        {"url": "https://evil.example/search"},
        {"endpoint_id": "other"},
        {"settlement": "mpp"},
    ]:
        config = provider()
        config["queries"][0].update(updates)
        with pytest.raises(ValueError):
            Provider.model_validate(config)


@pytest.mark.parametrize("value", ["-1", "NaN", "0.008", "1000001", "١", " ", None])
def test_invalid_configured_rates(value):
    with pytest.raises(ValueError):
        credit_rate(value)


def test_free_and_paid_cash_cost_are_separate_from_credits():
    for rate in (0, 8000):
        data, receipt, cost = parse(PAYLOAD, envelope(), credit_rate(str(rate)))
        assert data["results"][0]["title"] == "Energy"
        assert cost == rate and receipt["credits_consumed"] == 1
        assert receipt["cost_basis"] == "configured_credit_rate"
    empty = envelope() | {"results": []}
    assert parse(PAYLOAD, empty, 0)[0]["results"] == []


@pytest.mark.parametrize(
    "updates",
    [
        {"usage": {}},
        {"usage": {"credits": 2}},
        {"usage": {"credits": True}},
        {"request_id": ""},
        {"results": [{}]},
        {"results": [None]},
        {"results": envelope()["results"] * 2},
        {"error": "failed"},
    ],
)
def test_ambiguous_or_malformed_result_not_captured(updates):
    with pytest.raises(ValueError):
        parse(PAYLOAD, envelope() | updates, 0)


def test_catalog_merge_preserves_other_providers(tmp_path):
    from openmcp.integrations.dataforseo.catalog import provider as dfs_provider

    path = tmp_path / "approved.json"
    path.write_text(json.dumps([dfs_provider()]))
    write_catalog(path, "test")
    write_catalog(path, "test")
    entries = json.loads(path.read_text())
    assert [p["provider_id"] for p in entries] == ["dataforseo", "tavily"]
    assert SECRET not in path.read_text()


@pytest.mark.parametrize(
    "status,body",
    [(200, envelope() | {"usage": {"credits": 2}}), (429, {"detail": "quota exceeded"})],
)
async def test_sent_failure_never_retries_or_infers_refund(monkeypatch, status, body):
    monkeypatch.setenv("TAVILY_API_KEY", SECRET)
    monkeypatch.setenv("TAVILY_CREDIT_COST_MICROUSD", "0")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    fake = Mock()
    fake.provider_secret_ref.return_value = "TAVILY_API_KEY"
    caller = ApiKeyCaller(
        ProductSettings(_env_file=None), fake, transport=httpx.MockTransport(handler)
    )
    row = {
        "execution_id": "exe_test",
        "payment_status": "unsigned",
        "service": service().model_dump(),
        "payload": PAYLOAD,
    }
    try:
        with pytest.raises(TerminalFailure):
            await caller.purchase(row)
        with pytest.raises(TerminalFailure, match="already sent"):
            await caller.purchase(row | {"payment_status": "sent"})
        assert len(calls) == 1
        fake.mark_paid.assert_not_called()
        fake.finish.assert_not_called()
    finally:
        await caller.close()


@pytest.mark.parametrize("rate", [0, 8000])
@pytest.mark.parametrize("endpoint_id", list(SERVICES))
async def test_discover_execute_capture_replay_and_crash_recovery(
    store, monkeypatch, rate, endpoint_id
):
    monkeypatch.setenv("TAVILY_API_KEY", SECRET)
    monkeypatch.setenv("TAVILY_CREDIT_COST_MICROUSD", str(rate))
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("tavily-subject")["account_id"]
    api_tests.credit(store, owner)
    principal, credential = api_tests.grant(store, owner)
    settings = ProductSettings(_env_file=None)
    calls = []
    payload, response_body = sample(endpoint_id)
    selected = service(endpoint_id)
    reported_cost = response_body["usage"]["credits"] * rate

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer " + SECRET
        assert json.loads(request.content)["include_usage"] is True
        assert str(request.url) == selected.url
        return httpx.Response(200, json=response_body)

    caller = ApiKeyCaller(settings, store, transport=httpx.MockTransport(handler))
    worker = Worker(settings, store, Mock(), api_caller=caller)
    app = create_app(
        settings, store=store, verifier=api_tests.Closable(), stripe=api_tests.Closable()
    )
    auth = {"Authorization": "Bearer " + credential["secret"]}
    purchase = {
        "endpoint_id": endpoint_id,
        "payload": payload,
        "max_price_cents": selected.price_cents,
    }
    try:
        await worker.tick()  # Publish the worker heartbeat required by execute.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api.example"
        ) as client:
            discovered = await client.post(
                "/v1/discover", headers=auth, json={"query": "web search"}
            )
            assert discovered.status_code == 200 and SEARCH in discovered.text
            assert "secret_ref" not in discovered.text and URL not in discovered.text
            headers = auth | {"Idempotency-Key": "tavily-once"}
            first = await client.post("/v1/execute", headers=headers, json=purchase)
            assert first.status_code == 202
            assert store.account(owner)["reserved_cents"] == selected.price_cents
            await worker.tick()
            replay = await client.post("/v1/execute", headers=headers, json=purchase)
            assert replay.status_code == 200 and replay.json()["status"] == "completed"
            row = store.execution_internal(first.json()["execution_id"])
            assert row["provider_cost_microusd"] == reported_cost
            assert row["provider_receipt"]["credits_consumed"] == response_body["usage"]["credits"]
            assert SECRET not in json.dumps(row, default=str)
            assert store.account(owner)["spent_cents"] == selected.price_cents
            assert store.account(owner)["reserved_cents"] == 0
            await worker.tick()
            assert len(calls) == 1
            # Simulate a crash after mark_paid but before finish.
            pending = store.reserve(principal, "crash", purchase, selected)
            store.mark_sent(pending["execution_id"])
            data, receipt, cost = parse(payload, response_body, rate, endpoint_id)
            store.mark_paid(pending["execution_id"], receipt, data=data, cost_microusd=cost)
            await worker.tick()
            assert store.execution_internal(pending["execution_id"])["status"] == "completed"
            assert (
                len(calls) == 1 and store.account(owner)["spent_cents"] == 2 * selected.price_cents
            )
    finally:
        await caller.close()


def test_database_registration_preserves_catalog_and_rejects_collision(store):
    from openmcp.integrations.dataforseo.catalog import provider as dfs_provider

    store.sync_catalog([Provider.model_validate(dfs_provider())])
    store.sync_catalog([Provider.model_validate(provider())], prune=False)
    assert store.service_count("test") == 8
    store.sync_catalog([Provider.model_validate(provider())], prune=False)
    assert store.service_count("test") == 8
    conflicting = provider()
    conflicting["provider_id"] = "other"
    with pytest.raises(ValueError, match="owns"):
        store.sync_catalog([Provider.model_validate(conflicting)], prune=False)
    assert store.service_count("test") == 8


def sample(endpoint_id):
    if endpoint_id in (SEARCH, ADVANCED):
        return PAYLOAD, envelope() | {"usage": {"credits": 2 if endpoint_id == ADVANCED else 1}}
    if endpoint_id in (EXTRACT, EXTRACT_ADVANCED):
        return {"urls": ["https://example.com"]}, {
            "results": [{"url": "https://example.com", "raw_content": "Page text"}],
            "failed_results": [],
            "usage": {"credits": 0},
            "request_id": "extract-1",
        }
    return {"url": "https://example.com", "limit": 20}, {
        "results": ["https://example.com/page"],
        "usage": {"credits": 1},
        "request_id": "map-1",
    }


@pytest.mark.parametrize("endpoint_id", list(SERVICES))
def test_service_specific_request_and_usage(endpoint_id):
    payload, response = sample(endpoint_id)
    selected = service(endpoint_id)
    body, _ = prepare(endpoint_id, selected.url, "test", payload, SECRET)
    assert body["include_usage"] is True
    if endpoint_id in (SEARCH, ADVANCED):
        assert body["search_depth"] == ("basic" if endpoint_id == SEARCH else "advanced")
        body20, _ = prepare(
            endpoint_id,
            selected.url,
            "live",
            {
                "query": "x",
                "max_results": 20,
                "topic": "news",
                "time_range": "week",
                "include_domains": ["example.com"],
            },
            SECRET,
        )
        assert body20["max_results"] == 20 and body20["topic"] == "news"
    elif endpoint_id in (EXTRACT, EXTRACT_ADVANCED):
        assert body["extract_depth"] == ("basic" if endpoint_id == EXTRACT else "advanced")
        assert body["timeout"] == 10
    else:
        assert body["max_depth"] == 1 and body["allow_external"] is False
        assert "instructions" not in body and body["timeout"] == 20
    data, receipt, cost = parse(payload, response, 8000, endpoint_id)
    assert data["endpoint_id"] == endpoint_id
    assert cost == receipt["credits_consumed"] * 8000


@pytest.mark.parametrize(
    "endpoint_id,payload",
    [
        (EXTRACT, {"urls": ["https://127.0.0.1"]}),
        (EXTRACT, {"urls": ["https://169.254.169.254"]}),
        (EXTRACT, {"urls": ["https://localhost"]}),
        (EXTRACT, {"urls": ["https://user:pass@example.com"]}),
        (EXTRACT, {"urls": ["https://example.com"] * 6}),
        (EXTRACT, {"urls": ["https://example.com"], "extract_depth": "advanced"}),
        (MAP, {"url": "https://10.0.0.1"}),
        (MAP, {"url": "https://example.com", "limit": 51}),
        (MAP, {"url": "https://example.com", "instructions": "research everything"}),
        (MAP, {"url": "https://example.com", "max_depth": 10}),
    ],
)
def test_unsafe_urls_and_unpriced_options_rejected(endpoint_id, payload):
    with pytest.raises(ValueError):
        prepare(endpoint_id, service(endpoint_id).url, "test", payload, SECRET)


def test_partial_extraction_and_explicit_zero_usage_failure():
    from openmcp.integrations.tavily.protocol import Rejected

    payload = {"urls": ["https://example.com", "https://example.com/missing"]}
    _, response = sample(EXTRACT)
    response["failed_results"] = [{"url": payload["urls"][1], "error": "not found"}]
    data, _, _ = parse(payload, response, 8000, EXTRACT)
    assert data["partial_success"] is True and len(data["results"]) == 1
    response["results"] = []
    response["failed_results"].append({"url": payload["urls"][0], "error": "not found"})
    with pytest.raises(Rejected):
        parse(payload, response, 8000, EXTRACT)
    response["usage"]["credits"] = 1
    with pytest.raises(ValueError) as exc:
        parse(payload, response, 8000, EXTRACT)
    assert not isinstance(exc.value, Rejected)


async def test_extraction_all_failed_refunds(store, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", SECRET)
    monkeypatch.setenv("TAVILY_CREDIT_COST_MICROUSD", "0")
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("extract-subject")["account_id"]
    api_tests.credit(store, owner)
    principal, _ = api_tests.grant(store, owner)
    payload, body = sample(EXTRACT)
    body["results"] = []
    body["failed_results"] = [{"url": payload["urls"][0], "error": "unavailable"}]
    caller = ApiKeyCaller(
        ProductSettings(_env_file=None),
        store,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    )
    worker = Worker(ProductSettings(_env_file=None), store, Mock(), api_caller=caller)
    selected = service(EXTRACT)
    try:
        row = store.reserve(
            principal,
            "failed",
            {"endpoint_id": EXTRACT, "payload": payload, "max_price_cents": 2},
            selected,
        )
        await worker.tick()
        assert store.execution_internal(row["execution_id"])["status"] == "refunded"
        assert store.account(owner)["spent_cents"] == 0
        assert store.account(owner)["reserved_cents"] == 0
    finally:
        await caller.close()


@pytest.mark.parametrize("endpoint_id,credits", [(EXTRACT, 1), (EXTRACT_ADVANCED, 2), (MAP, 2)])
def test_reported_paid_usage_and_excess_credit_rejection(endpoint_id, credits):
    payload, body = sample(endpoint_id)
    body["usage"]["credits"] = credits
    _, receipt, cost = parse(payload, body, 8000, endpoint_id)
    assert cost == credits * 8000 and receipt["credits_consumed"] == credits
    body["usage"]["credits"] = credits + 1
    with pytest.raises(ValueError):
        parse(payload, body, 8000, endpoint_id)


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown", "empty_content"])
def test_extraction_malformed_coverage_never_refunds(change):
    from openmcp.integrations.tavily.protocol import Rejected

    payload, body = sample(EXTRACT)
    if change == "missing":
        body["results"] = []
    elif change == "duplicate":
        body["results"] *= 2
    elif change == "unknown":
        body["results"][0]["url"] = "https://other.example"
    else:
        body["results"][0]["raw_content"] = " "
    with pytest.raises(ValueError) as exc:
        parse(payload, body, 0, EXTRACT)
    assert not isinstance(exc.value, Rejected)
