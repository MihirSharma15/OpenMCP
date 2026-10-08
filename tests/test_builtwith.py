"""BuiltWith tests never use live credentials or vendor calls."""

import asyncio
import json
from unittest.mock import Mock

import httpx
import pytest

from openmcp.integrations.builtwith.catalog import ORIGIN, SERVICES, SUMMARY, TRENDS, provider
from openmcp.integrations.builtwith.protocol import parse, prepare
from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings, Provider
from openmcp.product.settlement import TerminalFailure
from openmcp.product.worker import Worker
from tests import test_product_api_call as api_tests

postgres_url = api_tests.postgres_url
store = api_tests.store
SECRET = "builtwith-mocked-secret"


def service(identifier):
    return next(
        q for q in Provider.model_validate(provider()).queries if q.endpoint_id == identifier
    )


def sample(identifier):
    if identifier == SUMMARY:
        return {"domain": "example.com"}, {
            "domain": "example.com",
            "first": 1000,
            "last": 2000,
            "groups": [
                {
                    "name": "analytics",
                    "live": 1,
                    "dead": 0,
                    "oldest": 1000,
                    "latest": 2000,
                    "categories": [],
                }
            ],
        }
    return {"technology": "Shopify"}, {
        "Tech": {"name": "Shopify", "categories": ["shop"], "coverage": {"live": 100, "ten_k": 1}}
    }


@pytest.mark.parametrize("identifier", SERVICES)
def test_protocol_and_catalog(identifier):
    payload, body = sample(identifier)
    params = prepare(identifier, service(identifier).url, "live", payload, SECRET)
    assert SECRET not in json.dumps(params)
    data, receipt, cost = parse(identifier, payload, body)
    assert data["provider"] == "BuiltWith" and cost == 0 and receipt["cost_basis"] == "free_api"
    public = service(identifier).public()
    assert ORIGIN not in json.dumps(public) and "provider_price_cents" not in public
    for field, value in [("url", ORIGIN + "/v26/api.json"), ("settlement", "mpp")]:
        bad = provider()
        bad["queries"][0][field] = value
        with pytest.raises(ValueError):
            Provider.model_validate(bad)


@pytest.mark.parametrize(
    "domain",
    [
        "http://example.com",
        "example.com/path",
        "127.0.0.1",
        "a.com,b.com",
        "example.com\n",
        "localhost",
        "EXAMPLE.COM",
    ],
)
def test_invalid_domain(domain):
    with pytest.raises(ValueError):
        prepare(SUMMARY, service(SUMMARY).url, "test", {"domain": domain}, SECRET)


@pytest.mark.parametrize("technology", ["", "a b", "a&KEY=x", "a\n", "x" * 101])
def test_invalid_technology(technology):
    with pytest.raises(ValueError):
        prepare(TRENDS, service(TRENDS).url, "test", {"technology": technology}, SECRET)


@pytest.mark.parametrize("identifier", SERVICES)
@pytest.mark.parametrize("issue", ["error", "missing", "mismatch", "boolean", "negative"])
def test_malformed_results(identifier, issue):
    payload, body = sample(identifier)
    if issue == "error":
        body["Errors"] = [{"message": "invalid key"}]
    elif issue == "missing":
        body = {}
    elif identifier == SUMMARY:
        if issue == "mismatch":
            body["domain"] = "evil.com"
        else:
            body["first"] = True if issue == "boolean" else -1
    else:
        if issue == "mismatch":
            body["Tech"]["name"] = "WordPress"
        else:
            body["Tech"]["coverage"]["live"] = True if issue == "boolean" else -1
    with pytest.raises(ValueError):
        parse(identifier, payload, body)


@pytest.mark.parametrize("status", [401, 429, 500, 302])
async def test_failure_does_not_capture_or_resend(monkeypatch, status):
    monkeypatch.setenv("BUILTWITH_API_KEY", SECRET)
    fake = Mock()
    fake.provider_secret_ref.return_value = "BUILTWITH_API_KEY"
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"Errors": ["failure"]})

    caller = ApiKeyCaller(
        ProductSettings(_env_file=None), fake, transport=httpx.MockTransport(handler)
    )
    row = {
        "execution_id": "failure",
        "payment_status": "unsigned",
        "service": service(SUMMARY).model_dump(),
        "payload": sample(SUMMARY)[0],
    }
    try:
        with pytest.raises(TerminalFailure):
            await caller.purchase(row)
        with pytest.raises(TerminalFailure):
            await caller.purchase(row | {"payment_status": "sent"})
        assert len(calls) == 1
        fake.mark_paid.assert_not_called()
        fake.finish.assert_not_called()
    finally:
        await caller.close()


async def test_calls_are_spaced():
    starts = []

    def handler(request):
        starts.append(asyncio.get_running_loop().time())
        return httpx.Response(200, json=sample(SUMMARY)[1])

    caller = ApiKeyCaller(
        ProductSettings(_env_file=None), Mock(), transport=httpx.MockTransport(handler)
    )
    try:
        body = json.dumps({"LOOKUP": "example.com"})
        await asyncio.gather(
            *(
                caller._post(service(SUMMARY), body, {"Authorization": "Bearer " + SECRET})
                for _ in range(2)
            )
        )
        assert starts[1] - starts[0] >= 1
    finally:
        await caller.close()


@pytest.mark.parametrize("identifier", SERVICES)
async def test_account_workflow_and_recovery(store, monkeypatch, identifier):
    monkeypatch.setenv("BUILTWITH_API_KEY", SECRET)
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("builtwith-owner")["account_id"]
    api_tests.credit(store, owner)
    principal, credential = api_tests.grant(store, owner)
    payload, body = sample(identifier)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "api.builtwith.com"
        assert request.url.params["KEY"] == SECRET
        assert "Authorization" not in request.headers
        assert (
            request.url.params["LOOKUP" if identifier == SUMMARY else "TECH"]
            == payload["domain" if identifier == SUMMARY else "technology"]
        )
        return httpx.Response(200, json=body)

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
            found = await client.post("/v1/discover", headers=auth, json={"query": "BuiltWith"})
            assert (
                found.status_code == 200 and identifier in found.text and SECRET not in found.text
            )
            headers = auth | {"Idempotency-Key": "once"}
            first = await client.post("/v1/execute", headers=headers, json=request)
            assert first.status_code == 202 and store.account(owner)["reserved_cents"] == 2
            await worker.tick()
            replay = await client.post("/v1/execute", headers=headers, json=request)
            assert replay.json()["status"] == "completed"
            assert replay.json()["execution_id"] == first.json()["execution_id"]
            row = store.execution_internal(first.json()["execution_id"])
            assert row["provider_cost_microusd"] == 0 and SECRET not in json.dumps(row, default=str)
            assert (
                store.account(owner)["spent_cents"] == 2
                and store.account(owner)["reserved_cents"] == 0
            )
            saved = store.reserve(principal, "crash", request, service(identifier))
            data, receipt, cost = parse(identifier, payload, body)
            store.mark_sent(saved["execution_id"])
            store.mark_paid(saved["execution_id"], receipt, data=data, cost_microusd=cost)
            await worker.tick()
            assert store.execution_internal(saved["execution_id"])["status"] == "completed"
            assert len(calls) == 1
        store.migrate()
        assert store.account(owner)["spent_cents"] == 4
    finally:
        await caller.close()
