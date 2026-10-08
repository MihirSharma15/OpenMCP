"""API2PDF tests use synthetic responses, never live vendor credentials."""

import json
from unittest.mock import Mock

import httpx
import pytest

from openmcp.integrations.api2pdf.catalog import MARKDOWN, URL, provider
from openmcp.integrations.api2pdf.cli import write_catalog
from openmcp.integrations.api2pdf.protocol import parse, prepare
from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings, Provider
from openmcp.product.settlement import TerminalFailure
from openmcp.product.worker import Worker
from tests import test_product_api_call as api_tests

postgres_url = api_tests.postgres_url
store = api_tests.store
SECRET = "api2pdf-test-secret"
PAYLOAD = {"markdown": "# Report\n\n**Hello**, world.", "filename": "report.pdf"}
BODY = {
    "Success": True,
    "Error": None,
    "FileUrl": "https://files.example.com/report.pdf",
    "ResponseId": "response-test-id",
    "Cost": 0.00017251586914062501,
    "MbOut": 0.08830547332763672,
}


def service():
    return Provider.model_validate(provider()).queries[0]


def test_protocol_and_private_catalog(tmp_path):
    outgoing, auth = prepare(MARKDOWN, URL, "live", PAYLOAD, SECRET)
    assert auth == SECRET and SECRET not in json.dumps(outgoing)
    assert outgoing["markdown"] == PAYLOAD["markdown"]
    assert outgoing["fileName"] == "report.pdf" and outgoing["inline"] is False
    assert outgoing["useCustomStorage"] is False
    data, receipt, cost = parse(MARKDOWN, PAYLOAD, BODY)
    assert cost == 173  # Preserve sub-microdollar vendor charge by rounding up.
    assert data["file_url"] == BODY["FileUrl"] and data["retention_seconds"] == 86400
    assert receipt["vendor_cost_usd"] == str(BODY["Cost"])
    public = service().public()
    assert URL not in json.dumps(public) and "secret_ref" not in public
    assert "provider_price_cents" not in public
    assert public["price_cents"] == 3
    path = tmp_path / "catalog.json"
    write_catalog(path, "live")
    write_catalog(path, "live")
    assert len(ProductSettings(_env_file=None, catalog_path=path).catalog()) == 1


@pytest.mark.parametrize("mode", ["test", "live"])
def test_defaults_and_response_casing(mode):
    outgoing, _ = prepare(MARKDOWN, URL, mode, {"markdown": "Report"}, SECRET)
    assert outgoing["fileName"] == "report.pdf"
    camel = {k[0].lower() + k[1:]: v for k, v in BODY.items()}
    data, _, _ = parse(MARKDOWN, {"markdown": "Report"}, camel)
    assert data["filename"] == "report.pdf"


@pytest.mark.parametrize(
    "markdown",
    [
        "",
        " \n",
        "x" * 20001,
        '<img src="http://localhost">',
        '<script>fetch("x")</script>',
        "![image](https://example.com/image.png)",
        "![image][reference]",
        "```html\n<img>\n```",
    ],
)
def test_reject_unsupported_markdown(markdown):
    with pytest.raises(ValueError):
        prepare(MARKDOWN, URL, "test", {"markdown": markdown}, SECRET)


@pytest.mark.parametrize(
    "filename", ["../a.pdf", "report.txt", "a/b.pdf", "x.pdf\n", "x" * 100 + ".pdf"]
)
def test_reject_filename(filename):
    with pytest.raises(ValueError):
        prepare(MARKDOWN, URL, "test", PAYLOAD | {"filename": filename}, SECRET)


@pytest.mark.parametrize(
    "extra",
    [
        {"options": {"delay": 90}},
        {"url": "https://example.com"},
        {"storage": {}},
        {"outputBinary": True},
    ],
)
def test_reject_unsupported_options(extra):
    with pytest.raises(ValueError):
        prepare(MARKDOWN, URL, "test", PAYLOAD | extra, SECRET)


@pytest.mark.parametrize(
    "change",
    [
        {"url": URL + "?apikey=x"},
        {"url": "https://v2-xl.api2pdf.com/chrome/pdf/markdown"},
        {"endpoint_id": "api2pdf-url-to-pdf"},
        {"settlement": "mpp"},
    ],
)
def test_reject_unapproved_catalog(change):
    catalog = provider()
    catalog["queries"][0].update(change)
    with pytest.raises(ValueError):
        Provider.model_validate(catalog)


@pytest.mark.parametrize(
    "changes",
    [
        {"Success": False},
        {"Success": 1},
        {"Error": "failure"},
        {"ResponseId": ""},
        {"FileUrl": "http://files.example.com/a.pdf"},
        {"FileUrl": "https://127.0.0.1/a.pdf"},
        {"FileUrl": "https://user:pass@files.example.com/a.pdf"},
        {"Cost": None},
        {"Cost": True},
        {"Cost": -0.1},
        {"Cost": 0.0300001},
        {"Cost": "0.001"},
        {"Cost": float("nan")},
        {"MbOut": None},
        {"MbOut": 6},
    ],
)
def test_unusable_or_over_budget_result(changes):
    with pytest.raises(ValueError):
        parse(MARKDOWN, PAYLOAD, BODY | changes)


@pytest.mark.parametrize("failure", ["http", "timeout", "malformed"])
async def test_sent_failure_never_resubmits(monkeypatch, failure):
    monkeypatch.setenv("API2PDF_API_KEY", SECRET)
    fake = Mock()
    fake.provider_secret_ref.return_value = "API2PDF_API_KEY"
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == SECRET
        if failure == "timeout":
            raise httpx.ReadTimeout("uncertain")
        return httpx.Response(500 if failure == "http" else 200, json={})

    caller = ApiKeyCaller(
        ProductSettings(_env_file=None), fake, transport=httpx.MockTransport(handler)
    )
    row = {
        "execution_id": "once",
        "payment_status": "unsigned",
        "service": service().model_dump(),
        "payload": PAYLOAD,
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


async def test_invalid_input_never_sends(monkeypatch):
    monkeypatch.setenv("API2PDF_API_KEY", SECRET)
    fake = Mock()
    fake.provider_secret_ref.return_value = "API2PDF_API_KEY"
    caller = ApiKeyCaller(
        ProductSettings(_env_file=None),
        fake,
        transport=httpx.MockTransport(lambda req: pytest.fail("Must not send")),
    )
    row = {
        "execution_id": "invalid",
        "payment_status": "unsigned",
        "service": service().model_dump(),
        "payload": {"markdown": "<script>"},
    }
    try:
        with pytest.raises(TerminalFailure):
            await caller.purchase(row)
        fake.mark_sent.assert_not_called()
    finally:
        await caller.close()


async def test_account_discover_execute_capture_replay_recovery(store, monkeypatch):
    monkeypatch.setenv("API2PDF_API_KEY", SECRET)
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("api2pdf-owner")["account_id"]
    api_tests.credit(store, owner)
    principal, credential = api_tests.grant(store, owner)
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == URL and request.method == "POST"
        assert request.headers["Authorization"] == SECRET
        assert json.loads(request.content)["markdown"] == PAYLOAD["markdown"]
        return httpx.Response(200, json=BODY)

    settings = ProductSettings(_env_file=None)
    caller = ApiKeyCaller(settings, store, transport=httpx.MockTransport(handler))
    worker = Worker(settings, store, Mock(), api_caller=caller)
    app = create_app(
        settings, store=store, verifier=api_tests.Closable(), stripe=api_tests.Closable()
    )
    auth = {"Authorization": "Bearer " + credential["secret"]}
    request = {"endpoint_id": MARKDOWN, "payload": PAYLOAD, "max_price_cents": 3}
    try:
        await worker.tick()  # Publish worker readiness before HTTP execute.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api.test"
        ) as client:
            found = await client.post("/v1/discover", headers=auth, json={"query": "PDF report"})
            assert found.status_code == 200 and MARKDOWN in found.text
            assert SECRET not in found.text and URL not in found.text
            headers = auth | {"Idempotency-Key": "once"}
            first = await client.post("/v1/execute", headers=headers, json=request)
            assert first.status_code == 202 and store.account(owner)["reserved_cents"] == 3
            await worker.tick()
            replay = await client.post("/v1/execute", headers=headers, json=request)
            assert replay.json()["status"] == "completed"
            assert replay.json()["execution_id"] == first.json()["execution_id"]
            row = store.execution_internal(first.json()["execution_id"])
            assert (
                row["provider_cost_microusd"] == 173 and row["data"]["file_url"] == BODY["FileUrl"]
            )
            assert SECRET not in json.dumps(row, default=str)
            assert (
                store.account(owner)["spent_cents"] == 3
                and store.account(owner)["reserved_cents"] == 0
            )
            # Recover a crash after receipt/result persistence without another conversion.
            saved = store.reserve(principal, "crash", request, service())
            data, receipt, cost = parse(MARKDOWN, PAYLOAD, BODY)
            store.mark_sent(saved["execution_id"])
            store.mark_paid(saved["execution_id"], receipt, data=data, cost_microusd=cost)
            await worker.tick()
            assert store.execution_internal(saved["execution_id"])["status"] == "completed"
            assert len(calls) == 1
        store.migrate()
        assert store.account(owner)["spent_cents"] == 6
    finally:
        await caller.close()


@pytest.mark.parametrize("failure", ["missing_key", "sent_failure"])
async def test_worker_refund_or_hold(store, monkeypatch, failure):
    monkeypatch.setenv("API2PDF_API_KEY", SECRET)
    if failure == "missing_key":
        monkeypatch.delenv("API2PDF_API_KEY")
    store.sync_catalog([Provider.model_validate(provider())])
    owner = store.bootstrap("api2pdf-failure")["account_id"]
    api_tests.credit(store, owner)
    principal, _ = api_tests.grant(store, owner)
    row = store.reserve(
        principal,
        "failure",
        {"endpoint_id": MARKDOWN, "payload": PAYLOAD, "max_price_cents": 3},
        service(),
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(502, json={"error": "unknown"})

    caller = ApiKeyCaller(
        ProductSettings(_env_file=None), store, transport=httpx.MockTransport(handler)
    )
    worker = Worker(ProductSettings(_env_file=None), store, Mock(), api_caller=caller)
    try:
        await worker.tick()
        done = store.execution_internal(row["execution_id"])
        if failure == "missing_key":
            assert done["status"] == "refunded" and done["refunded_cents"] == 3 and not calls
        else:
            assert done["status"] == "needs_review" and done["payment_status"] == "sent"
            assert store.account(owner)["reserved_cents"] == 3
            store.requeue(row["execution_id"])
            await worker.tick()
            assert len(calls) == 1
    finally:
        await caller.close()
