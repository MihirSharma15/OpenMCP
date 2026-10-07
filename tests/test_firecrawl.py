"""Firecrawl protocol and account purchase flow; all vendor calls are mocked."""

import json
from unittest.mock import Mock

import httpx
import pytest

from openmcp.integrations.firecrawl.catalog import (
    HTML,
    MAP,
    ORIGIN,
    SCRAPE,
    SEARCH,
    SERVICES,
    provider,
)
from openmcp.integrations.firecrawl.cli import write_catalog
from openmcp.integrations.firecrawl.protocol import credit_rate, parse, prepare
from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings, Provider
from openmcp.product.settlement import TerminalFailure
from openmcp.product.worker import Worker
from tests import test_product_api_call as api_tests

postgres_url = api_tests.postgres_url
store = api_tests.store
SECRET = "fc-private-test-key"


def service(endpoint_id):
    return next(
        q for q in Provider.model_validate(provider()).queries if q.endpoint_id == endpoint_id
    )


def sample(endpoint_id):
    payload = {"url": "https://example.com"}
    if endpoint_id == SEARCH:
        return {"query": "renewable energy", "limit": 2}, {
            "success": True,
            "id": "search-1",
            "creditsUsed": 2,
            "data": {
                "web": [{"url": "https://example.com", "title": "Energy", "description": "Source"}]
            },
        }
    if endpoint_id == MAP:
        return payload | {"limit": 2}, {
            "success": True,
            "links": [
                {"url": "https://example.com/a", "title": "A"},
                {"url": "https://example.com/b", "description": "B"},
            ],
        }
    field = "html" if endpoint_id == HTML else "markdown"
    return payload, {
        "success": True,
        "data": {
            field: "<p>Page</p>" if field == "html" else "# Page",
            "metadata": {
                "statusCode": 200,
                "title": "Page",
                "sourceURL": payload["url"],
                "scrapeId": "scrape-1",
            },
        },
    }


@pytest.mark.parametrize("endpoint_id", SERVICES)
def test_prepares_fixed_bounded_requests(endpoint_id):
    selected = service(endpoint_id)
    payload, _ = sample(endpoint_id)
    body, auth = prepare(endpoint_id, selected.url, "test", payload, SECRET)
    assert auth == "Bearer " + SECRET and body["timeout"] == 20000
    if endpoint_id in (SCRAPE, HTML):
        assert body["formats"] == ["markdown" if endpoint_id == SCRAPE else "html"]
        assert body["parsers"] == [] and body["proxy"] == "basic"
        assert body["skipTlsVerification"] is False
        assert body["onlyMainContent"] is True and "actions" not in body
    elif endpoint_id == SEARCH:
        assert body["sources"] == ["web"] and "scrapeOptions" not in body
        assert "enterprise" not in body and body["limit"] == 2
    else:
        assert body["includeSubdomains"] is False


@pytest.mark.parametrize(
    "endpoint_id,payload",
    [
        (SCRAPE, {"url": "https://example.com/document.pdf"}),
        (SCRAPE, {"url": "https://example.com/document%2epdf"}),
        (SCRAPE, {"url": "https://127.0.0.1"}),
        (HTML, {"url": "https://10.0.0.1"}),
        (SCRAPE, {"url": "https://localhost"}),
        (SCRAPE, {"url": "http://example.com"}),
        (SCRAPE, {"url": "https://u:p@example.com"}),
        (SCRAPE, {"url": "https://example.com", "parsers": ["pdf"]}),
        (HTML, {"url": "https://example.com", "formats": ["json"]}),
        (SCRAPE, {"url": "https://example.com", "actions": [{"type": "click"}]}),
        (SCRAPE, {"url": "https://example.com", "headers": {"Cookie": "secret"}}),
        (SEARCH, {"query": " "}),
        (SEARCH, {"query": "x" * 501}),
        (SEARCH, {"query": "x", "limit": 11}),
        (SEARCH, {"query": "x", "limit": True}),
        (SEARCH, {"query": "x", "scrapeOptions": {"formats": ["markdown"]}}),
        (MAP, {"url": "https://example.com", "limit": 11}),
    ],
)
def test_invalid_or_unpriced_inputs_are_rejected_before_sending(endpoint_id, payload):
    with pytest.raises(ValueError):
        prepare(endpoint_id, service(endpoint_id).url, "test", payload, SECRET)


@pytest.mark.parametrize("value", [None, "NaN", "-1", "0.005", "1000001", "١"])
def test_credit_rate_must_be_explicit_nonnegative_integer(value):
    with pytest.raises(ValueError):
        credit_rate(value)


def test_news_recency_filter_and_no_extra_sources():
    body, _ = prepare(
        SEARCH,
        service(SEARCH).url,
        "live",
        {
            "query": "energy",
            "source": "news",
            "time_range": "week",
            "country": "GB",
        },
        SECRET,
    )
    assert body["sources"] == ["news"] and body["tbs"] == "qdr:w" and body["country"] == "GB"
    _, response = sample(SEARCH)
    response["data"] = {"news": response["data"]["web"]}
    assert parse(SEARCH, {"query": "energy", "source": "news"}, response, 0)[0]["source"] == "news"


@pytest.mark.parametrize("endpoint_id", SERVICES)
@pytest.mark.parametrize("rate", [0, 5000])
def test_normalization_and_cost_basis_are_honest(endpoint_id, rate):
    payload, body = sample(endpoint_id)
    data, receipt, cost = parse(endpoint_id, payload, body, rate)
    assert data["endpoint_id"] == endpoint_id
    expected = 2 if endpoint_id == SEARCH else 1
    assert cost == expected * rate and receipt["credits_accounted"] == expected
    assert receipt["cash_cost_basis"] == "configured_credit_rate"
    if endpoint_id == SEARCH:
        assert receipt["credits_consumed"] == 2 and receipt["vendor_reference"] == "search-1"
    else:
        assert "credits_consumed" not in receipt  # Do not invent reported vendor usage.
        assert "estimate" in receipt["credit_count_basis"]


@pytest.mark.parametrize("count", [0, 1, 10])
def test_map_cost_is_per_call_not_per_link(count):
    payload = {"url": "https://example.com", "limit": 10}
    body = {"success": True, "links": [{"url": f"https://example.com/{i}"} for i in range(count)]}
    _, receipt, cost = parse(MAP, payload, body, 5000)
    assert cost == 5000 and receipt["credits_accounted"] == 1
    assert receipt["credit_count_basis"] == "documented_per_call_estimate"
    body["creditsUsed"] = 2
    with pytest.raises(ValueError):
        parse(MAP, payload, body, 5000)


@pytest.mark.parametrize("endpoint_id", [SCRAPE, HTML])
@pytest.mark.parametrize("issue", ["target404", "empty", "missing_status", "multipage", "false"])
def test_unusable_scrapes_are_not_paid_or_automatically_refunded(endpoint_id, issue):
    payload, body = sample(endpoint_id)
    if issue == "target404":
        body["data"]["metadata"]["statusCode"] = 404
    elif issue == "empty":
        body["data"][SERVICES[endpoint_id]["format"]] = " "
    elif issue == "missing_status":
        body["data"]["metadata"].pop("statusCode")
    elif issue == "multipage":
        body["data"]["metadata"]["numPages"] = 10
    else:
        body["success"] = False
    with pytest.raises(ValueError):
        parse(endpoint_id, payload, body, 0)


@pytest.mark.parametrize("reported", [None, -1, True, 3, "2"])
def test_search_requires_bounded_reported_cost(reported):
    payload, body = sample(SEARCH)
    body["creditsUsed"] = reported
    with pytest.raises(ValueError):
        parse(SEARCH, payload, body, 0)


def test_all_services_enabled_and_urls_auth_prices_are_private():
    definition = Provider.model_validate(provider())
    assert [q.endpoint_id for q in definition.queries if q.enabled] == [SCRAPE, HTML, SEARCH, MAP]
    for selected in definition.queries:
        public = selected.public()
        assert selected.url not in json.dumps(public) and "secret_ref" not in public
        assert "platform_fee_cents" not in public
    bad = provider()
    bad["queries"][0]["url"] = ORIGIN + "/crawl"
    with pytest.raises(ValueError):
        Provider.model_validate(bad)
    bad["queries"][0].update(url=ORIGIN + "/scrape", settlement="mpp")
    with pytest.raises(ValueError):
        Provider.model_validate(bad)


def test_catalog_merges_without_deleting_tavily(tmp_path):
    from openmcp.integrations.tavily.catalog import provider as tavily

    path = tmp_path / "all.json"
    path.write_text(json.dumps([tavily()]))
    write_catalog(path, "test")
    write_catalog(path, "test")
    entries = json.loads(path.read_text())
    assert [p["provider_id"] for p in entries] == ["tavily", "firecrawl"]
    assert SECRET not in path.read_text()


@pytest.mark.parametrize("endpoint_id", [SCRAPE, HTML, SEARCH, MAP])
@pytest.mark.parametrize("rate", [0, 5000])
async def test_discover_reserve_capture_replay_and_crash_recovery(
    store, monkeypatch, endpoint_id, rate
):
    monkeypatch.setenv("FIRECRAWL_API_KEY", SECRET)
    monkeypatch.setenv("FIRECRAWL_CREDIT_COST_MICROUSD", str(rate))
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("firecrawl-owner")["account_id"]
    api_tests.credit(store, owner)
    principal, credential = api_tests.grant(store, owner)
    payload, body = sample(endpoint_id)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer " + SECRET
        assert str(request.url) == service(endpoint_id).url
        return httpx.Response(200, json=body)

    settings = ProductSettings(_env_file=None)
    caller = ApiKeyCaller(settings, store, transport=httpx.MockTransport(handler))
    worker = Worker(settings, store, Mock(), api_caller=caller)
    app = create_app(
        settings, store=store, verifier=api_tests.Closable(), stripe=api_tests.Closable()
    )
    auth = {"Authorization": "Bearer " + credential["secret"]}
    request = {"endpoint_id": endpoint_id, "payload": payload, "max_price_cents": 2}
    try:
        await worker.tick()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api.test"
        ) as client:
            discovery = await client.post("/v1/discover", headers=auth, json={"query": "Firecrawl"})
            assert discovery.status_code == 200 and endpoint_id in discovery.text
            assert MAP in discovery.text and "secret_ref" not in discovery.text
            assert ORIGIN not in discovery.text
            headers = auth | {"Idempotency-Key": "buy-once"}
            first = await client.post("/v1/execute", headers=headers, json=request)
            assert first.status_code == 202 and store.account(owner)["reserved_cents"] == 2
            await worker.tick()
            replay = await client.post("/v1/execute", headers=headers, json=request)
            assert replay.status_code == 200 and replay.json()["status"] == "completed"
            row = store.execution_internal(first.json()["execution_id"])
            assert row["provider_cost_microusd"] == (2 if endpoint_id == SEARCH else 1) * rate
            assert SECRET not in json.dumps(row, default=str)
            assert store.account(owner)["spent_cents"] == 2
            assert store.account(owner)["reserved_cents"] == 0
            await worker.tick()
            assert len(calls) == 1
            pending = store.reserve(principal, "crash", request, service(endpoint_id))
            data, receipt, cost = parse(endpoint_id, payload, body, rate)
            store.mark_sent(pending["execution_id"])
            store.mark_paid(pending["execution_id"], receipt, data=data, cost_microusd=cost)
            await worker.tick()
            assert store.execution_internal(pending["execution_id"])["status"] == "completed"
            assert len(calls) == 1 and store.account(owner)["spent_cents"] == 4
    finally:
        await caller.close()


@pytest.mark.parametrize("issue", ["false", "target404", "http429", "timeout"])
async def test_failed_sent_call_holds_for_review_without_retry(store, monkeypatch, issue):
    monkeypatch.setenv("FIRECRAWL_API_KEY", SECRET)
    monkeypatch.setenv("FIRECRAWL_CREDIT_COST_MICROUSD", "0")
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("failed-owner")["account_id"]
    api_tests.credit(store, owner)
    principal, _ = api_tests.grant(store, owner)
    payload, body = sample(SCRAPE)
    calls = []

    def handler(request):
        calls.append(request)
        if issue == "timeout":
            raise httpx.TimeoutException("timeout")
        if issue == "http429":
            return httpx.Response(429, json={"success": False})
        if issue == "false":
            body["success"] = False
        if issue == "target404":
            body["data"]["metadata"]["statusCode"] = 404
        return httpx.Response(200, json=body)

    settings = ProductSettings(_env_file=None)
    caller = ApiKeyCaller(settings, store, transport=httpx.MockTransport(handler))
    worker = Worker(settings, store, Mock(), api_caller=caller)
    request = {"endpoint_id": SCRAPE, "payload": payload, "max_price_cents": 2}
    row = store.reserve(principal, "failed", request, service(SCRAPE))
    try:
        await worker.tick()
        current = store.execution_internal(row["execution_id"])
        assert current["status"] == "needs_review" and current["payment_status"] == "sent"
        assert store.account(owner)["reserved_cents"] == 2
        store.requeue(row["execution_id"])
        await worker.tick()
        assert len(calls) == 1 and store.account(owner)["spent_cents"] == 0
    finally:
        await caller.close()


async def test_invalid_rate_does_not_send_or_journal(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", SECRET)
    monkeypatch.setenv("FIRECRAWL_CREDIT_COST_MICROUSD", "bad")
    fake = Mock()
    fake.provider_secret_ref.return_value = "FIRECRAWL_API_KEY"
    caller = ApiKeyCaller(
        ProductSettings(_env_file=None),
        fake,
        transport=httpx.MockTransport(lambda r: pytest.fail("Must not send")),
    )
    try:
        with pytest.raises(TerminalFailure):
            await caller.purchase(
                {
                    "execution_id": "invalid-rate",
                    "payment_status": "unsigned",
                    "payload": {"url": "https://example.com"},
                    "service": service(SCRAPE).model_dump(),
                }
            )
        fake.mark_sent.assert_not_called()
    finally:
        await caller.close()


def test_reapplying_migrations_preserves_new_adapters_and_pending_purchases(store):
    from openmcp.integrations.tavily.catalog import provider as tavily

    store.sync_catalog([Provider.model_validate(tavily()), Provider.model_validate(provider())])
    owner = store.bootstrap("migration-owner")["account_id"]
    api_tests.credit(store, owner)
    principal, _ = api_tests.grant(store, owner)
    payload, _ = sample(SCRAPE)
    row = store.reserve(
        principal,
        "pending",
        {
            "endpoint_id": SCRAPE,
            "payload": payload,
            "max_price_cents": 2,
        },
        service(SCRAPE),
    )
    for _ in range(2):
        store.migrate()
        assert store.catalog_service(SCRAPE).adapter == "firecrawl"
        assert store.catalog_service("tavily-web-search").adapter == "tavily"
        assert store.account(owner)["reserved_cents"] == 2
        assert store.execution_internal(row["execution_id"])["service"] == row["service"]
