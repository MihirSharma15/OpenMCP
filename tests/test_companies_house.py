"""Companies House integration checks. All automated vendor requests are mocked."""

import base64
import json
from unittest.mock import Mock

import httpx
import pytest

from openmcp.integrations.companies_house.catalog import (
    FILINGS,
    OFFICERS,
    ORIGIN,
    PROFILE,
    SEARCH,
    SERVICES,
    provider,
)
from openmcp.integrations.companies_house.cli import write_catalog
from openmcp.integrations.companies_house.protocol import parse, prepare
from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings, Provider
from openmcp.product.settlement import TerminalFailure
from openmcp.product.worker import Worker
from tests import test_product_api_call as api_tests

postgres_url = api_tests.postgres_url
store = api_tests.store
SECRET = "companies-house-private-mocked-key"


def service(identifier):
    return next(
        q for q in Provider.model_validate(provider()).queries if q.endpoint_id == identifier
    )


def sample(identifier):
    payload = {"company_number": "00000006"}
    if identifier == PROFILE:
        return payload, {
            "company_number": "00000006",
            "company_name": "Example PLC",
            "company_status": "active",
            "accounts": {"overdue": False},
        }
    payload["items_per_page"] = 1
    item = {
        SEARCH: {"company_number": "00000006", "title": "Example PLC"},
        OFFICERS: {"name": "Example Director", "officer_role": "director"},
        FILINGS: {
            "transaction_id": "abcd",
            "type": "AA",
            "date": "2026-01-01",
            "description": "accounts-with-accounts-type-full",
        },
    }[identifier]
    if identifier == SEARCH:
        payload = {"query": "Example", "items_per_page": 1}
    return payload, {
        "items": [item],
        "items_per_page": 1,
        "start_index": 0,
        "total_count" if identifier == FILINGS else "total_results": 2,
    }


@pytest.mark.parametrize("identifier", SERVICES)
def test_request_and_result(identifier):
    payload, body = sample(identifier)
    target, params, authorization = prepare(
        identifier, service(identifier).url, "live", payload, SECRET
    )
    assert target.startswith(ORIGIN) and "{" not in target
    assert base64.b64decode(authorization.split()[1]).decode() == SECRET + ":"
    assert SECRET not in json.dumps(params)
    result, receipt, cost = parse(identifier, payload, body)
    assert cost == 0 and receipt["cost_basis"] == "free_public_data"
    assert result["provider"] == "Companies House"
    if identifier != PROFILE:
        assert result["pagination"]["next_start_index"] == 1
    public = service(identifier).public()
    assert ORIGIN not in json.dumps(public)
    assert "provider_price_cents" not in public


@pytest.mark.parametrize("identifier", [SEARCH, OFFICERS, FILINGS])
def test_empty_page_is_valid_and_has_no_next_page(identifier):
    payload, body = sample(identifier)
    body["items"] = []
    body["total_count" if identifier == FILINGS else "total_results"] = 0
    data, _, _ = parse(identifier, payload, body)
    assert data["items"] == [] and data["pagination"]["next_start_index"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"company_number": "../../x"},
        {"company_number": "00000006\n"},
        {"company_number": "00000006?x=y"},
        {"company_number": "sc123456"},
        {"company_number": 6},
        {"company_number": "00000006", "url": "https://evil.example"},
        {"company_number": "00000006", "items_per_page": 101},
        {"company_number": "00000006", "start_index": -1},
        {"company_number": "00000006", "items_per_page": True},
    ],
)
def test_invalid_inputs_do_not_build_request(payload):
    with pytest.raises(ValueError):
        prepare(OFFICERS, service(OFFICERS).url, "test", payload, SECRET)


@pytest.mark.parametrize("query", ["", "   ", "x" * 201])
def test_invalid_search(query):
    with pytest.raises(ValueError):
        prepare(SEARCH, service(SEARCH).url, "test", {"query": query}, SECRET)


@pytest.mark.parametrize("number", ["00000006", "SC123456", "OC123456", "OE012345"])
def test_prefixes_and_leading_zeros(number):
    target, _, _ = prepare(
        PROFILE, service(PROFILE).url, "live", {"company_number": number}, SECRET
    )
    assert target == ORIGIN + "/company/" + number


@pytest.mark.parametrize("bad", ["", "a b", "a:b", "å"])
def test_invalid_keys(bad):
    with pytest.raises(ValueError):
        prepare(SEARCH, service(SEARCH).url, "test", {"query": "Example"}, bad)


@pytest.mark.parametrize("issue", ["errors", "missing", "count", "offset", "item", "boolean"])
def test_malformed_results(issue):
    payload, body = sample(OFFICERS)
    if issue == "errors":
        body["errors"] = []
    elif issue == "missing":
        del body["items"]
    elif issue == "count":
        body["items"] *= 2
    elif issue == "offset":
        body["start_index"] = 10
    elif issue == "item":
        del body["items"][0]["name"]
    else:
        body["total_results"] = True
    with pytest.raises(ValueError):
        parse(OFFICERS, payload, body)


def test_profile_must_match_requested_company():
    payload, body = sample(PROFILE)
    body["company_number"] = "12345678"
    with pytest.raises(ValueError):
        parse(PROFILE, payload, body)


def test_catalog_merge_and_route_settlement_restrictions(tmp_path):
    from openmcp.integrations.openweather.catalog import provider as weather

    path = tmp_path / "catalog.json"
    path.write_text(json.dumps([weather()]))
    write_catalog(path, "test")
    assert [p["provider_id"] for p in json.loads(path.read_text())] == [
        "openweather",
        "companies-house",
    ]
    for field, value in [
        ("url", ORIGIN + "/company/{company_number}/charges"),
        ("url", ORIGIN + "/search/companies?apikey=bad"),
        ("settlement", "mpp"),
    ]:
        bad = provider()
        bad["queries"][0][field] = value
        with pytest.raises(ValueError):
            Provider.model_validate(bad)


@pytest.mark.parametrize("status", [401, 404, 429, 500, 302])
async def test_http_errors_are_not_captured_or_retried(monkeypatch, status):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", SECRET)
    fake = Mock()
    fake.provider_secret_ref.return_value = "COMPANIES_HOUSE_API_KEY"
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={"errors": [{"error": "failed"}]},
            headers={"Location": "https://evil.example"},
        )

    caller = ApiKeyCaller(
        ProductSettings(_env_file=None), fake, transport=httpx.MockTransport(handler)
    )
    payload, _ = sample(PROFILE)
    row = {
        "execution_id": "failure",
        "payment_status": "unsigned",
        "service": service(PROFILE).model_dump(),
        "payload": payload,
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


@pytest.mark.parametrize("identifier", SERVICES)
async def test_discover_execute_capture_replay_and_saved_recovery(store, monkeypatch, identifier):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", SECRET)
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("companies-house-owner")["account_id"]
    api_tests.credit(store, owner)
    principal, credential = api_tests.grant(store, owner)
    payload, body = sample(identifier)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert (
            base64.b64decode(request.headers["Authorization"].split()[1]).decode() == SECRET + ":"
        )
        assert "{" not in request.url.path and SECRET not in str(request.url)
        if identifier == SEARCH:
            assert request.url.path == "/search/companies" and request.url.params["q"] == "Example"
        else:
            assert request.url.path == service(identifier).url.removeprefix(ORIGIN).replace(
                "{company_number}", "00000006"
            )
            assert "company_number" not in request.url.params
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
            found = await client.post(
                "/v1/discover", headers=auth, json={"query": "Companies House"}
            )
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
            assert row["provider_cost_microusd"] == 0
            assert SECRET not in json.dumps(row, default=str)
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
