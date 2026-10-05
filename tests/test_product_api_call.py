"""API-key purchases: one POST, no key on the execution, hold after the request is sent."""

import json
import os
import time
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import httpx
import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from openmcp.product.api_call import ApiKeyCaller
from openmcp.product.app import create_app
from openmcp.product.config import ProductSettings, Provider, Service
from openmcp.product.models import now
from openmcp.product.settlement import TerminalFailure
from openmcp.product.store import Store
from openmcp.product.worker import Worker

SECRET = "omcp-test-secret-9f3a"
REF = "OPENMCP_TEST_PROVIDER_KEY"


def api_service(**updates):
    fields = {
        "endpoint_id": "web-search",
        "name": "Web search",
        "description": "Searches the public web",
        "url": "https://provider.example/search",
        "price_cents": 40,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "enabled": True,
        "mode": "test",
        "supports_idempotency": True,
        "settlement": "api_key",
    }
    fields.update(updates)
    return Service(**fields)


def provider_for(service, secret_ref=REF):
    return Provider(
        provider_id="web-search-co",
        name="Web Search Co",
        description="Publishes the search query",
        secret_ref=secret_ref,
        queries=[service],
    )


def _base_query(**updates):
    query = {
        "endpoint_id": "web-search",
        "name": "Web search",
        "description": "Searches the public web",
        "url": "https://provider.example/search",
        "price_cents": 40,
        "input_schema": {"type": "object"},
        "enabled": True,
        "mode": "test",
        "supports_idempotency": True,
        "settlement": "api_key",
    }
    query.update(updates)
    return query


def _catalog(tmp_path, query, secret_ref=REF):
    provider = {
        "provider_id": "web-search-co",
        "name": "Web Search Co",
        "description": "Publishes the search query",
        "queries": [query],
    }
    if secret_ref is not None:
        provider["secret_ref"] = secret_ref
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps([provider]))
    return ProductSettings(_env_file=None, catalog_path=path).catalog()


def test_default_settlement_stays_mpp_and_secret_ref_is_not_a_service_field():
    service = Service(
        endpoint_id="example",
        name="Example",
        description="Example service",
        url="https://provider.example/buy",
        recipient="0x" + "12" * 20,
        price_cents=40,
        input_schema={"type": "object"},
        enabled=True,
        mode="test",
        supports_idempotency=True,
    )
    assert service.settlement == "mpp"
    assert "secret_ref" not in service.model_dump()
    assert "secret_ref" not in Service.model_fields
    dumped = service.model_dump()
    dumped.pop("settlement")
    assert Service.model_validate(dumped).settlement == "mpp"


def test_catalog_rejects_private_urls_and_allows_test_loopback(tmp_path):
    blocked = [
        "http://10.0.0.1/q",
        "http://192.168.1.1/q",
        "http://172.16.0.1/q",
        "http://169.254.169.254/latest",
        "http://[fe80::1]/q",
        "http://[fd00::1]/q",
        "http://0.0.0.0/q",
        "http://user:pass@provider.example/q",
        "https://127.0.0.1/q",
        "https://localhost/q",
        "http://localhost/q",
    ]
    for url in blocked:
        mode = "live" if url.startswith("https") or url.startswith("http://localhost") else "test"
        if url.startswith("http://localhost"):
            mode = "live"
        with pytest.raises(ValueError):
            api_service(url=url, mode=mode, settlement="mpp", recipient="0x" + "ab" * 20)

    for url in ("http://127.0.0.1:8080/q", "http://127.1.2.3/q", "http://[::1]/q", "http://localhost/q"):
        service = api_service(url=url)
        assert service.url == url

    live = Service(
        endpoint_id="live-service",
        name="Live",
        description="Live service",
        url="https://provider.example/buy",
        recipient="0x" + "12" * 20,
        price_cents=40,
        input_schema={"type": "object"},
        enabled=True,
        mode="live",
        supports_idempotency=True,
    )
    assert live.settlement == "mpp"

    loaded = _catalog(tmp_path, _base_query(url="http://127.0.0.1:9/search"))
    assert loaded[0].queries[0].url == "http://127.0.0.1:9/search"
    with pytest.raises(ValueError, match="private, link-local, or localhost"):
        _catalog(tmp_path, _base_query(url="http://10.1.1.1/search"))
    with pytest.raises(ValueError, match="secret_ref"):
        _catalog(tmp_path, _base_query(), secret_ref=None)
    with pytest.raises(ValueError, match="secret_ref"):
        _catalog(tmp_path, _base_query(), secret_ref="")
    with pytest.raises(ValueError, match="recipient"):
        _catalog(tmp_path, _base_query(settlement="mpp"), secret_ref=None)
    mpp = _catalog(
        tmp_path,
        _base_query(settlement="mpp", recipient="0x" + "12" * 20),
        secret_ref=None,
    )
    assert mpp[0].secret_ref is None and mpp[0].queries[0].settlement == "mpp"


async def test_missing_key_or_private_url_does_not_post(monkeypatch):
    monkeypatch.delenv(REF, raising=False)
    settings = ProductSettings(_env_file=None)
    service = api_service()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"answer": "no"})

    store = Mock()
    store.provider_secret_ref.return_value = REF
    caller = ApiKeyCaller(settings, store, transport=httpx.MockTransport(handler))
    row = {
        "execution_id": "exe_one",
        "payment_status": "unsigned",
        "payload": {"query": "answer"},
        "service": service.model_dump(),
    }
    try:
        with pytest.raises(TerminalFailure, match="not configured"):
            await caller.purchase(row)
        private = service.model_dump()
        private["url"] = "http://10.0.0.1/q"
        with pytest.raises(TerminalFailure, match="not allowed"):
            await caller.purchase({**row, "service": private})
    finally:
        await caller.close()
    assert calls == []
    store.mark_sent.assert_not_called()


@pytest.fixture(scope="module")
def postgres_url():
    url = os.environ.get(
        "OPENMCP_PRODUCT_DATABASE_URL", "postgresql://openmcp:openmcp@localhost:5433/openmcp"
    )
    try:
        with psycopg.connect(url, connect_timeout=2) as connection:
            connection.execute("SELECT 1")
    except psycopg.Error:
        if os.environ.get("OPENMCP_REQUIRE_POSTGRES") == "1":
            pytest.fail("Required PostgreSQL unavailable; API-key purchase tests were not run.")
        pytest.skip("PostgreSQL unavailable; set OPENMCP_REQUIRE_POSTGRES=1 to make this a failure")
    return url


@pytest.fixture
def store(postgres_url):
    name = "product_api_" + uuid.uuid4().hex
    value = Store(postgres_url, name)
    value.migrate()
    try:
        yield value
    finally:
        with psycopg.connect(postgres_url) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


def credit(store, account_id, amount=1000):
    top = store.create_top_up(account_id, uuid.uuid4().hex, amount)
    session = {
        "id": "cs_" + top["id"],
        "url": "https://checkout.stripe.com/c/pay/test",
        "status": "complete",
        "expires_at": int(time.time()) + 1000,
        "payment_intent": "pi_" + top["id"],
    }
    store.checkout_state(top["id"], session, paid=True)
    return top


def grant(store, account_id, cap=200):
    agent = store.create_agent(account_id, "Research", cap, now() + timedelta(days=1))
    credential = store.issue(account_id, agent["agent_id"])
    return store.authenticate_agent(credential["secret"]), credential


def purchase(service):
    return {
        "endpoint_id": service.endpoint_id,
        "payload": {"query": "answer"},
        "max_price_cents": service.price_cents,
    }


class Closable:
    async def close(self):
        return None


def _worker(store, handler):
    settings = ProductSettings(_env_file=None)
    caller = ApiKeyCaller(settings, store, transport=httpx.MockTransport(handler))
    treasury = Mock()
    treasury.purchase = AsyncMock(side_effect=AssertionError("MPP settlement must not run"))
    worker = Worker(settings, store, Mock(), treasury, caller)
    return worker, caller


def _reserve(store, service):
    store.sync_catalog([provider_for(service)])
    owner = store.bootstrap("subject")["account_id"]
    credit(store, owner)
    principal, credential = grant(store, owner)
    row = store.reserve(principal, "buy", purchase(service), service)
    return principal, credential, row


def _assert_secret_absent(blob):
    assert SECRET not in blob
    assert REF not in blob
    assert "secret_ref" not in blob


async def test_api_key_purchase_spends_credits_once_and_hides_the_key(store, monkeypatch):
    monkeypatch.setenv(REF, SECRET)
    service = api_service()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"answer": "found"})

    worker, caller = _worker(store, handler)
    principal, credential, row = _reserve(store, service)
    loaded = store.catalog_service(service.endpoint_id)
    assert loaded.settlement == "api_key"
    assert loaded.model_dump() == service.model_dump()
    assert "secret_ref" not in loaded.model_dump()
    with store.connection() as connection:
        saved_ref = connection.execute(
            "SELECT secret_ref FROM providers WHERE provider_id=%s", ("web-search-co",)
        ).fetchone()["secret_ref"]
    assert saved_ref == REF
    try:
        await worker.tick()
        done = store.execution_internal(row["execution_id"])
        assert len(calls) == 1
        sent = calls[0]
        assert sent.headers["authorization"] == f"Bearer {SECRET}"
        assert sent.headers["idempotency-key"] == row["execution_id"]
        assert sent.headers["x-openmcp-execution-id"] == row["execution_id"]
        assert json.loads(sent.content) == {"query": "answer"}
        assert done["status"] == "completed"
        assert done["payment_status"] == "confirmed"
        assert done["charged_cents"] == 40
        assert done["data"] == {"answer": "found"}
        assert done["provider_receipt"] == {"method": "api_key", "status": "success"}
        account = store.account(principal.account_id)
        assert account["balance_cents"] == 960
        assert account["reserved_cents"] == 0
        assert account["spent_cents"] == 40
        with store.connection() as connection:
            agent = connection.execute(
                "SELECT spent_cents, reserved_cents FROM agents WHERE agent_id=%s",
                (principal.agent_id,),
            ).fetchone()
        assert agent["spent_cents"] == 40 and agent["reserved_cents"] == 0
        _assert_secret_absent(json.dumps(done, default=str))

        replay = store.reserve(principal, "buy", purchase(service), service)
        assert replay["execution_id"] == row["execution_id"]
        await worker.tick()
        await worker.execution(store.execution_internal(row["execution_id"]), None)
        assert len(calls) == 1

        app = create_app(
            ProductSettings(_env_file=None), store=store, verifier=Closable(), stripe=Closable()
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api.example"
        ) as client:
            response = await client.post(
                "/v1/discover",
                headers={"Authorization": "Bearer " + credential["secret"]},
                json={"query": "search"},
            )
        assert response.status_code == 200
        body = response.json()
        sample = body["providers"][0]["queries"][0]
        assert "url" not in sample and "recipient" not in sample
        _assert_secret_absent(json.dumps(body))
    finally:
        await caller.close()


async def test_missing_api_key_refunds_without_calling(store, monkeypatch):
    monkeypatch.delenv(REF, raising=False)
    service = api_service()
    calls = []
    worker, caller = _worker(store, lambda request: calls.append(request))
    principal, _, row = _reserve(store, service)
    try:
        await worker.tick()
    finally:
        await caller.close()
    assert calls == []
    done = store.execution_internal(row["execution_id"])
    assert done["status"] == "refunded"
    assert done["payment_status"] == "unsigned"
    assert done["refunded_cents"] == 40
    assert done["charged_cents"] == 0
    account = store.account(principal.account_id)
    assert account["balance_cents"] == 1000
    assert account["reserved_cents"] == 0
    assert store.service_disabled(service.endpoint_id) is False
    _assert_secret_absent(json.dumps(done, default=str))


async def test_private_url_on_a_reserved_execution_refunds_without_calling(store, monkeypatch):
    monkeypatch.setenv(REF, SECRET)
    service = api_service()
    calls = []
    worker, caller = _worker(store, lambda request: calls.append(request))
    _, _, row = _reserve(store, service)
    tampered = dict(row["service"])
    tampered["url"] = "http://192.168.0.8/q"
    with store.connection() as connection:
        connection.execute(
            "UPDATE executions SET service=%s WHERE execution_id=%s",
            (Jsonb(tampered), row["execution_id"]),
        )
    try:
        await worker.tick()
    finally:
        await caller.close()
    assert calls == []
    done = store.execution_internal(row["execution_id"])
    assert done["status"] == "refunded"
    assert done["payment_status"] == "unsigned"
    assert store.service_disabled(service.endpoint_id) is False


@pytest.mark.parametrize("failure", ["status", "timeout"])
async def test_failure_after_sent_holds_without_refund_retry_or_disable(store, monkeypatch, failure):
    monkeypatch.setenv(REF, SECRET)
    service = api_service()
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.TimeoutException("timed out")
        return httpx.Response(502, text="unavailable")

    worker, caller = _worker(store, handler)
    principal, _, row = _reserve(store, service)
    try:
        await worker.tick()
        done = store.execution_internal(row["execution_id"])
        assert len(calls) == 1
        assert done["status"] == "needs_review"
        assert done["payment_status"] == "sent"
        assert done["charged_cents"] == 0
        assert done["refunded_cents"] == 0
        account = store.account(principal.account_id)
        assert account["balance_cents"] == 1000
        assert account["reserved_cents"] == 40
        assert account["spent_cents"] == 0
        assert store.service_disabled(service.endpoint_id) is False
        _assert_secret_absent(json.dumps(done, default=str))

        store.requeue(row["execution_id"])
        await worker.tick()
        again = store.execution_internal(row["execution_id"])
        assert len(calls) == 1
        assert again["status"] == "needs_review"
        assert again["payment_status"] == "sent"
        assert store.service_disabled(service.endpoint_id) is False
    finally:
        await caller.close()
