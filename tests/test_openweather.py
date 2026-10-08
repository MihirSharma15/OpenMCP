"""OpenWeather GET adapter and account purchases; all vendor calls mocked."""

import json
from unittest.mock import Mock

import httpx
import pytest

from openmcp.integrations.openweather.catalog import CURRENT, FORECAST, ORIGIN, SERVICES, provider
from openmcp.integrations.openweather.cli import write_catalog
from openmcp.integrations.openweather.protocol import parse, prepare, request_cost
from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings, Provider
from openmcp.product.worker import Worker
from tests import test_product_api_call as api_tests

postgres_url = api_tests.postgres_url
store = api_tests.store
SECRET = "openweather-private-mocked-key"


def service(identifier):
    return next(
        q for q in Provider.model_validate(provider()).queries if q.endpoint_id == identifier
    )


def sample(identifier):
    payload = {"latitude": 40.71, "longitude": -74.0}
    point = {
        "dt": 1791400000,
        "main": {"temp": 18.1, "humidity": 65},
        "weather": [{"id": 800, "description": "clear sky"}],
        "wind": {"speed": 2.0},
    }
    if identifier == CURRENT:
        return payload, point | {"cod": 200, "name": "New York", "timezone": -14400}
    return payload | {"limit": 1}, {
        "cod": "200",
        "cnt": 1,
        "list": [point],
        "city": {"name": "New York", "country": "US", "timezone": -14400},
    }


@pytest.mark.parametrize("identifier", SERVICES)
@pytest.mark.parametrize("units", ["metric", "imperial", "standard"])
def test_parameters_normalization_and_free_cost(identifier, units):
    payload, response = sample(identifier)
    payload["units"] = units
    params, key = prepare(identifier, service(identifier).url, "live", payload, SECRET)
    assert params["lat"] == payload["latitude"] and params["units"] == units
    assert key == SECRET and "appid" not in params
    data, receipt, cost = parse(identifier, payload, response, 0)
    assert cost == 0 and receipt["cost_basis"] == "configured_per_request_estimate"
    assert data["units"] == units and data["attribution"]["name"] == "OpenWeather"
    assert SECRET not in json.dumps(data) and ORIGIN not in json.dumps(service(identifier).public())


@pytest.mark.parametrize(
    "payload",
    [
        {"latitude": 91, "longitude": 0},
        {"latitude": 0, "longitude": -181},
        {"latitude": float("nan"), "longitude": 0},
        {"latitude": True, "longitude": 0},
        {"latitude": 0, "longitude": 0, "appid": "override"},
        {"latitude": 0, "longitude": 0, "units": "bad"},
    ],
)
def test_invalid_inputs_rejected(payload):
    with pytest.raises(ValueError):
        prepare(CURRENT, service(CURRENT).url, "test", payload, SECRET)


@pytest.mark.parametrize("value", ["-1", "1.5", "", "bad", "1000001"])
def test_invalid_cost_setting(value):
    with pytest.raises(ValueError):
        request_cost(value)


@pytest.mark.parametrize("issue", ["cod", "empty", "temperature", "time", "weather", "count"])
def test_unusable_forecast_needs_review(issue):
    payload, body = sample(FORECAST)
    if issue == "cod":
        body["cod"] = 401
    elif issue == "empty":
        body["list"] = []
    elif issue == "temperature":
        body["list"][0]["main"]["temp"] = None
    elif issue == "time":
        body["list"][0]["dt"] = 0
    elif issue == "weather":
        body["list"][0]["weather"] = []
    else:
        body["cnt"] = 40
    with pytest.raises(ValueError):
        parse(FORECAST, payload, body, 0)


def test_routes_and_merged_catalog_preserve_existing(tmp_path):
    from openmcp.integrations.exa.catalog import provider as exa

    path = tmp_path / "catalog.json"
    path.write_text(json.dumps([exa()]))
    write_catalog(path, "test")
    assert [p["provider_id"] for p in json.loads(path.read_text())] == ["exa", "openweather"]
    bad = provider()
    bad["queries"][0]["url"] = "https://api.openweathermap.org/data/3.0/onecall"
    with pytest.raises(ValueError):
        Provider.model_validate(bad)


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_http_failure_is_not_retried_or_captured(monkeypatch, status):
    monkeypatch.setenv("OPENWEATHER_API_KEY", SECRET)
    monkeypatch.delenv("OPENWEATHER_REQUEST_COST_MICROUSD", raising=False)
    fake = Mock()
    fake.provider_secret_ref.return_value = "OPENWEATHER_API_KEY"
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"cod": status, "message": "rejected"})

    caller = ApiKeyCaller(
        ProductSettings(_env_file=None), fake, transport=httpx.MockTransport(handler)
    )
    from openmcp.product.settlement import TerminalFailure

    payload, _ = sample(CURRENT)
    row = {
        "execution_id": "failure",
        "payment_status": "unsigned",
        "service": service(CURRENT).model_dump(),
        "payload": payload,
    }
    try:
        with pytest.raises(TerminalFailure):
            await caller.purchase(row)
        with pytest.raises(TerminalFailure):
            await caller.purchase(row | {"payment_status": "sent"})
        assert len(calls) == 1
        fake.mark_paid.assert_not_called()
    finally:
        await caller.close()


@pytest.mark.parametrize("identifier", SERVICES)
async def test_discover_execute_capture_replay_recovery(store, monkeypatch, identifier):
    monkeypatch.setenv("OPENWEATHER_API_KEY", SECRET)
    monkeypatch.setenv("OPENWEATHER_REQUEST_COST_MICROUSD", "0")
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("openweather-owner")["account_id"]
    api_tests.credit(store, owner)
    principal, credential = api_tests.grant(store, owner)
    payload, response = sample(identifier)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and request.url.params["appid"] == SECRET
        assert "authorization" not in request.headers and "x-api-key" not in request.headers
        assert str(request.url).split("?")[0] == service(identifier).url
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
            found = await client.post("/v1/discover", headers=auth, json={"query": "OpenWeather"})
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
            data, receipt, cost = parse(identifier, payload, response, 0)
            store.mark_sent(saved["execution_id"])
            store.mark_paid(saved["execution_id"], receipt, data=data, cost_microusd=cost)
            await worker.tick()
            assert store.execution_internal(saved["execution_id"])["status"] == "completed"
            assert len(calls) == 1
        store.migrate()
        assert store.account(owner)["spent_cents"] == 4
    finally:
        await caller.close()
