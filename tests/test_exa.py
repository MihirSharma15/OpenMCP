"""Exa protocol and full local purchase tests; vendor requests are mocked."""

import json
from unittest.mock import Mock

import httpx
import pytest

from openmcp.integrations.exa.catalog import CONTENTS, ORIGIN, SEARCH, SERVICES, provider
from openmcp.integrations.exa.cli import write_catalog
from openmcp.integrations.exa.protocol import parse, prepare
from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings, Provider
from openmcp.product.worker import Worker
from tests import test_product_api_call as api_tests

postgres_url = api_tests.postgres_url
store = api_tests.store
SECRET = "exa-private-test-key"


def service(identifier):
    return next(
        q for q in Provider.model_validate(provider()).queries if q.endpoint_id == identifier
    )


def sample(identifier):
    payload = (
        {"query": "renewable energy", "limit": 2}
        if identifier == SEARCH
        else {"url": "https://example.com", "max_characters": 1000}
    )
    body = {
        "requestId": "vendor-1",
        "costDollars": {"total": 0.007 if identifier == SEARCH else 0.001},
        "results": [{"url": "https://example.com", "title": "Example", "text": "Page content"}],
    }
    if identifier == CONTENTS:
        body["statuses"] = [{"id": "https://example.com", "status": "success"}]
    return payload, body


@pytest.mark.parametrize("identifier", SERVICES)
def test_fixed_routes_auth_limits_and_estimated_cost(identifier):
    payload, response = sample(identifier)
    selected = service(identifier)
    body, key = prepare(identifier, selected.url, "live", payload, SECRET)
    assert key == SECRET
    if identifier == SEARCH:
        assert body == {"query": payload["query"], "numResults": 2, "type": "auto"}
    else:
        assert body["ids"] == [payload["url"]] and body["subpages"] == 0
        assert body["text"] == {"maxCharacters": 1000}
        assert body["highlights"] is False and body["summary"] is False
    data, receipt, cost = parse(identifier, payload, response)
    assert cost == SERVICES[identifier]["max_cost_microusd"]
    assert receipt["cost_basis"] == "vendor_reported_estimate"
    assert data["provider"] == "Exa" and SECRET not in json.dumps(data)
    assert "secret_ref" not in selected.public() and ORIGIN not in json.dumps(selected.public())


@pytest.mark.parametrize(
    "identifier,payload",
    [
        (SEARCH, {"query": " "}),
        (SEARCH, {"query": "q", "limit": 11}),
        (SEARCH, {"query": "q", "type": "deep"}),
        (CONTENTS, {"url": "https://127.0.0.1"}),
        (CONTENTS, {"url": "https://example.com", "subpages": 10}),
        (CONTENTS, {"url": "https://example.com", "max_characters": 20001}),
    ],
)
def test_invalid_inputs_do_not_send(identifier, payload):
    with pytest.raises(ValueError):
        prepare(identifier, service(identifier).url, "test", payload, SECRET)


@pytest.mark.parametrize(
    "total", [None, -1, True, "0.007", float("nan"), float("inf"), 0.0000001, 0.008]
)
def test_missing_or_unbounded_estimates_require_review(total):
    payload, body = sample(SEARCH)
    body["costDollars"]["total"] = total
    with pytest.raises(ValueError):
        parse(SEARCH, payload, body)


@pytest.mark.parametrize("issue", ["status", "empty", "too_long", "no_id", "error", "too_many"])
def test_unusable_content_is_not_captured(issue):
    payload, body = sample(CONTENTS)
    if issue == "status":
        body["statuses"][0]["status"] = "error"
    elif issue == "empty":
        body["results"][0]["text"] = ""
    elif issue == "too_long":
        body["results"][0]["text"] = "a" * 1001
    elif issue == "no_id":
        body.pop("requestId")
    elif issue == "error":
        body["error"] = "failure"
    else:
        body["results"] *= 2
    with pytest.raises(ValueError):
        parse(CONTENTS, payload, body)


def test_catalog_merge_and_route_validation(tmp_path):
    from openmcp.integrations.firecrawl.catalog import provider as firecrawl

    path = tmp_path / "catalog.json"
    path.write_text(json.dumps([firecrawl()]))
    write_catalog(path, "test")
    write_catalog(path, "test")
    assert [p["provider_id"] for p in json.loads(path.read_text())] == ["firecrawl", "exa"]
    definition = provider()
    definition["queries"][0]["url"] = ORIGIN + "/answer"
    with pytest.raises(ValueError):
        Provider.model_validate(definition)


@pytest.mark.parametrize("identifier", SERVICES)
async def test_discover_execute_capture_replay_recovery(store, monkeypatch, identifier):
    monkeypatch.setenv("EXA_API_KEY", SECRET)
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("exa-owner")["account_id"]
    api_tests.credit(store, owner)
    principal, credential = api_tests.grant(store, owner)
    payload, response = sample(identifier)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["x-api-key"] == SECRET and "authorization" not in request.headers
        assert str(request.url) == service(identifier).url
        return httpx.Response(200, json=response)

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
            found = await client.post("/v1/discover", headers=auth, json={"query": "Exa"})
            assert found.status_code == 200 and identifier in found.text
            assert SECRET not in found.text and ORIGIN not in found.text
            headers = auth | {"Idempotency-Key": "once"}
            first = await client.post("/v1/execute", headers=headers, json=request)
            assert first.status_code == 202 and store.account(owner)["reserved_cents"] == 2
            await worker.tick()
            replay = await client.post("/v1/execute", headers=headers, json=request)
            assert replay.json()["status"] == "completed"
            assert replay.json()["execution_id"] == first.json()["execution_id"]
            row = store.execution_internal(first.json()["execution_id"])
            assert row["provider_cost_microusd"] == SERVICES[identifier]["max_cost_microusd"]
            assert SECRET not in json.dumps(row, default=str)
            assert (
                store.account(owner)["spent_cents"] == 2
                and store.account(owner)["reserved_cents"] == 0
            )
            saved = store.reserve(principal, "crash", request, service(identifier))
            data, receipt, cost = parse(identifier, payload, response)
            store.mark_sent(saved["execution_id"])
            store.mark_paid(saved["execution_id"], receipt, data=data, cost_microusd=cost)
            await worker.tick()
            assert store.execution_internal(saved["execution_id"])["status"] == "completed"
            assert len(calls) == 1
        store.migrate()
        assert store.account(owner)["spent_cents"] == 4
    finally:
        await caller.close()


@pytest.mark.parametrize("issue", ["timeout", "http429", "excess_cost", "empty_page"])
async def test_sent_failure_holds_without_resubmission(store, monkeypatch, issue):
    monkeypatch.setenv("EXA_API_KEY", SECRET)
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("exa-failure")["account_id"]
    api_tests.credit(store, owner)
    principal, _ = api_tests.grant(store, owner)
    payload, body = sample(CONTENTS)
    calls = []

    def handler(request):
        calls.append(request)
        if issue == "timeout":
            raise httpx.TimeoutException("timeout")
        if issue == "http429":
            return httpx.Response(429, json={"error": "rate limited"})
        if issue == "excess_cost":
            body["costDollars"]["total"] = 0.1
        else:
            body["results"][0]["text"] = ""
        return httpx.Response(200, json=body)

    selected = service(CONTENTS)
    row = store.reserve(
        principal,
        "failure",
        {"endpoint_id": CONTENTS, "payload": payload, "max_price_cents": 2},
        selected,
    )
    settings = ProductSettings(_env_file=None)
    caller = ApiKeyCaller(settings, store, transport=httpx.MockTransport(handler))
    worker = Worker(settings, store, Mock(), api_caller=caller)
    try:
        await worker.tick()
        held = store.execution_internal(row["execution_id"])
        assert held["status"] == "needs_review" and held["payment_status"] == "sent"
        assert store.account(owner)["reserved_cents"] == 2
        await worker.tick()
        assert len(calls) == 1
    finally:
        await caller.close()


async def test_compressed_vendor_response_is_decoded_once():
    import gzip

    payload, body = sample(SEARCH)
    compressed = gzip.compress(json.dumps(body).encode())

    def handler(request):
        return httpx.Response(
            200,
            headers={
                "Content-Encoding": "gzip",
                "Content-Length": str(len(compressed)),
                "Content-Type": "application/json",
            },
            content=compressed,
        )

    caller = ApiKeyCaller(
        ProductSettings(_env_file=None), None, transport=httpx.MockTransport(handler)
    )
    try:
        response = await caller._post(service(SEARCH), b"{}", {})
        assert "content-encoding" not in response.headers
        data, _, cost = parse(SEARCH, payload, response.json())
        assert data["provider"] == "Exa" and cost == 7000
        assert int(response.headers["content-length"]) == len(response.content)
    finally:
        await caller.close()
